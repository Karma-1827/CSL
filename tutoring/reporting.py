from collections import defaultdict
from decimal import Decimal
from io import BytesIO, StringIO
import re
from xml.sax.saxutils import escape

from django.core.exceptions import ValidationError
from django.db.models import Q, Sum
from django.conf import settings
from django.utils import timezone

from accounts.models import EducationLevel, PartnerProgram, Role

from .models import ClassSession, ClassSessionStatus, HourAdjustment
from .services import LEVEL_LABELS, class_is_valid


def user_has_hour_records(user):
    if user.role == Role.TUTOR:
        return True
    return bool(
        user.role == Role.TUTEE
        and user.roster_entry
        and user.roster_entry.program_id
        and user.roster_entry.program.tutee_can_download_hours
    )


def tutor_available_programs(tutor):
    """Distinct partner programs among a tutor's tutees or manual hour adjustments,
    restricted to those with a configured tutor-facing certificate template."""
    session_program_ids = ClassSession.objects.filter(pairing__tutor=tutor).values_list(
        "pairing__tutee__roster_entry__program_id", flat=True
    )
    adjustment_program_ids = HourAdjustment.objects.filter(user=tutor).values_list("program_id", flat=True)
    program_ids = set(session_program_ids) | set(adjustment_program_ids)
    return PartnerProgram.objects.filter(
        pk__in=program_ids
    ).exclude(tutor_certificate_filename="").order_by("name_zh")


def hour_adjustment_total(user, starts_on, ends_on, program=None):
    """Sum manually-credited hours whose semester fully falls within [starts_on, ends_on]."""
    rows = HourAdjustment.objects.filter(
        user=user, semester__starts_on__gte=starts_on, semester__ends_on__lte=ends_on,
    )
    if program is not None:
        rows = rows.filter(program=program)
    return rows.aggregate(total=Sum("hours"))["total"] or Decimal("0")


def valid_sessions_for_user(user, starts_on, ends_on, program=None):
    participant = Q(pairing__tutor=user) if user.role == Role.TUTOR else Q(pairing__tutee=user)
    rows = ClassSession.objects.filter(
        participant,
        status=ClassSessionStatus.SCHEDULED,
        class_date__range=(starts_on, ends_on),
    ).select_related(
        "pairing__semester", "pairing__tutor", "pairing__tutee", "pairing__tutee__tutee_profile"
    ).prefetch_related(
        "attendances", "class_records", "confirmations", "makeup_review"
    ).order_by("class_date", "start_time")
    if program is not None:
        rows = rows.filter(pairing__tutee__roster_entry__program=program)
    return [row for row in rows if class_is_valid(row)]


def hour_report_data(user, starts_on, ends_on, program=None):
    sessions = valid_sessions_for_user(user, starts_on, ends_on, program=program)
    sections = defaultdict(list)
    for session in sessions:
        own_record = next((r for r in session.class_records.all() if r.author_id == user.pk), None)
        counterpart = session.pairing.tutee if user.role == Role.TUTOR else session.pairing.tutor
        student_profile = getattr(session.pairing.tutee, "tutee_profile", None)
        sections[session.pairing.semester].append({
            "session": session,
            "counterpart": counterpart,
            "topic": own_record.topic if own_record else "",
            "student_nationality": student_profile.nationality if student_profile else "—",
            "student_level": LEVEL_LABELS.get(student_profile.overall_level, student_profile.overall_level) if student_profile else "—",
        })
    result = []
    for semester, rows in sorted(sections.items(), key=lambda item: item[0].starts_on):
        result.append({"semester": semester, "rows": rows, "subtotal": sum(r["session"].duration for r in rows)})
    session_total = sum(row.duration for row in sessions)
    adjustment_total = hour_adjustment_total(user, starts_on, ends_on, program=program)
    return {
        "user": user,
        "starts_on": starts_on,
        "ends_on": ends_on,
        "sections": result,
        "session_total": session_total,
        "adjustment_total": adjustment_total,
        "total": session_total + adjustment_total,
        "generated_at": timezone.localtime(),
    }


