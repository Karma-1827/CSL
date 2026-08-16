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
        "form-action 'self';"
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response["Content-Security-Policy"] = self.POLICY
        response["Permissions-Policy"] = (
            "camera=(), geolocation=(), microphone=(), payment=(), usb=()"
        )
        return response
