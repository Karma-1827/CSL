from datetime import time, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import EducationLevel, IdentityCategory, PartnerProgram, Role, RosterEntry, User
from tutoring.models import (
    ClassAlertReason,
    ClassSession,
    ConfirmationStatus,
    HourAdjustment,
    MatchingInvitation,
    Pairing,
    PairingReleaseReason,
    PairingReleaseRequest,
    PairingStatus,
    PairingMessage,
    QualificationDocument,
    QualificationStatus,
    Semester,
    TuteeProfile,
    TutorProfile,
)
from tutoring.services import (
    check_in,
    confirm_counterpart,
    report_class_alert,
    resolve_incident_report,
    schedule_classes,
    send_invitation,
    submit_class_record,
    submit_incident_report,
    submit_pairing_release_request,
)


class Command(BaseCommand):
    help = (
        "Populate every admin dashboard section (qualifications, matching, pairing releases, "
        "class alerts, incident reports, makeup review, classes, hours) with local-only demo "
        "data. Safe to re-run at any time; existing demo records are reset and rebuilt relative "
        "to the current date."
    )

    def add_arguments(self, parser):
        parser.add_argument("--password", required=True, help="Password to set on every demo account")

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This demo command is disabled when DEBUG is false.")

        self.password = options["password"]
        today = timezone.localdate()

        admin = User.objects.filter(username="DEMO-ADMIN", role=Role.ADMIN).first()
        if admin:
            admin.set_password(self.password)
            admin.save(update_fields=["password"])

        semester = self._ensure_semester(today)
        # Certificates only open 3 days after a semester ends (see CLAUDE.md 4.9), so the
        # always-current active semester above can never be downloaded during a demo. A
        # second, already-ended semester gives the hours/PDF download step something real
        # to show without waiting months for the active semester to close.
        past_semester = self._ensure_past_semester(today)
        ntnu = PartnerProgram.objects.get(code="NTNU")
        maryland = PartnerProgram.objects.get(code="MARYLAND")

        tutor1 = self._ensure_tutor("DEMO-TUTOR", "王小華", "Alex Wang", QualificationStatus.APPROVED)
        tutor2 = self._ensure_tutor("DEMO-TUTOR2", "陳安然", "Jamie Chen", QualificationStatus.APPROVED)
        self._ensure_tutor("DEMO-TUTOR3", "李承宇", "Ryan Lee", QualificationStatus.PENDING)

        tutee1 = self._ensure_tutee("DEMO-TUTEE", "林安娜", "Anna Lin", ntnu)
        tutee2 = self._ensure_tutee("DEMO-TUTEE2", "金智友", "Jiyou Kim", ntnu)
        tutee3 = self._ensure_tutee("DEMO-TUTEE3", "田中愛", "Tanaka Ai", ntnu)
        maryland_tutee = self._ensure_tutee("DEMO-MARYLAND", "測試交換生", "Taylor Demo", maryland)
        # Deliberately left unpaired and uninvited: every other demo tutee above is already
        # matched or already has a pending invitation, so a live "browse -> invite -> accept"
        # walkthrough has nothing free to target. DEMO-TUTOR2 has one open slot (see pairings
        # below) and can invite this account live.
        self._ensure_tutee("DEMO-TUTEE4", "山田花子", "Hanako Yamada", ntnu)
        # A second, unpaired Maryland tutee: DEMO-MARYLAND is already paired, and the
        # "find a tutor" browse screen only shows candidates while unpaired (see
        # accounts/views.py dashboard()), so there was previously no way to demo that
        # Maryland tutees can browse/invite tutors at all.
        self._ensure_tutee("DEMO-MARYLAND2", "白瑞德", "Rhett Baker", maryland)
        self._seed_filter_demo_tutees(ntnu)

        # Two never-registered roster rows so the admin roster/registration stats show a gap.
        RosterEntry.objects.update_or_create(
            student_id="DEMO-UNCLAIMED-T",
            defaults={"role": Role.TUTOR, "is_enabled": True, "claimed_at": None},
        )
        RosterEntry.objects.update_or_create(
            student_id="DEMO-UNCLAIMED-S",
            defaults={"role": Role.TUTEE, "program": ntnu, "is_enabled": True, "claimed_at": None},
        )

        pairing_main = self._ensure_pairing(semester, tutor1, tutee1)
        pairing_second_tutee = self._ensure_pairing(semester, tutor1, tutee3)
        pairing_maryland = self._ensure_pairing(semester, tutor2, maryland_tutee)

        self._reset_class_sessions(pairing_main, pairing_second_tutee, pairing_maryland)
        self._seed_valid_class(pairing_main, tutor1, tutee1, today - timedelta(days=6))
        self._seed_makeup_class(pairing_main, tutor1, tutee1, today - timedelta(days=3))
        self._seed_alert_class(pairing_main, tutor1, tutee1, today - timedelta(days=2))
        self._seed_incident_classes(pairing_main, tutor1, tutee1, today - timedelta(days=4))
        self._seed_upcoming_class(pairing_main, tutor1, today + timedelta(days=14))
        self._seed_valid_class(pairing_second_tutee, tutor1, tutee3, today - timedelta(days=7))
        self._seed_valid_class(pairing_maryland, tutor2, maryland_tutee, today - timedelta(days=5))
        self._seed_upcoming_class(pairing_maryland, tutor2, today + timedelta(days=17))

        self._reset_and_submit_release_request(pairing_second_tutee, tutee3)
        self._reset_and_send_invitation(semester, tutor2, tutee2)
        self._seed_messages(pairing_main, tutor1, tutee1)
        self._seed_messages(pairing_maryland, tutor2, maryland_tutee)
        self._seed_hour_adjustments(semester, tutor1, ntnu, tutor2, maryland)

        past_pairing_main = self._ensure_ended_pairing(past_semester, tutor1, tutee1)
        past_pairing_maryland = self._ensure_ended_pairing(past_semester, tutor2, maryland_tutee)
        self._reset_class_sessions(past_pairing_main, past_pairing_maryland)
        self._seed_valid_class(past_pairing_main, tutor1, tutee1, today - timedelta(days=100))
        self._seed_valid_class(past_pairing_main, tutor1, tutee1, today - timedelta(days=95))
        self._seed_valid_class(past_pairing_maryland, tutor2, maryland_tutee, today - timedelta(days=98))

        self.stdout.write(self.style.SUCCESS("Admin demo data is ready."))
        self.stdout.write(
            "Accounts (all share the password you passed in): DEMO-ADMIN, DEMO-TUTOR, DEMO-TUTOR2, "
            "DEMO-TUTOR3, DEMO-TUTEE, DEMO-TUTEE2, DEMO-TUTEE3, DEMO-TUTEE4, DEMO-MARYLAND, "
            "DEMO-MARYLAND2, DEMO-CAND01..DEMO-CAND10"
        )

    # -- setup helpers -----------------------------------------------------

    def _ensure_semester(self, today):
        Semester.objects.filter(is_active=True).update(is_active=False)
        semester, _ = Semester.objects.update_or_create(
            name_zh="114學年度第3學期",
            defaults={
                "name_en": "114-3 Semester",
                "starts_on": today - timedelta(days=45),
                "ends_on": today + timedelta(days=45),
                "is_active": True,
            },
        )
        return semester

    def _ensure_tutor(self, student_id, name_zh, name_en, qualification_status):
        roster, _ = RosterEntry.objects.update_or_create(
            student_id=student_id,
            defaults={
                "name_zh": name_zh,
                "name_en": name_en,
                "role": Role.TUTOR,
                "education_level": EducationLevel.MASTER,
                "identity_category": IdentityCategory.LOCAL,
                "program": None,
                "is_enabled": True,
                "claimed_at": timezone.now(),
            },
        )
        user, _ = User.objects.update_or_create(
            username=student_id,
            defaults={"role": Role.TUTOR, "roster_entry": roster, "name_zh": name_zh, "name_en": name_en, "is_active": True},
        )
        user.set_password(self.password)
        user.save(update_fields=["password"])
        TutorProfile.objects.update_or_create(
            tutor=user,
            defaults={
                "gender": "MALE",
                "native_language": "Mandarin Chinese",
                "nationality": "Taiwan",
                "department": "華語文教學系",
                "level_listening": 4,
                "level_speaking": 5,
                "level_reading": 4,
                "level_writing": 4,
                "teaching_notes": "重視口語互動與生活會話練習。",
                "available_days": ["MON", "WED", "THU"],
                "available_time_slots": ["13:00-15:00", "17:00-19:00"],
            },
        )
        QualificationDocument.objects.update_or_create(
            tutor=user,
            defaults={
                "file": "qualifications/demo-proof.pdf",
                "original_filename": "demo-proof.pdf",
                "status": qualification_status,
            },
        )
        return user

    def _ensure_tutee(self, student_id, name_zh, name_en, program, profile_overrides=None):
        roster, _ = RosterEntry.objects.update_or_create(
            student_id=student_id,
            defaults={
                "name_zh": name_zh,
                "name_en": name_en,
                "role": Role.TUTEE,
                "education_level": EducationLevel.NOT_APPLICABLE,
                "identity_category": IdentityCategory.INTERNATIONAL,
                "program": program,
                "is_enabled": True,
                "claimed_at": timezone.now(),
            },
        )
        user, _ = User.objects.update_or_create(
            username=student_id,
            defaults={"role": Role.TUTEE, "roster_entry": roster, "name_zh": name_zh, "name_en": name_en, "is_active": True},
        )
        user.set_password(self.password)
        user.save(update_fields=["password"])
        profile_defaults = {
            "gender": "FEMALE",
            "native_language": "英文 (English)",
            "nationality": "United States",
            "department": "Languages",
            "overall_level": "B1",
            "learning_duration": "1_TO_2_YEARS",
            "target_skills": ["LISTENING", "SPEAKING"],
            "skills_to_improve": "希望加強日常會話與課堂討論。",
            "preferred_days": ["TUE", "THU"],
            "preferred_time_slots": ["15:00-17:00"],
        }
        profile_defaults.update(profile_overrides or {})
        TuteeProfile.objects.update_or_create(tutee=user, defaults=profile_defaults)
        return user

    # DEMO-CAND01..10: unpaired/uninvited NTNU tutees spread across every filterable field
    # (gender, TOCFL level, native language, target skills, days, time slots) so the tutor
    # candidate-filter UI has enough variety to demo narrowing down the list.
    FILTER_DEMO_TUTEES = [
        ("DEMO-CAND01", "佐藤美咲", "Misaki Sato", "FEMALE", "日文 (Japanese)", "Japan", "B1", ["SPEAKING", "LISTENING"], ["MON", "WED"], ["13:00-15:00"]),
        ("DEMO-CAND02", "約翰史密斯", "John Smith", "MALE", "英文 (English)", "United States", "A2", ["READING", "WRITING"], ["TUE", "THU"], ["09:00-11:00"]),
        ("DEMO-CAND03", "朴敏英", "Minyoung Park", "FEMALE", "韓文 (Korean)", "South Korea", "B2", ["SPEAKING"], ["FRI"], ["15:00-17:00"]),
        ("DEMO-CAND04", "阮文雄", "Van Hung Nguyen", "MALE", "越南文 (Vietnamese)", "Vietnam", "A1", ["LISTENING", "SPEAKING", "READING"], ["MON", "TUE"], ["17:00-19:00"]),
        ("DEMO-CAND05", "西蒂努哈麗莎", "Siti Nur Halisa", "FEMALE", "印尼文 (Indonesian)", "Indonesia", "C1", ["WRITING"], ["WED", "THU"], ["11:00-13:00"]),
        ("DEMO-CAND06", "頌猜", "Songchai", "NON_BINARY", "泰文 (Thai)", "Thailand", "N", ["LISTENING"], ["MON", "FRI"], ["09:00-11:00", "13:00-15:00"]),
        ("DEMO-CAND07", "皮耶杜邦", "Pierre Dupont", "MALE", "法文 (French)", "France", "B1", ["SPEAKING", "READING"], ["TUE"], ["15:00-17:00"]),
        ("DEMO-CAND08", "瑪麗亞加西亞", "Maria Garcia", "FEMALE", "西班牙文 (Spanish)", "Spain", "A2", ["LISTENING", "WRITING"], ["WED"], ["17:00-19:00"]),
        ("DEMO-CAND09", "馬克斯米勒", "Max Mueller", "MALE", "德文 (German)", "Germany", "C2", ["SPEAKING"], ["THU", "FRI"], ["OTHER"]),
        ("DEMO-CAND10", "安娜伊凡諾娃", "Anna Ivanova", "FEMALE", "俄文 (Russian)", "Russia", "UNKNOWN", ["READING"], ["MON", "WED", "FRI"], ["13:00-15:00"]),
    ]

    def _seed_filter_demo_tutees(self, ntnu):
        for student_id, name_zh, name_en, gender, language, nationality, level, skills, days, slots in self.FILTER_DEMO_TUTEES:
            self._ensure_tutee(
                student_id, name_zh, name_en, ntnu,
                profile_overrides={
                    "gender": gender,
                    "native_language": language,
                    "nationality": nationality,
                    "overall_level": level,
                    "target_skills": skills,
                    "skills_to_improve": "示範用篩選條件資料。",
                    "preferred_days": days,
                    "preferred_time_slots": slots,
                },
            )

    def _ensure_pairing(self, semester, tutor, tutee):
        pairing, _ = Pairing.objects.update_or_create(
            semester=semester,
            tutor=tutor,
            tutee=tutee,
            defaults={"status": PairingStatus.ACTIVE, "ended_at": None, "end_reason": ""},
        )
        return pairing

    def _ensure_past_semester(self, today):
        semester, _ = Semester.objects.update_or_create(
            name_zh="114學年度第2學期",
            defaults={
                "name_en": "114-2 Semester",
                "starts_on": today - timedelta(days=165),
                "ends_on": today - timedelta(days=30),
                "is_active": False,
            },
        )
        return semester

    def _ensure_ended_pairing(self, semester, tutor, tutee):
        pairing, _ = Pairing.objects.update_or_create(
            semester=semester,
            tutor=tutor,
            tutee=tutee,
            defaults={"status": PairingStatus.ENDED, "ended_at": timezone.now(), "end_reason": "學期結束"},
        )
        return pairing

    def _reset_class_sessions(self, *pairings):
        ClassSession.objects.filter(pairing__in=pairings).delete()

    def _create_past_session(self, *, pairing, tutor, class_date, start_time, duration=Decimal("1")):
        # schedule_classes() refuses anything not in the future (a real tutor could never
        # schedule a past class), so past-dated demo sessions are created directly instead.
        session = ClassSession(
            pairing=pairing, class_date=class_date, start_time=start_time, duration=duration, created_by=tutor,
        )
        session.full_clean()
        session.save()
        return session

    # -- class scenarios -----------------------------------------------------

    def _seed_valid_class(self, pairing, tutor, tutee, class_date):
        session = self._create_past_session(pairing=pairing, tutor=tutor, class_date=class_date, start_time=time(10, 0))
        on_time = session.ends_at + timedelta(minutes=5)
        check_in(session_id=session.pk, participant=tutor, now=on_time)
        check_in(session_id=session.pk, participant=tutee, now=on_time + timedelta(minutes=5))
        submit_class_record(
            session_id=session.pk, author=tutor,
            data={"location": "線上 Google Meet", "topic": "日常會話練習", "content": "練習點餐與問路的情境對話。", "skills_practiced": ["SPEAKING", "LISTENING"], "remarks": "學生表現積極，發音持續進步。"},
            now=on_time + timedelta(minutes=10),
        )
        submit_class_record(
            session_id=session.pk, author=tutee,
            data={"location": "線上 Google Meet", "topic": "日常會話練習", "content": "今天學到點餐跟問路怎麼說。", "skills_practiced": ["SPEAKING"], "remarks": "希望下次多練習聽力。"},
            now=on_time + timedelta(minutes=15),
        )
        confirm_counterpart(session_id=session.pk, reviewer=tutor, status=ConfirmationStatus.CONFIRMED)
        confirm_counterpart(session_id=session.pk, reviewer=tutee, status=ConfirmationStatus.CONFIRMED)
        return session

    def _seed_makeup_class(self, pairing, tutor, tutee, class_date):
        session = self._create_past_session(pairing=pairing, tutor=tutor, class_date=class_date, start_time=time(10, 0))
        check_in(session_id=session.pk, participant=tutor, reason="忘記在課堂結束後立即簽到，事後補簽。")
        check_in(session_id=session.pk, participant=tutee, reason="臨時斷線，事後補簽到。")
        record_data = {"location": "線上 Google Meet", "topic": "聽力與口說練習", "content": "補交課堂紀錄。", "skills_practiced": ["LISTENING"], "remarks": ""}
        submit_class_record(session_id=session.pk, author=tutor, data=record_data, reason="延誤填寫，補交課堂紀錄。")
        submit_class_record(session_id=session.pk, author=tutee, data=record_data, reason="延誤填寫，補交課堂紀錄。")
        confirm_counterpart(session_id=session.pk, reviewer=tutor, status=ConfirmationStatus.CONFIRMED)
        confirm_counterpart(session_id=session.pk, reviewer=tutee, status=ConfirmationStatus.CONFIRMED)
        return session

    def _seed_alert_class(self, pairing, tutor, tutee, class_date):
        session = self._create_past_session(pairing=pairing, tutor=tutor, class_date=class_date, start_time=time(11, 0))
        report_class_alert(
            session_id=session.pk, reporter=tutor, reason=ClassAlertReason.CANNOT_REACH,
            note="", now=session.starts_at + timedelta(minutes=10),
        )
        return session

    def _seed_incident_classes(self, pairing, tutor, tutee, class_date):
        pending_session = self._create_past_session(pairing=pairing, tutor=tutor, class_date=class_date, start_time=time(9, 0))
        submit_incident_report(
            session_id=pending_session.pk, reporter=tutee, category="VENUE_ISSUE",
            content="教室冷氣故障，課堂進行到一半必須換教室。",
        )
        resolved_session = self._create_past_session(
            pairing=pairing, tutor=tutor, class_date=class_date - timedelta(days=1), start_time=time(9, 0),
        )
        report = submit_incident_report(
            session_id=resolved_session.pk, reporter=tutor, category="LEARNING_PROGRESS",
            content="學生本週進度落後，建議增加練習時間。",
        )
        admin = User.objects.filter(role=Role.ADMIN).first()
        if admin:
            resolve_incident_report(report_id=report.pk, admin=admin, note="已聯繫雙方確認後續安排。")

    def _seed_upcoming_class(self, pairing, tutor, class_date):
        schedule_classes(tutor=tutor, pairing=pairing, class_date=class_date, start_time=time(14, 0), duration=Decimal("1"))

    # -- matching / releases -----------------------------------------------------

    def _reset_and_submit_release_request(self, pairing, requester):
        PairingReleaseRequest.objects.filter(pairing=pairing).delete()
        submit_pairing_release_request(
            pairing_id=pairing.pk, requester=requester, reason=PairingReleaseReason.SCHEDULE_CONFLICT,
        )

    def _reset_and_send_invitation(self, semester, tutor, tutee):
        MatchingInvitation.objects.filter(semester=semester, tutor=tutor, tutee=tutee).delete()
        send_invitation(initiator=tutor, tutor_id=tutor.pk, tutee_id=tutee.pk)

    # -- messages / hours -----------------------------------------------------

    def _seed_messages(self, pairing, tutor, tutee):
        PairingMessage.objects.filter(pairing=pairing).delete()
        now = timezone.now()
        rows = [
            (tutor, "你好，這學期的上課時間方便嗎？", now - timedelta(days=3), True),
            (tutee, "方便的，謝謝老師！", now - timedelta(days=3) + timedelta(minutes=5), True),
            (tutor, "下次上課前記得先預習一下單字表喔。", now - timedelta(hours=2), False),
        ]
        for sender, body, created_at, is_read in rows:
            message = PairingMessage.objects.create(pairing=pairing, sender=sender, body=body)
            message.created_at = created_at
            message.read_at = created_at if is_read else None
            message.save(update_fields=["created_at", "read_at"])

    def _seed_hour_adjustments(self, semester, tutor1, ntnu, tutor2, maryland):
        admin = User.objects.filter(role=Role.ADMIN).first()
        HourAdjustment.objects.filter(user__in=[tutor1, tutor2], semester=semester).delete()
        HourAdjustment.objects.create(
            user=tutor1, semester=semester, program=ntnu, hours=Decimal("2.5"),
            reason="舊紙本資料補登（系統上線前輔導紀錄）。", created_by=admin,
        )
        HourAdjustment.objects.create(
            user=tutor2, semester=semester, program=maryland, hours=Decimal("1.5"),
            reason="舊紙本資料補登（系統上線前語言交換紀錄）。", created_by=admin,
        )
