import csv
import io
import re
from dataclasses import dataclass, field
from datetime import time

import openpyxl
from django.contrib.sessions.models import Session
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    DepartmentOralExamPass,
    DepartmentOralExamPassListType,
    EducationLevel,
    IdentityCategory,
    OralExamRegistration,
    OralExamRegistrationReviewStatus,
    PartnerProgram,
    Role,
    RosterEntry,
)

ROSTER_IMPORT_COLUMNS = [
    "student_id",
    "name_zh",
    "name_en",
    "role",
    "education_level",
    "identity_category",
    "program_code",
    "is_enabled",
]

_TRUE_VALUES = {"true", "1", "yes", "y", "是", "true "}
_FALSE_VALUES = {"false", "0", "no", "n", "否", ""}


class RosterImportFileError(Exception):
    """檔案本身無法解析（格式錯誤、空檔案、副檔名不支援）。"""


@dataclass
class RosterImportResult:
    created_count: int = 0
    created_ids: list = field(default_factory=list)
    updated_count: int = 0
    updated_ids: list = field(default_factory=list)
    skipped_existing_ids: list = field(default_factory=list)
    skipped_invalid: list = field(default_factory=list)
    errors: list = field(default_factory=list)


def _read_csv_rows(uploaded_file):
    raw = uploaded_file.read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))
    if reader.fieldnames is None:
        raise RosterImportFileError("檔案是空的。 / The file is empty.")
    return list(reader)


def _read_xlsx_rows(uploaded_file):
    workbook = openpyxl.load_workbook(uploaded_file, read_only=True, data_only=True)
    sheet = workbook.worksheets[0]
    rows_iter = sheet.iter_rows(values_only=True)
    try:
        header = next(rows_iter)
    except StopIteration:
        raise RosterImportFileError("檔案是空的。 / The file is empty.")
    header = [str(cell).strip() if cell is not None else "" for cell in header]
    rows = []
    for raw_row in rows_iter:
        if raw_row is None or all(cell is None for cell in raw_row):
            continue
        row = {header[i]: raw_row[i] for i in range(len(header)) if i < len(raw_row)}
        rows.append(row)
    return rows


def _parse_bool(raw_value, row_num, field_name, errors):
    value = "" if raw_value is None else str(raw_value).strip().lower()
    if value in _TRUE_VALUES and value != "":
        return True
    if value in _FALSE_VALUES:
        return False
    errors.append(f"第 {row_num} 列：{field_name} 不是有效的布林值「{raw_value}」。 / Row {row_num}: {field_name} is not a valid boolean.")
    return None


def _clean_str(raw_value):
    if raw_value is None:
        return ""
    return str(raw_value).strip()


def parse_roster_import_rows(uploaded_file):
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        return _read_csv_rows(uploaded_file)
    if name.endswith(".xlsx"):
        return _read_xlsx_rows(uploaded_file)
    raise RosterImportFileError("僅支援 .csv 或 .xlsx 檔案。 / Only .csv or .xlsx files are supported.")