def build_hours_pdf(data, *, version="summary", detail_fields=(), program=None):
    """Overlay a formal certificate onto the department-provided PDF template."""
    from pypdf import PdfReader, PdfWriter
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas
    from reportlab.platypus import Paragraph, Table, TableStyle

    font_name = "CertificateKai"
    bold_font_name = "CertificateKai-Bold"
    english_font_name = "CertificateSerif"
    english_bold_font_name = "CertificateSerif-Bold"
    if font_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(font_name, settings.BASE_DIR / "assets/fonts/TW-Kai.ttf"))
    if bold_font_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(bold_font_name, settings.BASE_DIR / "assets/fonts/TW-Kai.ttf"))
    if english_font_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(english_font_name, settings.BASE_DIR / "assets/fonts/LiberationSerif-Regular.ttf"))
    if english_bold_font_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(english_bold_font_name, settings.BASE_DIR / "assets/fonts/LiberationSerif-Bold.ttf"))
    pdfmetrics.registerFontFamily(
        font_name,
        normal=font_name,
        bold=bold_font_name,
        italic=font_name,
        boldItalic=bold_font_name,
    )
    pdfmetrics.registerFontFamily(
        english_font_name,
        normal=english_font_name,
        bold=english_bold_font_name,
        italic=english_font_name,
        boldItalic=english_bold_font_name,
    )

    user = data["user"]
    roster = user.roster_entry
    if user.role == Role.TUTEE:
        program = roster.program if roster else None
    if program is None:
        raise ValidationError("此帳號尚未設定合作計畫，無法產生證明。 / No partner program is configured for this account.")
    if user.role == Role.TUTEE:
        template_name = program.tutee_certificate_filename
        title_zh = program.tutee_certificate_title_zh
        title_en = program.tutee_certificate_title_en
        plan_name = program.tutee_certificate_plan_name
        activity = program.tutee_certificate_activity_text
    else:
        template_name = program.tutor_certificate_filename
        title_zh = program.tutor_certificate_title_zh
        title_en = program.tutor_certificate_title_en
        plan_name = program.tutor_certificate_plan_name
        activity = program.tutor_certificate_activity_text
    if not template_name:
        raise ValidationError(
            "此合作計畫尚未設定證明模板，請聯絡系辦。 / This partner program has no certificate template configured."
        )
    template_path = settings.BASE_DIR / "tutoring/resources/certificate_templates" / template_name

    def hours_text(value):
        value = str(value)
        return value[:-2] if value.endswith(".0") else value

    def roc_date(value):
        return f"中華民國 {value.year - 1911} 年 {value.month} 月 {value.day} 日"

    def period_markup():
        start, end = data["starts_on"], data["ends_on"]
        return (
            f"民國 <font name=\"{english_bold_font_name}\">{start.year - 1911}</font> 年 "
            f"{start.month} 月 {start.day} 日至民國 "
            f"<font name=\"{english_bold_font_name}\">{end.year - 1911}</font> 年 "
            f"{end.month} 月 {end.day} 日"
        )

    def month_period_markup():
        start, end = data["starts_on"], data["ends_on"]
        start_year = start.year - 1911
        end_year = end.year - 1911
        bold_number = lambda value: f'<font name="{english_bold_font_name}">{value}</font>'
        if start.year == end.year and start.month == end.month:
            return f"民國{bold_number(start_year)}年{bold_number(start.month)}月"
        if start.year == end.year:
            return (
                f"民國{bold_number(start_year)}年"
                f"{bold_number(start.month)}月-{bold_number(end.month)}月"
            )
        return (
            f"民國{bold_number(start_year)}年{bold_number(start.month)}月-"
            f"{bold_number(end_year)}年{bold_number(end.month)}月"
        )

    latin_run_pattern = re.compile(r"[A-Za-z0-9][A-Za-z0-9 .,/():+\-]*")

    def mixed_font_markup(value, *, bold=False):
        """Use Times New Roman for Latin text while retaining Kaiti for Chinese."""
        value = str(value)
        result = []
        cursor = 0
        latin_font = english_bold_font_name if bold else english_font_name
        for match in latin_run_pattern.finditer(value):
            result.append(escape(value[cursor:match.start()]))
            result.append(f'<font name="{latin_font}">{escape(match.group())}</font>')
            cursor = match.end()
        result.append(escape(value[cursor:]))
        markup = "".join(result)
        return f"<b>{markup}</b>" if bold else markup

    certificate_lead = None
    is_ntnu_tutor = program.code == "NTNU" and user.role == Role.TUTOR
    if is_ntnu_tutor:
        education_level_labels = {
            EducationLevel.BACHELOR: "大學部",
            EducationLevel.MASTER: "碩士班",
            EducationLevel.DOCTORAL: "博士班",
        }
        level_label = education_level_labels.get(roster.education_level, "") if roster else ""
        certificate_lead = (
            f"本系{level_label}學生 "
            f'<font name="{bold_font_name}"><b>{escape(user.name_zh)}</b></font>，學號'
            f'<font name="{english_bold_font_name}">{escape(user.username)}</font>，'
        )
        certificate_paragraph = (
            f"於{month_period_markup()}，"
            f"於本校擔任國際生華語輔導老師，總計授課 "
            f'<font name="{english_bold_font_name}">{hours_text(data["total"])}</font>'
            f"<b> 小時</b>。特此證明"
        )
        summary_paragraph_style = ParagraphStyle(
            "CertificateSummaryBodyNtnuTutor", fontName=font_name, fontSize=20, leading=43,
            alignment=TA_JUSTIFY, firstLineIndent=0,
            textColor=colors.HexColor("#151515"), wordWrap="CJK",
        )
    else:
        if user.name_zh and user.name_en:
            display_name = (
                f"<b>{escape(user.name_zh)}</b> / "
                f'<font name="{english_bold_font_name}">{escape(user.name_en)}</font>'
            )
        else:
            display_name = mixed_font_markup(user.bilingual_name, bold=True)
        certificate_paragraph = (
            f"茲證明 {display_name} 同學（學號："
            f'<font name="{english_bold_font_name}">{escape(user.username)}</font>），'
            f"於 <b>{period_markup()}</b> 期間，參與國立臺灣師範大學華語文教學系"
            f"「<b>{plan_name}</b>」，{activity}共計 "
            f'<font name="{english_bold_font_name}">{hours_text(data["total"])}</font>'
            f"<b> 小時</b>，特此證明。"
        )
        summary_paragraph_style = ParagraphStyle(
            "CertificateSummaryBody", fontName=font_name, fontSize=15, leading=34,
            alignment=TA_JUSTIFY, firstLineIndent=30, textColor=colors.HexColor("#151515"),
            wordWrap="CJK",
        )
    detail_paragraph_style = ParagraphStyle(
        "CertificateDetailBody", fontName=font_name,
        fontSize=15.5 if is_ntnu_tutor else 14,
        leading=34 if is_ntnu_tutor else 31,
        alignment=TA_JUSTIFY, firstLineIndent=0 if is_ntnu_tutor else 28,
        textColor=colors.HexColor("#151515"),
        wordWrap="CJK",
    )
    summary_lead_style = ParagraphStyle(
        "CertificateSummaryLead", fontName=font_name, fontSize=21, leading=28,
        alignment=0, textColor=colors.HexColor("#151515"), wordWrap="CJK",
    )
    detail_lead_style = ParagraphStyle(
        "CertificateDetailLead", fontName=font_name, fontSize=17, leading=23,
        alignment=0, textColor=colors.HexColor("#151515"), wordWrap="CJK",
    )
    small_style = ParagraphStyle(
        "CertificateCell", fontName=font_name, fontSize=9.5, leading=12,
        alignment=TA_CENTER, textColor=colors.HexColor("#221D19"),
    )

    ordered_fields = [key for key in ("date", "nationality", "level", "hours") if key in detail_fields]
    field_config = {
        "date": (f"日期<br/><font name='{english_font_name}' size='8'>Date</font>", 1.2),
        "nationality": (f"學生國籍<br/><font name='{english_font_name}' size='8'>Nationality</font>", 1.35),
        "level": (f"學生程度<br/><font name='{english_font_name}' size='8'>Chinese level</font>", 1.3),
        "hours": (f"時數<br/><font name='{english_font_name}' size='8'>Hours</font>", .75),
    }
    detail_rows = []
    for section in data["sections"]:
        for row in section["rows"]:
            session = row["session"]
            values = {
                "date": session.class_date.strftime("%Y/%m/%d"),
                "nationality": row["student_nationality"],
                "level": row["student_level"],
                "hours": hours_text(session.duration),
            }
            detail_rows.append([values[key] for key in ordered_fields])

    rows_per_page = 8
    chunks = [detail_rows[index:index + rows_per_page] for index in range(0, len(detail_rows), rows_per_page)]
    if not chunks:
        chunks = [[]]
    if version == "summary":
        chunks = [None]

    overlay_buffer = BytesIO()
    pdf_canvas = canvas.Canvas(overlay_buffer, pagesize=A4)
    page_width, _ = A4
    total_pages = len(chunks)
    for page_index, chunk in enumerate(chunks, start=1):
        if title_zh:
            # DFKai-SB has no separate bold face. Fill-and-stroke preserves the
            # requested Kaiti typeface while giving the title a visible bold weight.
            pdf_canvas.saveState()
            pdf_canvas.setFillColor(colors.HexColor("#151515"))
            pdf_canvas.setStrokeColor(colors.HexColor("#151515"))
            pdf_canvas.setLineWidth(.22)
            title_text = pdf_canvas.beginText(
                (page_width - pdfmetrics.stringWidth(title_zh, bold_font_name, 22)) / 2,
                635,
            )
            title_text.setFont(bold_font_name, 22)
            title_text.setTextRenderMode(2)
            title_text.textLine(title_zh)
            pdf_canvas.drawText(title_text)
            pdf_canvas.restoreState()
        if title_en:
            pdf_canvas.setFillColor(colors.HexColor("#151515"))
            pdf_canvas.setFont(english_bold_font_name, 13)
            pdf_canvas.drawCentredString(page_width / 2, 612, title_en)

        is_summary = version == "summary"
        paragraph_style = summary_paragraph_style if is_summary else detail_paragraph_style
        paragraph_width = 465
        paragraph_x = (page_width - paragraph_width) / 2
        paragraph_top = 540
        if certificate_lead:
            lead_style = summary_lead_style if is_summary else detail_lead_style
            lead = Paragraph(certificate_lead, lead_style)
            lead_width = 490 if is_summary else paragraph_width
            lead_x = paragraph_x
            _, lead_height = lead.wrap(lead_width, 40)
            lead_y = paragraph_top - lead_height
            lead.drawOn(pdf_canvas, lead_x, lead_y)
            paragraph_top = lead_y - (16 if is_summary else 12)
        paragraph = Paragraph(certificate_paragraph, paragraph_style)
        _, paragraph_height = paragraph.wrap(paragraph_width, 180)
        paragraph_y = paragraph_top - paragraph_height
        paragraph.drawOn(pdf_canvas, paragraph_x, paragraph_y)

        if version == "detailed":
            label = "輔導時數明細" if page_index == 1 else "輔導時數明細（續）"
            pdf_canvas.setFillColor(colors.HexColor("#392E26"))
            pdf_canvas.setFont(bold_font_name, 11.5)
            pdf_canvas.drawString(72, 419, label)
            page_number_style = ParagraphStyle(
                "CertificatePageNumber", fontName=bold_font_name, fontSize=11.5, leading=14,
                alignment=TA_RIGHT, textColor=colors.HexColor("#392E26"),
            )
            page_number = Paragraph(
                f"第 {page_index} 頁，共 {total_pages} 頁 / "
                f'<font name="{english_bold_font_name}">Page {page_index} of {total_pages}</font>',
                page_number_style,
            )
            page_number.wrap(280, 16)
            page_number.drawOn(pdf_canvas, page_width - 352, 416)

            headers = [Paragraph(field_config[key][0], small_style) for key in ordered_fields]
            if chunk:
                body = [[Paragraph(mixed_font_markup(value), small_style) for value in row] for row in chunk]
            else:
                body = [[Paragraph("此期間沒有有效時數紀錄 / No verified records", small_style)] + [""] * (len(headers) - 1)]
            weights = [field_config[key][1] for key in ordered_fields]
            total_weight = sum(weights) or 1
            column_widths = [465 * weight / total_weight for weight in weights]
            table = Table([headers] + body, colWidths=column_widths, rowHeights=[34] + [29] * len(body))
            table_style = [
                ("FONTNAME", (0, 0), (-1, -1), font_name),
                ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.91, 0.87, 0.82, alpha=.42)),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#2A211B")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ]
            for row_index in range(1, len(body) + 1):
                if row_index % 2 == 0:
                    table_style.append(("BACKGROUND", (0, row_index), (-1, row_index), colors.Color(0.96, 0.93, 0.89, alpha=.24)))
            if not chunk and len(headers) > 1:
                table_style.append(("SPAN", (0, 1), (-1, 1)))
            table.setStyle(TableStyle(table_style))
            _, table_height = table.wrap(465, 330)
            table.drawOn(pdf_canvas, 65, 402 - table_height)

        pdf_canvas.saveState()
        pdf_canvas.setFillColor(colors.HexColor("#171310"))
        pdf_canvas.setStrokeColor(colors.HexColor("#171310"))
        pdf_canvas.setLineWidth(.3)
        issue_date = pdf_canvas.beginText(62, 65.5)
        issue_date.setFont(font_name, 22)
        issue_date.setTextRenderMode(2)
        issue_date.textLine(roc_date(data["generated_at"].date()))
        pdf_canvas.drawText(issue_date)
        pdf_canvas.restoreState()
        pdf_canvas.showPage()
    pdf_canvas.save()

    overlay_buffer.seek(0)
    overlay_reader = PdfReader(overlay_buffer)
    writer = PdfWriter()
    for overlay_page in overlay_reader.pages:
        page = PdfReader(str(template_path)).pages[0]
        page.merge_page(overlay_page)
        writer.add_page(page)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


