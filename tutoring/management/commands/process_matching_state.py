from django.core.management.base import BaseCommand

from tutoring.services import synchronize_matching_state


class Command(BaseCommand):
    help = "Synchronize invitations, pairings, releases, and expired semester settings."

    def handle(self, *args, **options):
        result = synchronize_matching_state()
        self.stdout.write(
            self.style.SUCCESS(
                "Matching state synchronized: "
                f"expired invitations={result['expired_invitations']}, "
                f"semester-ended pairings={result['ended_pairings']}, "
                f"automatic releases={result['auto_releases']}, "
                f"archived semesters={result['archived_semesters']}."
            )
        )