def validate_roster_import_rows(raw_rows):
    errors = []
    entries = []
    skipped_existing_ids = []
    seen_student_ids = set()
    existing_student_ids = set(RosterEntry.objects.values_list("student_id", flat=True))
    programs_by_code = {program.code: program for program in PartnerProgram.objects.all()}

    for index, raw_row in enumerate(raw_rows, start=2):  # row 1 is the header
        student_id = _clean_str(raw_row.get("student_id")).upper()
        name_zh = _clean_str(raw_row.get("name_zh"))
        name_en = _clean_str(raw_row.get("name_en"))
        role = _clean_str(raw_row.get("role")).upper()
        education_level = _clean_str(raw_row.get("education_level")).upper() or EducationLevel.NOT_APPLICABLE
        identity_category = _clean_str(raw_row.get("identity_category")).upper()
        program_code = _clean_str(raw_row.get("program_code")).upper()
        is_enabled = _parse_bool(raw_row.get("is_enabled", "true"), index, "is_enabled", errors)

        if not student_id:
            errors.append(f"第 {index} 列：學號為必填欄位。 / Row {index}: student_id is required.")
            continue
        if not name_zh:
            errors.append(f"第 {index} 列：中文姓名為必填欄位。 / Row {index}: name_zh is required.")
        if role not in {Role.TUTOR, Role.TUTEE}:
            errors.append(f"第 {index} 列：身分「{role}」不是合法值（TUTOR / TUTEE）。 / Row {index}: role must be TUTOR or TUTEE.")
        if education_level not in EducationLevel.values:
            errors.append(f"第 {index} 列：學制「{education_level}」不是合法值。 / Row {index}: invalid education_level.")
        if identity_category not in IdentityCategory.values:
            errors.append(f"第 {index} 列：學生類別「{identity_category}」不是合法值。 / Row {index}: invalid identity_category.")
        program = programs_by_code.get(program_code) if program_code and program_code != "NA" else None
        if program_code and program_code != "NA" and program is None:
            errors.append(f"第 {index} 列：所屬計畫代碼「{program_code}」不存在。 / Row {index}: unknown program_code.")
        if role == Role.TUTEE and program is None:
            errors.append(f"第 {index} 列：Tutee 必須設定所屬計畫。 / Row {index}: program_code is required for tutees.")

        if student_id in seen_student_ids:
            continue  # already handled earlier in this same file; keep the first occurrence
        if student_id in existing_student_ids:
            skipped_existing_ids.append(student_id)
            seen_student_ids.add(student_id)
            continue
        seen_student_ids.add(student_id)

        row_had_error = any(err.startswith(f"第 {index} 列") for err in errors)
        if row_had_error:
            continue

        entry = RosterEntry(
            student_id=student_id,
            name_zh=name_zh,
            name_en=name_en,
            role=role,
            education_level=education_level,
            identity_category=identity_category,
            program=program,
            is_enabled=is_enabled if is_enabled is not None else True,
        )
        try:
            entry.full_clean(exclude=["id"])
        except ValidationError as exc:
            for messages_list in exc.message_dict.values():
                for message in messages_list:
                    errors.append(f"第 {index} 列：{message} / Row {index}: {message}")
            continue
        entries.append(entry)

    return entries, errors, skipped_existing_ids


_TEMPLATE_SAMPLE_ROWS = [
    ["S10112345", "王小明", "Wang Xiao-Ming", "TUTOR", "MASTER", "LOCAL", "NA", "TRUE"],
    ["S20223456", "陳小美", "Chen Xiao-Mei", "TUTEE", "NA", "INTERNATIONAL", "NTNU", "TRUE"],
]


def roster_template_csv_bytes():
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(ROSTER_IMPORT_COLUMNS)
    writer.writerows(_TEMPLATE_SAMPLE_ROWS)
    return buffer.getvalue().encode("utf-8-sig")


def roster_template_xlsx_bytes():
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(ROSTER_IMPORT_COLUMNS)
    for row in _TEMPLATE_SAMPLE_ROWS:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def import_roster_entries(uploaded_file):
    raw_rows = parse_roster_import_rows(uploaded_file)
    if not raw_rows:
        return RosterImportResult(errors=["檔案沒有任何資料列。 / The file has no data rows."])

    entries, errors, skipped_existing_ids = validate_roster_import_rows(raw_rows)
    if errors:
        return RosterImportResult(errors=errors)

    with transaction.atomic():
        for entry in entries:
            entry.save()

    return RosterImportResult(
        created_count=len(entries),
        created_ids=[entry.student_id for entry in entries],
        skipped_existing_ids=skipped_existing_ids,
    )


_STUDENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9]{4,24}$")