EXPORT_HEADERS = ["學號 Student ID", "中文姓名", "英文姓名", "身分 Role", "學期 Semester", "日期 Date", "時間 Time", "時數 Hours", "對方學號", "輔導對象", "狀態 Status"]


def _export_rows(users, *, starts_on=None, ends_on=None):
    rows = []
    for user in users:
        participant = Q(pairing__tutor=user) if user.role == Role.TUTOR else Q(pairing__tutee=user)
        sessions = ClassSession.objects.filter(participant).select_related(
            "pairing__semester", "pairing__tutor", "pairing__tutee"
        ).prefetch_related("attendances", "class_records", "confirmations", "makeup_review")
        if starts_on:
            sessions = sessions.filter(class_date__gte=starts_on)
        if ends_on:
            sessions = sessions.filter(class_date__lte=ends_on)
        for session in sessions:
            counterpart = session.pairing.tutee if user.role == Role.TUTOR else session.pairing.tutor
            rows.append([
                user.username, user.name_zh, user.name_en, user.get_role_display(),
                session.pairing.semester.name_zh, str(session.class_date), session.start_time.strftime("%H:%M"),
                str(session.duration), counterpart.username, counterpart.bilingual_name,
                "有效 / Verified" if class_is_valid(session) else "未成立 / Incomplete",
            ])
        if not sessions.exists():
            rows.append([user.username, user.name_zh, user.name_en, user.get_role_display(), "", "", "", "", "", "", "尚無課程 / No classes"])
    return rows


