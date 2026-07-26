import csv
import io
import re
from dataclasses import dataclass, field

import openpyxl
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import EducationLevel, IdentityCategory, PartnerProgram, Role, RosterEntry

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


def _read_single_column_values(uploaded_file):
    """Read every non-empty cell from the first column of a CSV/.xlsx file.

    Source lists are often messy (a title row, a Chinese header row, stray
    whitespace) rather than a clean single-column export, so this reads every
    row rather than assuming a specific header.
    """
    name = uploaded_file.name.lower()
    values = []
    if name.endswith(".csv"):
        raw = uploaded_file.read().decode("utf-8-sig")
        for row_num, row in enumerate(csv.reader(io.StringIO(raw)), start=1):
            if row and row[0] is not None and str(row[0]).strip():
                values.append((row_num, str(row[0]).strip()))
    elif name.endswith(".xlsx"):
        workbook = openpyxl.load_workbook(uploaded_file, read_only=True, data_only=True)
        sheet = workbook.worksheets[0]
        for row_num, row in enumerate(sheet.iter_rows(values_only=True), start=1):
            cell = row[0] if row else None
            if cell is not None and str(cell).strip():
                values.append((row_num, str(cell).strip()))
    else:
        raise RosterImportFileError("僅支援 .csv 或 .xlsx 檔案。 / Only .csv or .xlsx files are supported.")
    return values


def import_roster_ids(uploaded_file, *, role, program=None):
    """Quick import: a single-column list of student IDs, classified entirely
    by which category (role/program) the admin picked, matching separately
    supplied source lists per program."""
    raw_values = _read_single_column_values(uploaded_file)
    if not raw_values:
        return RosterImportResult(errors=["檔案沒有任何資料列。 / The file has no data rows."])

    seen = set()
    candidate_ids = []
    skipped_invalid = []
    for row_num, raw_value in raw_values:
        candidate = raw_value.strip().upper()
        if not _STUDENT_ID_PATTERN.match(candidate):
            skipped_invalid.append(f"第 {row_num} 列：「{raw_value}」不是有效學號格式，已略過。 / Row {row_num}: not a valid student ID, skipped.")
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        candidate_ids.append(candidate)

    existing_ids = set(
        RosterEntry.objects.filter(student_id__in=candidate_ids).values_list("student_id", flat=True)
    )
    new_ids = [sid for sid in candidate_ids if sid not in existing_ids]

    with transaction.atomic():
        for student_id in new_ids:
            entry = RosterEntry(
                student_id=student_id,
                role=role,
                program=program,
            )
            entry.full_clean(exclude=["id"])
            entry.save()

    return RosterImportResult(
        created_count=len(new_ids),
        created_ids=new_ids,
        skipped_existing_ids=sorted(existing_ids),
        skipped_invalid=skipped_invalid,
    )