_STUDENT_ID_HEADERS = {"學號", "學生學號", "studentid", "student_id"}
_IDENTITY_IMPORT_ALIASES = {
    "local": IdentityCategory.LOCAL,
    "domesticstudent": IdentityCategory.LOCAL,
    "本地生": IdentityCategory.LOCAL,
    "本國生": IdentityCategory.LOCAL,
    "overseas": IdentityCategory.OVERSEAS,
    "overseaschinesestudent": IdentityCategory.OVERSEAS,
    "僑生": IdentityCategory.OVERSEAS,
    "hongkongmacao": IdentityCategory.HONG_KONG_MACAO,
    "hongkongandmacaostudent": IdentityCategory.HONG_KONG_MACAO,
    "港澳生": IdentityCategory.HONG_KONG_MACAO,
    "mainland": IdentityCategory.MAINLAND,
    "mainlandchinesestudent": IdentityCategory.MAINLAND,
    "陸生": IdentityCategory.MAINLAND,
    "international": IdentityCategory.INTERNATIONAL,
    "internationalstudent": IdentityCategory.INTERNATIONAL,
    "foreignstudent": IdentityCategory.INTERNATIONAL,
    "外籍生": IdentityCategory.INTERNATIONAL,
    "外國學生": IdentityCategory.INTERNATIONAL,
    "國際學生": IdentityCategory.INTERNATIONAL,
    # Maryland is represented by PartnerProgram rather than a fifth model-level identity;
    # its registration selector derives MARYLAND from role + program.
    "marylandstudent": IdentityCategory.INTERNATIONAL,
    "馬里蘭學生": IdentityCategory.INTERNATIONAL,
}


def _compact_import_label(raw_value):
    return re.sub(r"[\s/_\-]+", "", _clean_str(raw_value)).lower()


def _parse_quick_identity(raw_value):
    value = _clean_str(raw_value)
    if not value:
        return ""
    compact = _compact_import_label(value)
    if compact in _IDENTITY_IMPORT_ALIASES:
        return _IDENTITY_IMPORT_ALIASES[compact]
    upper_value = value.upper()
    return upper_value if upper_value in IdentityCategory.values else None


def _read_quick_roster_rows(uploaded_file):
    """Read student ID and optional identity from the first two columns.

    Source lists are often messy (a title row, a Chinese header row, stray
    whitespace) rather than a clean export, so this reads every row rather than
    assuming a specific header. The second column remains optional for backwards
    compatibility with historical ID-only lists.
    """
    name = uploaded_file.name.lower()
    values = []
    if name.endswith(".csv"):
        raw = uploaded_file.read().decode("utf-8-sig")
        for row_num, row in enumerate(csv.reader(io.StringIO(raw)), start=1):
            if row and row[0] is not None and str(row[0]).strip():
                identity = row[1] if len(row) > 1 else ""
                values.append((row_num, str(row[0]).strip(), identity))
    elif name.endswith(".xlsx"):
        workbook = openpyxl.load_workbook(uploaded_file, read_only=True, data_only=True)
        sheet = workbook.worksheets[0]
        for row_num, row in enumerate(sheet.iter_rows(values_only=True), start=1):
            cell = row[0] if row else None
            if cell is not None and str(cell).strip():
                identity = row[1] if len(row) > 1 else ""
                values.append((row_num, str(cell).strip(), identity))
    else:
        raise RosterImportFileError("僅支援 .csv 或 .xlsx 檔案。 / Only .csv or .xlsx files are supported.")
    return values


