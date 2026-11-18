"""「返回原本位置」(accounts/navigation.py、static/js/page-memory.js)的單元測試。

2026-11-18(使用者回報「回到上一頁都不會留在原本的位置」)。與課程審核流程整合的測試在
`tutoring/tests.py::ClassWorkflowTests`(test_admin_class_detail_back_link_* 等)。
"""

import re
from pathlib import Path
from urllib.parse import urlencode

from django.conf import settings
from django.http import HttpResponse, HttpResponseRedirect
from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse

from accounts.navigation import BackNavigationMiddleware, safe_back_url


class SafeBackUrlTests(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().get("/matching/classes/1/")

    def test_accepts_same_site_paths_with_query_and_fragment(self):
        for value in ("/dashboard/", "/dashboard/#class-review", "/dashboard/?pending_page=2#class-review"):
            self.assertEqual(safe_back_url(value, self.request), value)

    def test_rejects_anything_that_could_leave_the_site(self):
        for value in (
            "", "https://evil.example/", "http://evil.example/", "//evil.example/", "/\\evil.example",
            "javascript:alert(1)", "dashboard/", "/dash\nboard/", "/dash\x00board/",
        ):
            self.assertEqual(safe_back_url(value, self.request), "", value)

    def test_rejects_overlong_values(self):
        self.assertEqual(safe_back_url("/dashboard/?x=" + "a" * 2000, self.request), "")


class BackNavigationMiddlewareTests(SimpleTestCase):
    BACK = "/dashboard/?pending_page=2#class-review"

    def run_middleware(self, method, query, location, status=302):
        def view(request):
            response = HttpResponse(status=status)
            response["Location"] = location
            return response

        # `back` 實際上是放在表單 action 的網址(query string)上,不是 POST 內容。
        path = "/matching/classes/1/review/"
        if query:
            path += "?" + urlencode(query)
        request = getattr(RequestFactory(), method)(path)
        return BackNavigationMiddleware(view)(request)

    def test_dashboard_redirect_on_same_tab_returns_to_the_remembered_page(self):
        response = self.run_middleware("post", {"back": self.BACK}, "/dashboard/#class-review")
        self.assertEqual(response["Location"], self.BACK)

    def test_dashboard_redirect_to_a_different_tab_is_left_alone(self):
        response = self.run_middleware("post", {"back": self.BACK}, "/dashboard/#hours")
        self.assertEqual(response["Location"], "/dashboard/#hours")

    def test_redirect_to_another_page_carries_back_along(self):
        response = self.run_middleware("post", {"back": self.BACK}, "/matching/classes/1/")
        self.assertEqual(
            response["Location"],
            "/matching/classes/1/?back=%2Fdashboard%2F%3Fpending_page%3D2%23class-review",
        )

    def test_existing_back_param_is_not_duplicated(self):
        location = "/matching/classes/1/?back=%2Fdashboard%2F"
        self.assertEqual(self.run_middleware("post", {"back": self.BACK}, location)["Location"], location)

    def test_requests_without_a_valid_back_are_untouched(self):
        for query in ({}, {"back": "https://evil.example/"}, {"back": "//evil.example/"}):
            response = self.run_middleware("post", query, "/dashboard/#class-review")
            self.assertEqual(response["Location"], "/dashboard/#class-review")

    def test_get_requests_are_untouched(self):
        response = self.run_middleware("get", {"back": self.BACK}, "/dashboard/#class-review")
        self.assertEqual(response["Location"], "/dashboard/#class-review")

    def test_absolute_redirects_are_left_alone(self):
        response = self.run_middleware("post", {"back": self.BACK}, "https://elsewhere.example/x")
        self.assertEqual(response["Location"], "https://elsewhere.example/x")

    def test_non_redirect_responses_are_untouched(self):
        def view(request):
            return HttpResponse("ok")

        request = RequestFactory().post("/x/", {"back": self.BACK})
        self.assertEqual(BackNavigationMiddleware(view)(request).content, b"ok")

    def test_redirect_helper_response_is_supported(self):
        def view(request):
            return HttpResponseRedirect("/dashboard/#class-review")

        request = RequestFactory().post("/x/?back=" + "%2Fdashboard%2F%3Fpending_page%3D2%23class-review")
        self.assertEqual(BackNavigationMiddleware(view)(request)["Location"], self.BACK)


class PageMemoryScriptTests(SimpleTestCase):
    """站台 CSP 啟用 Trusted Types(`require-trusted-types-for 'script'`),寫入 HTML 的 JS 會直接被
    瀏覽器丟錯、整支腳本失效,而且只有在真實瀏覽器才看得到。這裡用靜態檢查當安全網。"""

    SCRIPT = Path(settings.BASE_DIR) / "static" / "js" / "page-memory.js"

    def test_script_never_assigns_html_sinks(self):
        source = self.SCRIPT.read_text(encoding="utf-8")
        # 只檢查程式碼本身;說明用的註解可以提到這些字樣。
        source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
        source = re.sub(r"(?m)^\s*//.*$|(?<=\s)//[^\n]*$", "", source)
        for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
            self.assertNotIn(sink, source, sink)

    def test_script_dashboard_path_matches_the_real_url(self):
        self.assertEqual(reverse("accounts:dashboard"), "/dashboard/")
        self.assertIn('const DASHBOARD_PATH = "/dashboard/";', self.SCRIPT.read_text(encoding="utf-8"))
