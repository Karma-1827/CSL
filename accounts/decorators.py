from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect


def role_required(*roles):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect("accounts:login")
            if request.user.role not in roles:
                messages.error(request, "您沒有此功能的權限。 / You do not have permission to use this feature.")
                return redirect("accounts:dashboard")
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator

