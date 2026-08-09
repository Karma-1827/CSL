from django.conf import settings


class PrivateNoStoreMiddleware:
    """Batch 6 item 3 (docs/VULNERABILITY_SCAN_IMPROVEMENTS.md): every response to a
    logged-in request carries Cache-Control: private, no-store, so pressing the browser's
    back button after logout (or on a shared/kiosk machine) can't replay a cached snapshot
    of a dashboard, profile, class record, private attachment, or export. This covers all
    of those pages uniformly (including Django Admin, since /system-admin/ users are also
    authenticated Django users) without having to remember to add the header to every view
    individually. Static assets are exempt since they aren't user/session-specific and
    losing their cache would hurt perceived performance for no security benefit.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.user.is_authenticated and not request.path.startswith(settings.STATIC_URL):
            response["Cache-Control"] = "private, no-store"
        return response


class ContentSecurityPolicyMiddleware:
    """Batch 6 item 5 (docs/VULNERABILITY_SCAN_IMPROVEMENTS.md): ship
    Content-Security-Policy-Report-Only first so the policy can be checked against every
    real page/flow via the browser console without breaking anything, then switch the
    header name to the enforcing Content-Security-Policy once that check is done. The
    policy is deliberately strict (no 'unsafe-inline' anywhere) because this codebase
    already has no inline <script>/<style> blocks or event-handler attributes, and no
    external CDN scripts/fonts/styles (CLAUDE.md: vanilla JS + a single local
    static/css/app.css) — loosening the policy to work around a violation would be
    treating a symptom instead of moving the offending inline code into a static file.
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
        response["Content-Security-Policy-Report-Only"] = self.POLICY
        return response
