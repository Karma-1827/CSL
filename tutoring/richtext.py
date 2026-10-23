"""課程審核意見的簡易富文字(粗體/斜體/底線/文字顏色)清理工具。

審核意見由 contenteditable 編輯器產生 HTML,伺服器端一律用白名單重建,不信任前端送來的
內容:只保留少數格式標籤,`style` 只接受 `color`,其餘標籤與屬性全部移除(文字保留)。
刻意只用標準庫 html.parser,不新增第三方依賴。
"""
import html
import re
from html.parser import HTMLParser

from django.utils.safestring import mark_safe

ALLOWED_TAGS = {"b", "strong", "i", "em", "u", "br", "p", "div"}
TAG_ALIASES = {"strong": "b", "em": "i"}
VOID_TAGS = {"br"}
DROP_CONTENT_TAGS = {"script", "style", "iframe", "object", "template"}
HEX_COLOR = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
RGB_COLOR = re.compile(r"^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*(?:,\s*[\d.]+\s*)?\)$")
STYLE_COLOR = re.compile(r"(?:^|;)\s*color\s*:\s*([^;]+)", re.IGNORECASE)
MAX_RICH_NOTE_LENGTH = 5000


def _normalize_color(value):
    value = (value or "").strip()
    if HEX_COLOR.match(value):
        if len(value) == 4:
            value = "#" + "".join(ch * 2 for ch in value[1:])
        return value.lower()
    match = RGB_COLOR.match(value)
    if match:
        channels = [int(part) for part in match.groups()]
        if all(channel <= 255 for channel in channels):
            return "#%02x%02x%02x" % tuple(channels)
    return None


class _Sanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.stack = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in DROP_CONTENT_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        attrs = dict(attrs)
        if tag in ("span", "font"):
            raw = attrs.get("color") if tag == "font" else None
            if raw is None:
                found = STYLE_COLOR.search(attrs.get("style") or "")
                raw = found.group(1) if found else None
            color = _normalize_color(raw)
            if color:
                self.out.append('<span style="color:%s">' % color)
                self.stack.append("span")
            else:
                self.stack.append(None)
            return
        if tag not in ALLOWED_TAGS:
            return
        tag = TAG_ALIASES.get(tag, tag)
        if tag in VOID_TAGS:
            self.out.append("<br>")
            return
        self.out.append("<%s>" % tag)
        self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        if tag == "br" and not self.skip_depth:
            self.out.append("<br>")

    def handle_endtag(self, tag):
        if tag in DROP_CONTENT_TAGS:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth:
            return
        if tag in ("span", "font"):
            if self.stack and (self.stack[-1] == "span" or self.stack[-1] is None):
                closed = self.stack.pop()
                if closed:
                    self.out.append("</span>")
            return
        tag = TAG_ALIASES.get(tag, tag)
        if tag in ALLOWED_TAGS and tag not in VOID_TAGS and tag in self.stack:
            while self.stack:
                closed = self.stack.pop()
                if closed:
                    self.out.append("</%s>" % closed)
                if closed == tag:
                    break

    def handle_data(self, data):
        if not self.skip_depth:
            self.out.append(html.escape(data, quote=False))

    def result(self):
        while self.stack:
            closed = self.stack.pop()
            if closed:
                self.out.append("</%s>" % closed)
        return "".join(self.out)


def sanitize_rich_text(value):
    """回傳只含白名單標籤的 HTML;沒有任何可見文字時回傳空字串。"""
    parser = _Sanitizer()
    parser.feed(value or "")
    parser.close()
    cleaned = parser.result()
    visible = re.sub(r"<[^>]*>", "", cleaned).replace("&nbsp;", " ").replace("\xa0", " ")
    if not visible.strip():
        return ""
    return cleaned.strip()


PALETTE_COLORS = {"8c1d40", "c0392b", "d97706", "1f7a4d", "1d4ed8", "111111"}
SPAN_COLOR = re.compile(r'<span style="color:#([0-9a-f]{6})">')


def _colors_to_classes(cleaned):
    """站台 CSP 的 style-src 'self' 會擋掉行內 style 屬性,顯示時改用 class(CSS 見 app.css 的 .rn-color-*)。
    儲存的資料仍是 style="color:#hex";不在調色盤內的顏色顯示成預設文字色。"""
    def replace(match):
        hex_value = match.group(1)
        if hex_value in PALETTE_COLORS:
            return '<span class="rn-color-%s">' % hex_value
        return "<span>"
    return SPAN_COLOR.sub(replace, cleaned)


def render_rich_text(value):
    """顯示用:純文字舊資料(沒有任何標籤)照舊以換行轉 <br>,其餘重新清理後輸出。"""
    value = value or ""
    if "<" not in value:
        return mark_safe(html.escape(value, quote=False).replace("\r\n", "\n").replace("\n", "<br>"))
    return mark_safe(_colors_to_classes(sanitize_rich_text(value)))
