from tutoring.services import visible_class_document_programs

from .models import Role


def class_documents_menu(request):
    """Whether to show the "上課文件 / Class documents" menu item (item 5).

    The shared app_header.html component is included on every authenticated page across
    both the accounts and tutoring template trees, so this is a context processor rather
    than something each of those views would otherwise need to remember to pass in.
    """
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated or user.role not in {Role.TUTOR, Role.TUTEE}:
        return {"class_documents_visible": False}
    return {"class_documents_visible": bool(visible_class_document_programs(user))}
