from django.conf import settings


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