def import_roster_ids(uploaded_file, *, role, program=None):
    """Quick import: student IDs plus an optional identity-category column.

    Role/program still come from the Admin card selected for upload. Identity is
    read from column two when present; re-uploading may fill a previously blank
    identity but never overwrites an existing non-blank administrative value.
    """
    raw_values = _read_quick_roster_rows(uploaded_file)
    if not raw_values:
        return RosterImportResult(errors=["檔案沒有任何資料列。 / The file has no data rows."])

    candidates = {}
    skipped_invalid = []
    for row_num, raw_value, raw_identity in raw_values:
        candidate = raw_value.strip().upper()
        if _compact_import_label(raw_value) in _STUDENT_ID_HEADERS:
            continue
        if not _STUDENT_ID_PATTERN.match(candidate):
            skipped_invalid.append(f"第 {row_num} 列：「{raw_value}」不是有效學號格式，已略過。 / Row {row_num}: not a valid student ID, skipped.")
            continue
        identity_category = _parse_quick_identity(raw_identity)
        if identity_category is None:
            skipped_invalid.append(
                f"第 {row_num} 列：無法識別身分別「{raw_identity}」，已略過。 / "
                f"Row {row_num}: unknown identity category, skipped."
            )
            continue
        if candidate not in candidates or (not candidates[candidate] and identity_category):
            candidates[candidate] = identity_category

    existing_entries = RosterEntry.objects.in_bulk(candidates, field_name="student_id")
    new_ids = [student_id for student_id in candidates if student_id not in existing_entries]
    updated_ids = []
    skipped_existing_ids = []

    with transaction.atomic():
        for student_id in new_ids:
            entry = RosterEntry(
                student_id=student_id,
                role=role,
                program=program,
                identity_category=candidates[student_id],
            )
            entry.full_clean(exclude=["id"])
            entry.save()
        for student_id, entry in existing_entries.items():
            incoming_identity = candidates[student_id]
            if incoming_identity and not entry.identity_category:
                entry.identity_category = incoming_identity
                entry.full_clean(exclude=["id"])
                entry.save(update_fields=["identity_category", "updated_at"])
                updated_ids.append(student_id)
            else:
                skipped_existing_ids.append(student_id)
                if incoming_identity and entry.identity_category != incoming_identity:
                    skipped_invalid.append(
                        f"學號 {student_id} 已有不同身分別，保留系統原資料。 / "
                        f"Student ID {student_id} already has a different identity; existing data was kept."
                    )

    return RosterImportResult(
        created_count=len(new_ids),
        created_ids=new_ids,
        updated_count=len(updated_ids),
        updated_ids=sorted(updated_ids),
        skipped_existing_ids=sorted(skipped_existing_ids),
        skipped_invalid=skipped_invalid,
    )


class OralExamPassListImportError(Exception):
    """檔案本身無法解析，或找不到任何一個含「學號」與「語音」欄位的工作表。"""


@dataclass
class OralExamPassListImportResult:
    matched_count: int = 0
    created_count: int = 0
    sheets_used: list = field(default_factory=list)


def import_department_oral_exam_pass_list(
    uploaded_file, *, admin, list_type=DepartmentOralExamPassListType.ORAL_EXAM_PASS
):
    """匯入系辦提供的資格比對名單，只挑出「語音」欄位值恰好是「通過」的學號。

    來源檔案原本是系辦內部畢業條件追蹤表(NTNU 用，`list_type=ORAL_EXAM_PASS`)，不是專門
    匯出的口語通過名單:標題列不固定在第一列(常見於第一列是報表標題、第二列才是真正的
    欄位標題)，且可能有多個工作表，只有部分工作表含「語音」欄位。因此逐一工作表掃描前
    幾列找出同時含「學號」與「語音」的標題列，找不到的工作表(例如本專案實際踩過的
    「海華碩」分頁，只有外語沒有語音欄位)直接跳過，不視為錯誤。

    「語音」欄位的值在系辦這份表格裡並不一致(通過/完成/有皆曾出現)，這裡刻意只認**完全
    等於**「通過」的儲存格，其餘一律不算通過——這是 2026-09-11 使用者實際核對過原始檔案
    後明確要求的比對規則，不得放寬比對其他相近字串。

    2026-09-24(使用者要求)新增 `list_type=MARYLAND_COURSE_ROSTER`:馬里蘭計畫的口語能力
    資格依據是系辦提供的修課名單，不是語音考試，語意跟 NTNU 完全不同，需要用不同的提示
    文字呈現(見 `DepartmentOralExamPass` docstring)。系辦目前提供的馬里蘭檔案沿用同一種
    「學號＋語音＝通過」欄位格式，因此這裡的解析邏輯不需要跟著分支，只需要把呼叫端選擇
    的 `list_type` 存進比對到的每一筆紀錄。
    """
    try:
        workbook = openpyxl.load_workbook(uploaded_file, read_only=True, data_only=True)
    except Exception as exc:
        raise OralExamPassListImportError("檔案不是有效的 Excel 檔案。 / The file is not a valid Excel file.") from exc

    matched_student_ids = set()
    sheets_used = []
    for sheet in workbook.worksheets:
        rows_iter = sheet.iter_rows(values_only=True)
        header = None
        for _, row in zip(range(5), rows_iter):
            candidate = [str(cell).strip() if cell is not None else "" for cell in row]
            if "學號" in candidate and "語音" in candidate:
                header = candidate
                break
        if header is None:
            continue
        sheets_used.append(sheet.title)
        student_id_index = header.index("學號")
        oral_index = header.index("語音")
        for row in rows_iter:
            student_id = row[student_id_index] if student_id_index < len(row) else None
            oral_value = row[oral_index] if oral_index < len(row) else None
            if not student_id or not isinstance(oral_value, str) or oral_value.strip() != "通過":
                continue
            candidate_id = str(student_id).strip().upper()
            if _STUDENT_ID_PATTERN.match(candidate_id):
                matched_student_ids.add(candidate_id)

    if not sheets_used:
        raise OralExamPassListImportError(
            "找不到任何同時含「學號」與「語音」欄位的工作表。 / "
            "No worksheet with both a \"學號\" and a \"語音\" column was found."
        )

    created_count = 0
    with transaction.atomic():
        for student_id in matched_student_ids:
            _, created = DepartmentOralExamPass.objects.update_or_create(
                student_id=student_id, defaults={"imported_by": admin, "list_type": list_type}
            )
            if created:
                created_count += 1

    return OralExamPassListImportResult(
        matched_count=len(matched_student_ids), created_count=created_count, sheets_used=sheets_used
    )


