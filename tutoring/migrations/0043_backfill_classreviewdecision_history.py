from django.db import migrations


def backfill_existing_decisions(apps, schema_editor):
    """2026-10-01(使用者回報「所以通過不會列出所有審核紀錄嗎？」):ClassReviewDecision
    這張歷史表是跟著 0042 新增的,在那之前就已經通過/未通過/待補正的課程完全沒有對應的
    歷史紀錄,導致「審核紀錄」區塊對這些舊資料整個不顯示,看起來像是功能對已通過的課程
    沒有作用。這裡為每一筆「目前狀態已是終局決定、但還沒有任何歷史紀錄」的 ClassReview
    補一筆快照,內容就是該筆目前僅有的那組 status/review_note/reviewed_by/reviewed_at——
    這是我們能確定的唯一一次決定,不是憑空捏造更早的歷程。沒有 reviewed_by 的筆數(即
    0031 那批規則變更時系統自動核准、不是真人審核的「grandfathered」紀錄)刻意跳過,因
    為 ClassReviewDecision.reviewed_by 不可為空,這類本來就沒有對應審核人員可以歸屬。"""
    ClassReview = apps.get_model("tutoring", "ClassReview")
    ClassReviewDecision = apps.get_model("tutoring", "ClassReviewDecision")
    decided = ClassReview.objects.filter(
        status__in=["APPROVED", "REJECTED", "REVISE"], reviewed_by__isnull=False
    )
    for review in decided.iterator():
        if review.decisions.exists():
            continue
        decision = ClassReviewDecision.objects.create(
            review=review,
            status=review.status,
            note=review.review_note,
            reviewed_by_id=review.reviewed_by_id,
        )
        if review.reviewed_at:
            # created_at has auto_now_add=True so .create() always stamps "now"; use
            # .update() afterward (bypasses auto_now_add's pre_save override) so the
            # backfilled entry's timestamp matches when the real decision happened.
            ClassReviewDecision.objects.filter(pk=decision.pk).update(created_at=review.reviewed_at)


def noop_reverse(apps, schema_editor):
    """Not meaningfully reversible: once new decisions are made on top of a backfilled
    entry, we can no longer tell a backfilled row apart from a real one. Leaving rows in
    place on reverse is safer than guessing which ones to delete (same stance as 0031)."""


class Migration(migrations.Migration):

    dependencies = [
        ("tutoring", "0042_classreviewdecision"),
    ]

    operations = [
        migrations.RunPython(backfill_existing_decisions, noop_reverse),
    ]
