from django.test import SimpleTestCase

from tutoring.richtext import render_rich_text, sanitize_rich_text


class RichTextSanitizerTests(SimpleTestCase):
    def test_render_uses_color_classes_because_csp_blocks_inline_style(self):
        rendered = render_rich_text('<font color="#c0392b">紅</font><span style="color:#aabbcc">他</span>')
        self.assertEqual(rendered, '<span class="rn-color-c0392b">紅</span><span>他</span>')
        self.assertNotIn("style=", rendered)

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


class RichNoteEditorScriptTests(SimpleTestCase):
    """站台 CSP 啟用 Trusted Types,編輯器 JS 不得寫入 innerHTML,否則整個編輯器不會建立。"""

    def test_editor_script_never_assigns_html_sinks(self):
        from pathlib import Path

        from django.conf import settings

        source = (Path(settings.BASE_DIR) / "static/js/rich-note-editor.js").read_text(encoding="utf-8")
        for sink in ("innerHTML =", "outerHTML =", "insertAdjacentHTML", "document.write"):
            self.assertNotIn(sink, source)

    def test_editor_script_emits_markup_the_sanitizer_keeps(self):
        # 編輯器關閉 styleWithCSS 後產生的標記:粗體/斜體/<font color>,清理器都必須保留。
        cleaned = sanitize_rich_text('<b><i><font color="#c0392b">字</font></i></b>')
        self.assertEqual(cleaned, '<b><i><span style="color:#c0392b">字</span></i></b>')