def count_online_users():
    """Approximate "currently online" as the number of unexpired sessions that belong to
    a logged-in user (2026-09-11,使用者要求). This is the closest honest proxy available
    without adding new tracking infrastructure: it rides on the existing 30 分鐘閒置逾時
    (SESSION_COOKIE_AGE)+SESSION_SAVE_EVERY_REQUEST behavior already used for auto-logout,
    so "online" here means "has a valid session within that same 30-minute window" — not a
    real-time page-view or WebSocket presence signal (this project deliberately doesn't have
    either, see CLAUDE.md 系統邊界). Session data has to be decoded one row at a time because
    `_auth_user_id` lives inside the encoded payload, not as a queryable column.
    """
    count = 0
    for session in Session.objects.filter(expire_date__gt=timezone.now()).iterator():
        if session.get_decoded().get("_auth_user_id"):
            count += 1
    return count


def _oral_exam_candidate_minutes(registration, *, exam_minutes, step_minutes):
    """2026-10-07(使用者要求「根據他們的時間組合排列...考試順序」):每個報名都有三個
    各 30 分鐘的可口試時段(`time_slot_1/2/3`),但實際口試只要 10 分鐘——這裡算出在
    每個 30 分鐘時段內,排在 `step_minutes`(15 分鐘)間隔格線上、且留得下一次完整
    10 分鐘考試的起始時間(以「從午夜算起的分鐘數」表示,方便後面排程比較大小)。
    30 分鐘的時段剛好可以切出 2 個這種起始點(時段開始、時段開始+15 分鐘);
    時段開始+30 分鐘那一點因為考完會超出時段範圍,不計入。"""
    candidates = []
    for slot in registration.time_slots:
        window_start = slot.hour * 60 + slot.minute
        window_end = window_start + 30
        offset = 0
        while window_start + offset + exam_minutes <= window_end:
            candidates.append(window_start + offset)
            offset += step_minutes
    return sorted(set(candidates))


