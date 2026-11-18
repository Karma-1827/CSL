"""「返回原本位置」:從列表點進詳情頁後,「← 返回」與操作後的導向都要回到原本的頁碼/頁籤。

2026-11-18(使用者回報「回到上一頁都不會留在原本的位置,例如我在「等待管理員核准」卡片的
第二頁,點擊某一筆時數,回到上一頁,又變回第一頁」):原本 9 個詳情頁的「← 返回」連結都寫死成
`dashboard#<頁籤>`,不帶 `?pending_page=2` 這類分頁參數,所以一定回到第 1 頁;操作(審核、取消…)
送出後的 redirect 同樣只導回 `#<頁籤>`。

做法(前端 `static/js/page-memory.js` 與這裡搭配):
1. 前端點擊站內連結時,自動在連結後面附上 `?back=<目前完整網址>`(含分頁參數與頁籤 hash)。
   dashboard 上的 POST 表單(審核、儲存、取消…)送出時也一樣附上,所以操作後回到同一頁碼。
2. 詳情頁的「← 返回」讀取 `nav_back`(`back_navigation()` context processor),有值就用它,
   沒有才退回原本寫死的預設網址,所以沒有 JS、直接用網址列開啟時行為與以前完全相同。
3. 詳情頁上的表單送出時,前端也把 `back` 帶進表單 action;`BackNavigationMiddleware` 看到 POST
   後的導向,若是回 dashboard 同一個頁籤就改導回 `back`(帶回頁碼),若是導向別的站內頁面
   (例如操作完又回到同一個詳情頁)就把 `back` 接著帶下去,不用逐一修改每個 view。

`back` 是使用者可控的輸入,必須當成不可信:只接受以單一 `/` 開頭的站內相對路徑,
避免被利用成 open redirect(導向外部網站)。
"""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

BACK_PARAM = "back"
MAX_BACK_LENGTH = 1800
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


def safe_back_url(value, request):
    """回傳可安全使用的站內 `back` 網址;不合格(外部網址、控制字元、過長…)一律回傳空字串。"""
    if not value or len(value) > MAX_BACK_LENGTH:
        return ""
    if not value.startswith("/") or value.startswith("//") or "\\" in value:
        return ""
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return ""
    if not url_has_allowed_host_and_scheme(
        value, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return ""
    return value


def back_navigation(request):
    """Template context:`nav_back` 是驗證過的 `?back=` 網址,沒有或不合格時為空字串。"""
    return {"nav_back": safe_back_url(request.GET.get(BACK_PARAM, ""), request)}


class BackNavigationMiddleware:
    """POST 之後的導向要保留使用者原本所在的頁碼/頁籤(見模組說明)。

    只處理「請求網址帶有合格 `back`」的 POST:
    - 導向 dashboard 同一個頁籤(hash 相同)且 `back` 本身也是 dashboard → 改導回 `back`。
      hash 不同代表 view 刻意把使用者帶去別的頁籤,尊重 view 的決定,不覆寫。
    - 導向其他站內頁面且尚未帶 `back` → 把 `back` 接在後面,讓使用者仍能一路返回原位置。
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.method != "POST" or response.status_code not in _REDIRECT_STATUSES:
            return response
        back = safe_back_url(request.GET.get(BACK_PARAM, ""), request)
        if not back:
            return response
        location = urlsplit(response.get("Location", ""))
        if location.scheme or location.netloc or not location.path.startswith("/"):
            return response

        dashboard_path = reverse("accounts:dashboard")
        if location.path == dashboard_path:
            back_parts = urlsplit(back)
            # view 自己帶了 query string(刻意指定的篩選等)時不覆寫,以免把它丟掉。
            if (
                not location.query
                and back_parts.path == dashboard_path
                and back_parts.fragment == location.fragment
            ):
                response["Location"] = back
            return response

        query = parse_qsl(location.query, keep_blank_values=True)
        if any(key == BACK_PARAM for key, _ in query):
            return response
        query.append((BACK_PARAM, back))
        response["Location"] = urlunsplit(("", "", location.path, urlencode(query), location.fragment))
        return response
