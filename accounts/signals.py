from django.contrib.admin.models import ADDITION, CHANGE, DELETION, LogEntry
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import AuditLog, User

ADMIN_ACTION_EVENT_TYPES = {
    ADDITION: "ADMIN_ADDED",
    CHANGE: "ADMIN_CHANGED",
    DELETION: "ADMIN_DELETED",
}


@receiver(post_save, sender=LogEntry, dispatch_uid="mirror_admin_log_entry_to_audit_log")
def mirror_admin_log_entry_to_audit_log(sender, instance, created, **kwargs):
    """Mirror every Django Admin add/change/delete into AuditLog (checklist item 15).

    Django Admin already writes its own LogEntry for any CRUD done through the admin
    UI, separate from the AuditLog rows written by our own views/services. This closes
    that gap in one place instead of instrumenting every ModelAdmin individually, so
    future models registered in admin.py are covered automatically. A handful of
    models (e.g. HourAdjustment) already write a more specific AuditLog entry from
    their own save_model()/service code; this adds a second, generic entry alongside
    it rather than trying to detect and suppress the overlap, which isn't worth the
    added complexity for a read-only audit trail.
    """
    if not created:
        return
    event_prefix = ADMIN_ACTION_EVENT_TYPES.get(instance.action_flag, "ADMIN_ACTION")
    model_class = instance.content_type.model_class() if instance.content_type else None
    model_name = model_class.__name__ if model_class else "Unknown"
    target_user = None
    if model_class is User and instance.object_id:
        target_user = User.objects.filter(pk=instance.object_id).first()
    AuditLog.record(
        actor=instance.user,
        target_user=target_user,
        event_type=f"{event_prefix}_{model_name.upper()}",
        description=f"Django Admin: {instance.object_repr}",
        metadata={
            "model": model_name,
            "object_id": instance.object_id,
            "change_message": instance.get_change_message(),
        },
    )
