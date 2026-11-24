from django.core.management.base import BaseCommand

from accounts.services import reset_finished_oral_exam
from tutoring.services import synchronize_matching_state


class Command(BaseCommand):
    help = "Synchronize invitations, pairings, releases, and expired semester settings."

    def handle(self, *args, **options):
        result = synchronize_matching_state()
        # 口試當天 17:30 後自動清除本次口試設定(只由背景排程觸發,不在 dashboard 載入時執行)。
        oral_exam_reset = reset_finished_oral_exam()
        self.stdout.write(
            self.style.SUCCESS(
                "Matching state synchronized: "
                f"expired invitations={result['expired_invitations']}, "
                f"semester-ended pairings={result['ended_pairings']}, "
                f"automatic releases={result['auto_releases']}, "
                f"archived semesters={result['archived_semesters']}, "
                f"oral exam reset={oral_exam_reset}."
            )
        )
