from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect


class FriendlyMethodNotAllowedMiddleware:
    """Turn a stray GET to a `@require_POST` dashboard action into a friendly redirect
    instead of Django's bare, unstyled "Method Not Allowed" text response.

    2026-10-01(使用者回報「網站打不開」):實際發生的情境是 session 在操作途中逾時,
    `@login_required` 把瀏覽器導去登入頁並帶上 `?next=<原本那個只接受 POST 的網址>`;
    重新登入後,Django `LoginView` 預設行為是用 GET 導向這個 `next` 網址,但該網址只有
    `@require_POST` 處理,GET 到這裡只會得到一頁純文字的「Method Not Allowed」,
    沒有任何頁面樣式,對使用者來說看起來就像「網站壞了打不開」。這個網站有 30+ 個
    `@require_POST` 的 dashboard 操作型 view(審核、解除、標記已紀錄等),不是只有單一
    一處,所以在這裡統一攔截比逐一修改每個 view 更不容易漏掉。只處理已登入使用者的
    GET 請求——未登入的請求本來就會被 `@login_required` 攔在前面導去登入頁,不會真的
    走到這裡;刻意不處理其他方法或未登入情境,避免掩蓋其他原因造成的真正 405。
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if response.status_code == 405 and request.method == "GET" and request.user.is_authenticated:
            messages.error(
                request,
                "此連結只能透過按鈕送出操作，請回到頁面重新操作一次。 / "
                "This link can only be used by submitting its form; please go back and try the action again.",
            )
            return redirect("accounts:dashboard")
        return response


class PrivateNoStoreMiddleware:
    """Prevent browsers and shared proxies from retaining sensitive pages.

    Authenticated responses are always private. Registration and account-recovery pages
    receive the same protection even before login because they can display student IDs,
    roster information, and security questions. Static assets remain cacheable.
    """

    PUBLIC_SENSITIVE_VIEWS = {
        "accounts:login",
        "accounts:register",
        "accounts:register_confirm",
        "accounts:register_tutor",
        "accounts:register_tutee",
        "accounts:recover",
        "accounts:set_recovered_password",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        view_name = request.resolver_match.view_name if request.resolver_match else ""
        is_sensitive = request.user.is_authenticated or view_name in self.PUBLIC_SENSITIVE_VIEWS
        if is_sensitive and not request.path.startswith(settings.STATIC_URL):
            response["Cache-Control"] = "private, no-store"
            response["Pragma"] = "no-cache"
            response["Expires"] = "0"
        return response


class ContentSecurityPolicyMiddleware:
    """Apply the enforcing browser policy used by every application response.

    The codebase has no inline scripts/styles, event-handler attributes, or external CDN
    resources, so the policy intentionally contains no ``unsafe-inline`` fallback.
    """

    POLICY = (
        "default-src 'self'; "
        "script-src 'self'; "
        "script-src-attr 'none'; "
        "style-src 'self'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'; "
        "form-action 'self'; "
        # 2026-09-10 弱點掃描 Batch B: safe to enforce now that static/js/dashboard.js's
        # only innerHTML use has been replaced with cloneNode/replaceChildren — no script
        # anywhere in the codebase still writes through an innerHTML/outerHTML/
        # insertAdjacentHTML/document.write/eval sink (confirmed by a full-repo grep).
        "require-trusted-types-for 'script'; "
        "trusted-types default;"
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response["Content-Security-Policy"] = self.POLICY
        response["Permissions-Policy"] = (
            "camera=(), geolocation=(), microphone=(), payment=(), usb=()"
        )
        # 2026-09-10 弱點掃描 Batch B: Django has no built-in setting for these two (only
        # SECURE_CROSS_ORIGIN_OPENER_POLICY is built in, already "same-origin" by default
        # since Django 4.0). Safe to add require-corp here because every resource this app
        # loads is same-origin or a data: URI (no external CDN, no iframes — confirmed by a
        # full-repo grep); a cross-origin subresource added later would need its own CORP
        # header or it will be blocked by this policy.
        response["Cross-Origin-Embedder-Policy"] = "require-corp"
        response["Cross-Origin-Resource-Policy"] = "same-origin"
        return response