def build_excel_xml(users, *, starts_on=None, ends_on=None):
    """Create a styled Excel 2003 XML workbook without a server-side office dependency."""
    rows = _export_rows(users, starts_on=starts_on, ends_on=ends_on)
    headers = EXPORT_HEADERS
    def cell(value, style="Cell"):
        return f'<Cell ss:StyleID="{style}"><Data ss:Type="String">{escape(str(value))}</Data></Cell>'
    body = "".join("<Row>" + "".join(cell(value) for value in row) + "</Row>" for row in rows)
    return (f'''<?xml version="1.0"?><?mso-application progid="Excel.Sheet"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
<Styles><Style ss:ID="Default" ss:Name="Normal"><Alignment ss:Vertical="Center"/><Font ss:FontName="Arial" ss:Size="11"/></Style><Style ss:ID="Header"><Alignment ss:Vertical="Center" ss:Horizontal="Center"/><Font ss:Bold="1" ss:Color="#FFFFFF"/><Interior ss:Color="#0F4C75" ss:Pattern="Solid"/></Style><Style ss:ID="Cell"><Alignment ss:Vertical="Top" ss:WrapText="1"/></Style></Styles>
<Worksheet ss:Name="輔導資料"><Table><Column ss:Width="90"/><Column ss:Width="90"/><Column ss:Width="120"/><Column ss:Width="110"/><Column ss:Width="90"/><Column ss:Width="80"/><Column ss:Width="60"/><Column ss:Width="65"/><Column ss:Width="90"/><Column ss:Width="130"/><Column ss:Width="105"/><Row>{''.join(cell(h, 'Header') for h in headers)}</Row>{body}</Table><WorksheetOptions xmlns="urn:schemas-microsoft-com:office:excel"><FreezePanes/><FrozenNoSplit/><SplitHorizontal>1</SplitHorizontal><TopRowBottomPane>1</TopRowBottomPane><ActivePane>2</ActivePane></WorksheetOptions></Worksheet></Workbook>''').encode("utf-8")