def _oral_exam_try_assign(reg_pk, candidates_by_registration, minute_to_slot_index, match_for_slot, visited):
    """標準的 Kuhn's algorithm augmenting-path 寫法:幫 `reg_pk` 這筆報名找一個還沒
    被佔用、或可以把原本佔用者挪到別的候選時間(遞迴嘗試)的考試時間格。資料量(確認
    報名的 Tutor 數)在本專案的實際使用情境下頂多幾十筆,這種 O(V·E) 寫法已經足夠,
    不需要更複雜的演算法。"""
    for minute in candidates_by_registration[reg_pk]:
        slot_index = minute_to_slot_index[minute]
        if slot_index in visited:
            continue
        visited.add(slot_index)
        occupant_pk = match_for_slot.get(slot_index)
        if occupant_pk is None or _oral_exam_try_assign(
            occupant_pk, candidates_by_registration, minute_to_slot_index, match_for_slot, visited,
        ):
            match_for_slot[slot_index] = reg_pk
            return True
    return False


def schedule_oral_exam_registrations(exam_date, *, exam_minutes=10, step_minutes=15):
    """2026-10-07 新增(使用者要求「下方新增一個卡片「考試名單」，會先有一個按鈕
    「按排考試」，然後把已登記的tutor，根據他們的時間組合排列...考試順序，每位只有
    10分鐘考試時間，所以可以抓15分鐘一人這樣排下來」)。只排已登記
    (`review_status=CONFIRMED`)的報名——還沒登記的 Admin 根本沒核對過,不該排進
    考試名單。

    把每筆報名的三個候選時段展開成多個 15 分鐘間隔的候選考試起始時間
    (`_oral_exam_candidate_minutes()`),再用 Kuhn's algorithm 求「報名 ↔ 候選時間」
    的最大二分匹配(bipartite matching)——這能找到一組「每人一個相異考試時間,且落在
    該人自己申報的可口試時段內」的排法,是這類「每人有多個可用時段、需要互不重疊地
    排出一個時間給每個人」問題的標準解法,比單純依送出時間或時段起始時間「先搶先贏」
    的貪婪排法更能避免原本其實排得出來、卻因為搶位順序不對而漏排的情況。

    成功排入的報名,依考試時間先後給 `exam_order`(1 起算);真的排不進去的(例如
    候選時段嚴重撞車到無法兩全)`exam_time`/`exam_order` 都留空。每次呼叫都會重算
    「目前所有已登記報名」並整批覆寫,不是疊加——比照本功能一路以來「只保留目前這次
    結果」的既有慣例(見 `OralExamAnnouncement`/報名本身重新送出覆蓋同一筆的設計)。

    回傳 `(scheduled, unscheduled)`,分別是已排入(依考試時間排序)與排不進去的
    `OralExamRegistration` queryset 轉成的 list,方便呼叫端顯示結果或警示訊息。
    """
    registrations = list(
        OralExamRegistration.objects.filter(
            exam_date=exam_date, review_status=OralExamRegistrationReviewStatus.CONFIRMED,
        ).select_related("tutor").order_by("pk")
    )
    candidates_by_registration = {}
    all_minutes = set()
    for registration in registrations:
        candidates = _oral_exam_candidate_minutes(registration, exam_minutes=exam_minutes, step_minutes=step_minutes)
        candidates_by_registration[registration.pk] = candidates
        all_minutes.update(candidates)
    sorted_minutes = sorted(all_minutes)
    minute_to_slot_index = {minute: index for index, minute in enumerate(sorted_minutes)}

    match_for_slot = {}
    for registration in registrations:
        _oral_exam_try_assign(registration.pk, candidates_by_registration, minute_to_slot_index, match_for_slot, set())
    slot_index_for_registration = {reg_pk: slot_index for slot_index, reg_pk in match_for_slot.items()}

    for registration in registrations:
        slot_index = slot_index_for_registration.get(registration.pk)
        if slot_index is None:
            registration.exam_time = None
        else:
            total_minutes = sorted_minutes[slot_index]
            registration.exam_time = time(total_minutes // 60 % 24, total_minutes % 60)
        registration.exam_order = None

    scheduled = sorted((r for r in registrations if r.exam_time is not None), key=lambda r: r.exam_time)
    unscheduled = [r for r in registrations if r.exam_time is None]
    for order, registration in enumerate(scheduled, start=1):
        registration.exam_order = order

    OralExamRegistration.objects.bulk_update(registrations, ["exam_time", "exam_order"])
    return scheduled, unscheduled
