from django.test import SimpleTestCase

from tutoring.richtext import render_rich_text, sanitize_rich_text


class RichTextSanitizerTests(SimpleTestCase):
    def test_keeps_basic_formatting_and_normalizes_colors(self):
        cleaned = sanitize_rich_text(
            '<b>粗</b><em>斜</em><span style="color: rgb(192, 57, 43)">紅</span><font color="#abc">藍</font>'
        )
        self.assertEqual(
            cleaned,
            '<b>粗</b><i>斜</i><span style="color:#c0392b">紅</span><span style="color:#aabbcc">藍</span>',
        )

    def test_strips_scripts_attributes_and_unsafe_styles(self):
        cleaned = sanitize_rich_text(
            '<script>alert(1)</script><b onclick="x()">字</b>'
            '<span style="color:red;background:url(javascript:x)">甲</span>'
            '<a href="javascript:x">連結</a><img src=x onerror=y>'
        )
        self.assertEqual(cleaned, "<b>字</b>甲連結")

    def test_escapes_text_and_closes_unclosed_tags(self):
        self.assertEqual(sanitize_rich_text("<b>a &lt;i&gt; b"), "<b>a &lt;i&gt; b</b>")

    def test_blank_content_becomes_empty(self):
        self.assertEqual(sanitize_rich_text("<div><br></div>&nbsp;"), "")

    def test_legacy_plain_text_renders_with_line_breaks_and_escaping(self):
        self.assertEqual(render_rich_text("第一行\n第二行 & 補充"), "第一行<br>第二行 &amp; 補充")
        self.assertEqual(render_rich_text("a <第二行> b"), "a &lt;第二行&gt; b")