def build_excel_xlsx(users, *, starts_on=None, ends_on=None):
    """Create a real .xlsx workbook (openpyxl) with the same columns as build_excel_xml()."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    rows = _export_rows(users, starts_on=starts_on, ends_on=ends_on)
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "輔導資料"
    worksheet.append(EXPORT_HEADERS)
    for row in rows:
        worksheet.append(row)
    header_fill = PatternFill(start_color="0F4C75", end_color="0F4C75", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")
    header_alignment = Alignment(horizontal="center", vertical="center")
    for header_cell in worksheet[1]:
        header_cell.fill = header_fill
        header_cell.font = header_font
        header_cell.alignment = header_alignment
    for row_cells in worksheet.iter_rows(min_row=2):
        for data_cell in row_cells:
            data_cell.alignment = Alignment(vertical="top", wrap_text=True)
    for index, width in enumerate([13, 13, 16, 14, 14, 12, 9, 9, 12, 18, 15], start=1):
        worksheet.column_dimensions[get_column_letter(index)].width = width
    worksheet.freeze_panes = "A2"
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def build_export_csv(users, *, starts_on=None, ends_on=None):
    """Create a CSV export with the same columns as build_excel_xml()/build_excel_xlsx().

    Written with a UTF-8 BOM so Excel on Windows opens the Chinese headers/content correctly.
    """
    import codecs
    import csv as csv_module

    rows = _export_rows(users, starts_on=starts_on, ends_on=ends_on)
    buffer = StringIO()
    writer = csv_module.writer(buffer)
    writer.writerow(EXPORT_HEADERS)
    writer.writerows(rows)
    return codecs.BOM_UTF8 + buffer.getvalue().encode("utf-8")
