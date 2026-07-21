from collections import defaultdict
from io import BytesIO
import re
from xml.sax.saxutils import escape

from django.db.models import Q
from django.conf import settings
from django.utils import timezone

from accounts.models import ProgramSource, Role, User

from .models import ClassSession, ClassSessionStatus, Semester
from .services import LEVEL_LABELS, class_is_valid


def user_has_hour_records(user):
    if user.role == Role.TUTOR:
        return True
    return bool(
        user.role == Role.TUTEE
        and user.roster_entry
        and user.roster_entry.program_source in {ProgramSource.MARYLAND, ProgramSource.OTHER}
    )


def valid_sessions_for_user(user, starts_on, ends_on):
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
    return [row for row in rows if class_is_valid(row)]


def hour_report_data(user, starts_on, ends_on):
    sessions = valid_sessions_for_user(user, starts_on, ends_on)
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
    return {
        "user": user,
        "starts_on": starts_on,
        "ends_on": ends_on,
        "sections": result,
        "total": sum(row.duration for row in sessions),
        "generated_at": timezone.localtime(),
    }


def build_hours_pdf(data, *, version="summary", detail_fields=()):
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
    english_font_name = "CertificateTimesNewRoman"
    english_bold_font_name = "CertificateTimesNewRoman-Bold"
    if font_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(font_name, settings.BASE_DIR / "assets/fonts/Kaiu.ttf"))
    if bold_font_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(bold_font_name, settings.BASE_DIR / "assets/fonts/Kaiu.ttf"))
    if english_font_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(english_font_name, settings.BASE_DIR / "assets/fonts/TimesNewRoman.ttf"))
    if english_bold_font_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(english_bold_font_name, settings.BASE_DIR / "assets/fonts/TimesNewRoman-Bold.ttf"))
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
    partner_certificate = bool(
        user.role == Role.TUTEE
        and roster
        and roster.program_source in {ProgramSource.MARYLAND, ProgramSource.OTHER}
    )
    template_name = "maryland_hours_certificate.pdf" if partner_certificate else "ntnu_csl_hours_certificate.pdf"
    template_path = settings.BASE_DIR / "tutoring/resources/certificate_templates" / template_name

    def hours_text(value):
        value = str(value)
        return value[:-2] if value.endswith(".0") else value

    def roc_date(value):
        return f"中華民國 {value.year - 1911} 年 {value.month} 月 {value.day} 日"

    def period_text():
        start, end = data["starts_on"], data["ends_on"]
        return (
            f"民國 {start.year - 1911} 年 {start.month} 月 {start.day} 日至"
            f"民國 {end.year - 1911} 年 {end.month} 月 {end.day} 日"
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

    plan_name = "華語語言交換計畫" if partner_certificate else "外籍生華語輔導計畫"
    activity = "完成語言交換" if partner_certificate else "擔任華語輔導小老師，完成輔導服務"
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
        f"於 <b>{period_text()}</b> 期間，參與國立臺灣師範大學華語文教學系"
        f"「<b>{plan_name}</b>」，{activity}共計 "
        f'<font name="{english_bold_font_name}">{hours_text(data["total"])}</font>'
        f"<b> 小時</b>，特此證明。"
    )
    summary_paragraph_style = ParagraphStyle(
        "CertificateSummaryBody", fontName=font_name, fontSize=15, leading=30,
        alignment=TA_JUSTIFY, firstLineIndent=30, textColor=colors.HexColor("#151515"),
        wordWrap="CJK",
    )
    detail_paragraph_style = ParagraphStyle(
        "CertificateDetailBody", fontName=font_name, fontSize=14, leading=27,
        alignment=TA_JUSTIFY, firstLineIndent=28, textColor=colors.HexColor("#151515"),
        wordWrap="CJK",
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
        is_summary = version == "summary"
        paragraph_style = summary_paragraph_style if is_summary else detail_paragraph_style
        paragraph_width = 450 if is_summary else 465
        paragraph_x = (page_width - paragraph_width) / 2
        paragraph = Paragraph(certificate_paragraph, paragraph_style)
        _, paragraph_height = paragraph.wrap(paragraph_width, 180)
        if is_summary:
            paragraph_y = 355 - (paragraph_height / 2)
            divider_y = paragraph_y - 24
        else:
            paragraph_y = 555 - paragraph_height
            divider_y = 442
        paragraph.drawOn(pdf_canvas, paragraph_x, paragraph_y)

        pdf_canvas.setStrokeColor(colors.HexColor("#BFA68D"))
        pdf_canvas.setLineWidth(.65)
        pdf_canvas.line(72, divider_y, page_width - 72, divider_y)

        if version == "detailed":
            label = "輔導時數明細" if page_index == 1 else "輔導時數明細（續）"
            pdf_canvas.setFillColor(colors.HexColor("#392E26"))
            pdf_canvas.setFont(bold_font_name, 11.5)
            pdf_canvas.drawString(72, 419, label)
            page_number_style = ParagraphStyle(
                "CertificatePageNumber", fontName=font_name, fontSize=8.5, leading=10,
                alignment=TA_RIGHT, textColor=colors.HexColor("#665B53"),
            )
            page_number = Paragraph(
                f"第 {page_index} 頁，共 {total_pages} 頁 / "
                f'<font name="{english_font_name}">Page {page_index} of {total_pages}</font>',
                page_number_style,
            )
            page_number.wrap(220, 12)
            page_number.drawOn(pdf_canvas, page_width - 292, 414)

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
        issue_date = pdf_canvas.beginText(62, 58)
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


def build_excel_xml(users, *, starts_on=None, ends_on=None):
    """Create a styled Excel 2003 XML workbook without a server-side office dependency."""
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
    headers = ["學號 Student ID", "中文姓名", "英文姓名", "身分 Role", "學期 Semester", "日期 Date", "時間 Time", "時數 Hours", "對方學號", "輔導對象", "狀態 Status"]
    def cell(value, style="Cell"):
        return f'<Cell ss:StyleID="{style}"><Data ss:Type="String">{escape(str(value))}</Data></Cell>'
    body = "".join("<Row>" + "".join(cell(value) for value in row) + "</Row>" for row in rows)
    return (f'''<?xml version="1.0"?><?mso-application progid="Excel.Sheet"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
<Styles><Style ss:ID="Default" ss:Name="Normal"><Alignment ss:Vertical="Center"/><Font ss:FontName="Arial" ss:Size="11"/></Style><Style ss:ID="Header"><Alignment ss:Vertical="Center" ss:Horizontal="Center"/><Font ss:Bold="1" ss:Color="#FFFFFF"/><Interior ss:Color="#0F4C75" ss:Pattern="Solid"/></Style><Style ss:ID="Cell"><Alignment ss:Vertical="Top" ss:WrapText="1"/></Style></Styles>
<Worksheet ss:Name="輔導資料"><Table><Column ss:Width="90"/><Column ss:Width="90"/><Column ss:Width="120"/><Column ss:Width="110"/><Column ss:Width="90"/><Column ss:Width="80"/><Column ss:Width="60"/><Column ss:Width="65"/><Column ss:Width="90"/><Column ss:Width="130"/><Column ss:Width="105"/><Row>{''.join(cell(h, 'Header') for h in headers)}</Row>{body}</Table><WorksheetOptions xmlns="urn:schemas-microsoft-com:office:excel"><FreezePanes/><FrozenNoSplit/><SplitHorizontal>1</SplitHorizontal><TopRowBottomPane>1</TopRowBottomPane><ActivePane>2</ActivePane></WorksheetOptions></Worksheet></Workbook>''').encode("utf-8")
