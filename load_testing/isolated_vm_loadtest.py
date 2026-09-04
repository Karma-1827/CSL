#!/usr/bin/env python3
"""Seed and exercise an isolated MPTS database on the production VM.

This script is intentionally not a Django management command: it is copied to a
temporary directory on the VM and run by a transient systemd unit whose
POSTGRES_DB points at a disposable database.  It must never run against the real
``mpts`` database.
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import http.client
import math
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, time as dt_time, timedelta
from decimal import Decimal
from urllib.parse import urlencode


DATABASE_NAME = os.environ.get("POSTGRES_DB", "")
if not DATABASE_NAME.startswith("mpts_loadtest_"):
    raise SystemExit(
        "Refusing to run: POSTGRES_DB must start with 'mpts_loadtest_'."
    )

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
sys.path.insert(0, "/opt/mpts")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.contrib.auth import (  # noqa: E402
    BACKEND_SESSION_KEY,
    HASH_SESSION_KEY,
    SESSION_KEY,
)
from django.contrib.sessions.backends.db import SessionStore  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.db import connections  # noqa: E402
from django.middleware.csrf import (  # noqa: E402
    _get_new_csrf_string,
    _mask_cipher_secret,
)
from django.utils import timezone  # noqa: E402

from accounts.models import (  # noqa: E402
    EducationLevel,
    IdentityCategory,
    PartnerProgram,
    Role,
    RosterEntry,
    User,
)
from tutoring.models import (  # noqa: E402
    Attendance,
    ClassConfirmation,
    ClassRecord,
    ClassSession,
    ConfirmationStatus,
    Pairing,
    Semester,
    TuteeProfile,
    TutorProfile,
)


TUTOR_COUNT = 250
TUTEE_COUNT = 250
CLASSES_PER_PAIR = 16
GUNICORN_WORKERS = min((os.cpu_count() or 1) * 2 + 1, 17)


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1)]


def read_cpu_counters() -> tuple[int, int]:
    fields = [int(value) for value in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
    idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
    return sum(fields), idle


def read_available_memory_mib() -> float:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) / 1024
    return 0.0


class ResourceSampler:
    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self.cpu_peak = 0.0
        self.mem_available_min = read_available_memory_mib()
        self.load1_peak = 0.0
        self.db_connections_peak = 0
        self.thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self) -> "ResourceSampler":
        self.thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.stop_event.set()
        self.thread.join(timeout=2)

    def _run(self) -> None:
        previous_total, previous_idle = read_cpu_counters()
        while not self.stop_event.wait(0.5):
            total, idle = read_cpu_counters()
            delta_total = total - previous_total
            delta_idle = idle - previous_idle
            if delta_total:
                self.cpu_peak = max(self.cpu_peak, 100 * (delta_total - delta_idle) / delta_total)
            previous_total, previous_idle = total, idle
            self.mem_available_min = min(self.mem_available_min, read_available_memory_mib())
            self.load1_peak = max(self.load1_peak, os.getloadavg()[0])
            try:
                import psycopg

                db = settings.DATABASES["default"]
                with psycopg.connect(
                    dbname=db["NAME"], user=db["USER"], password=db["PASSWORD"],
                    host=db["HOST"], port=db["PORT"], connect_timeout=2,
                ) as connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT count(*) FROM pg_stat_activity WHERE datname = %s",
                            (db["NAME"],),
                        )
                        self.db_connections_peak = max(
                            self.db_connections_peak, cursor.fetchone()[0]
                        )
            except Exception:
                pass


def migrate_and_seed() -> dict[str, object]:
    print(f"Migrating isolated database {DATABASE_NAME}...", flush=True)
    call_command("migrate", verbosity=0, interactive=False)

    program = PartnerProgram.objects.get(code="NTNU")
    today = timezone.localdate()
    semester = Semester.objects.create(
        name_zh="隔離壓測學期",
        name_en="Isolated load-test semester",
        starts_on=today - timedelta(days=150),
        ends_on=today - timedelta(days=20),
        is_active=True,
        program=program,
    )

    now = timezone.now()
    tutor_rosters = [
        RosterEntry(
            student_id=f"LOAD-T-{index:04d}", name_zh=f"壓測老師{index:04d}",
            name_en=f"Load Tutor {index:04d}", role=Role.TUTOR,
            education_level=EducationLevel.MASTER,
            identity_category=IdentityCategory.LOCAL, claimed_at=now,
        )
        for index in range(TUTOR_COUNT)
    ]
    tutee_rosters = [
        RosterEntry(
            student_id=f"LOAD-S-{index:04d}", name_zh=f"壓測學生{index:04d}",
            name_en=f"Load Student {index:04d}", role=Role.TUTEE,
            education_level=EducationLevel.NOT_APPLICABLE,
            identity_category=IdentityCategory.INTERNATIONAL, program=program,
            claimed_at=now,
        )
        for index in range(TUTEE_COUNT)
    ]
    RosterEntry.objects.bulk_create(tutor_rosters + tutee_rosters, batch_size=1000)

    admin = User(
        username="LOAD-ADMIN", password="!", role=Role.ADMIN,
        name_zh="壓測管理員", name_en="Load Admin", email="load-admin@example.invalid",
        is_staff=True, is_superuser=True,
    )
    admin.save(force_insert=True)
    tutors = [
        User(
            username=roster.student_id, password="!", role=Role.TUTOR,
            roster_entry=roster, name_zh=roster.name_zh, name_en=roster.name_en,
            email=f"tutor-{index:04d}@example.invalid",
        )
        for index, roster in enumerate(tutor_rosters)
    ]
    tutees = [
        User(
            username=roster.student_id, password="!", role=Role.TUTEE,
            roster_entry=roster, name_zh=roster.name_zh, name_en=roster.name_en,
            email=f"student-{index:04d}@example.invalid",
        )
        for index, roster in enumerate(tutee_rosters)
    ]
    User.objects.bulk_create(tutors + tutees, batch_size=1000)

    TutorProfile.objects.bulk_create(
        [
            TutorProfile(
                tutor=user, gender="MALE", native_language="Mandarin Chinese",
                nationality="Taiwan", level_listening=4, level_speaking=4,
                level_reading=4, level_writing=4, teaching_notes="Synthetic load data",
                available_days=["MON"], available_time_slots=["13:00-15:00"],
            )
            for user in tutors
        ],
        batch_size=1000,
    )
    TuteeProfile.objects.bulk_create(
        [
            TuteeProfile(
                tutee=user, gender="FEMALE", native_language="English",
                nationality="Synthetic", department="Load Testing", overall_level="B1",
                learning_duration="1_TO_2_YEARS", target_skills=["SPEAKING"],
                skills_to_improve="Synthetic load data", preferred_days=["MON"],
                preferred_time_slots=["13:00-15:00"],
            )
            for user in tutees
        ],
        batch_size=1000,
    )

    pairings = [
        Pairing(semester=semester, tutor=tutors[index], tutee=tutees[index])
        for index in range(TUTEE_COUNT)
    ]
    Pairing.objects.bulk_create(pairings, batch_size=1000)

    first_monday = semester.starts_on + timedelta(days=(-semester.starts_on.weekday()) % 7)
    sessions: list[ClassSession] = []
    for pairing in pairings:
        for week in range(CLASSES_PER_PAIR):
            sessions.append(
                ClassSession(
                    pairing=pairing,
                    class_date=first_monday + timedelta(weeks=week),
                    start_time=dt_time(13, 0), duration=Decimal("1.0"),
                    created_by=pairing.tutor,
                )
            )
    ClassSession.objects.bulk_create(sessions, batch_size=1000)

    attendances: list[Attendance] = []
    records: list[ClassRecord] = []
    confirmations: list[ClassConfirmation] = []
    for session in sessions:
        tutor = session.pairing.tutor
        tutee = session.pairing.tutee
        signed_at = timezone.make_aware(
            datetime.combine(session.class_date, session.start_time),
            timezone.get_current_timezone(),
        )
        for participant in (tutor, tutee):
            attendances.append(
                Attendance(session=session, participant=participant, signed_at=signed_at)
            )
            records.append(
                ClassRecord(
                    session=session, author=participant, location="Synthetic classroom",
                    topic="Synthetic lesson", content="Synthetic class content",
                    reflection="", materials_used="Synthetic materials",
                    individual_progress="Synthetic progress notes", remarks="",
                    evidence_links=["https://example.invalid/evidence"],
                )
            )
        confirmations.extend(
            [
                ClassConfirmation(
                    session=session, reviewer=tutor, subject=tutee,
                    attendance_confirmed=True, record_confirmed=True,
                    status=ConfirmationStatus.CONFIRMED,
                ),
                ClassConfirmation(
                    session=session, reviewer=tutee, subject=tutor,
                    attendance_confirmed=True, record_confirmed=True,
                    status=ConfirmationStatus.CONFIRMED,
                ),
            ]
        )
    Attendance.objects.bulk_create(attendances, batch_size=2000)
    ClassRecord.objects.bulk_create(records, batch_size=2000)
    ClassConfirmation.objects.bulk_create(confirmations, batch_size=2000)

    print(
        f"Seeded users={User.objects.count()} pairings={Pairing.objects.count()} "
        f"classes={ClassSession.objects.count()} records={ClassRecord.objects.count()}",
        flush=True,
    )
    return {
        "program": program,
        "semester": semester,
        "admin": admin,
        "tutors": tutors,
        "tutees": tutees,
        "sessions": sessions,
    }


def create_login_session(user: User) -> str:
    store = SessionStore()
    store[SESSION_KEY] = str(user.pk)
    store[BACKEND_SESSION_KEY] = "django.contrib.auth.backends.ModelBackend"
    store[HASH_SESSION_KEY] = user.get_session_auth_hash()
    store.save()
    return store.session_key


def request_once(
    *, port: int, method: str, path: str, session_key: str,
    body: str | None = None, csrf_secret: str | None = None,
) -> tuple[int, float, int]:
    headers = {
        "Host": "mpts.tcsl.ntnu.edu.tw",
        "X-Forwarded-Proto": "https",
        "User-Agent": "MPTS-Isolated-Load-Test/1.0",
        "Cookie": f"sessionid={session_key}",
        "Connection": "close",
    }
    if body is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        headers["Content-Length"] = str(len(body.encode()))
        headers["Origin"] = "https://mpts.tcsl.ntnu.edu.tw"
        headers["Referer"] = "https://mpts.tcsl.ntnu.edu.tw/dashboard/"
    if csrf_secret:
        headers["Cookie"] += f"; csrftoken={csrf_secret}"
    started = time.perf_counter()
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        content = response.read()
        return response.status, time.perf_counter() - started, len(content)
    except Exception:
        return 0, time.perf_counter() - started, 0
    finally:
        connection.close()


def run_scenario(
    name: str, *, port: int, concurrency: int, requests: int,
    request_specs: list[dict[str, object]],
) -> dict[str, object]:
    started = time.perf_counter()
    with ResourceSampler() as resources:
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [
                executor.submit(
                    request_once, port=port,
                    **request_specs[index % len(request_specs)],
                )
                for index in range(requests)
            ]
            results = [future.result() for future in concurrent.futures.as_completed(futures)]
    elapsed = time.perf_counter() - started
    statuses: dict[int, int] = {}
    latencies: list[float] = []
    total_bytes = 0
    for status, latency, size in results:
        statuses[status] = statuses.get(status, 0) + 1
        latencies.append(latency)
        total_bytes += size
    errors = sum(count for status, count in statuses.items() if status < 200 or status >= 400)
    result = {
        "name": name, "concurrency": concurrency, "requests": requests,
        "errors": errors, "statuses": statuses, "rps": requests / elapsed,
        "mean_ms": 1000 * sum(latencies) / len(latencies),
        "p95_ms": 1000 * percentile(latencies, 0.95),
        "max_ms": 1000 * max(latencies), "bytes": total_bytes,
        "cpu_peak": resources.cpu_peak,
        "mem_available_min_mib": resources.mem_available_min,
        "load1_peak": resources.load1_peak,
        "db_connections_peak": resources.db_connections_peak,
    }
    print(
        "RESULT " + " ".join(
            [
                f"name={name}", f"c={concurrency}", f"n={requests}",
                f"errors={errors}", f"statuses={statuses}",
                f"rps={result['rps']:.2f}", f"mean_ms={result['mean_ms']:.1f}",
                f"p95_ms={result['p95_ms']:.1f}", f"max_ms={result['max_ms']:.1f}",
                f"cpu_peak={result['cpu_peak']:.1f}%",
                f"mem_avail_min={result['mem_available_min_mib']:.0f}MiB",
                f"load1_peak={result['load1_peak']:.2f}",
                f"db_conn_peak={result['db_connections_peak']}",
                f"bytes={total_bytes}",
            ]
        ),
        flush=True,
    )
    return result


def pick_port() -> int:
    with socket.socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        return candidate.getsockname()[1]


def wait_for_server(port: int, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Gunicorn exited early with status {process.returncode}")
        status, _, _ = request_once(
            port=port, method="GET", path="/", session_key="health-check"
        )
        if status == 200:
            return
        time.sleep(0.2)
    raise RuntimeError("Gunicorn did not become healthy within 30 seconds")


def main() -> int:
    fixtures = migrate_and_seed()
    admin: User = fixtures["admin"]
    tutors: list[User] = fixtures["tutors"]
    tutees: list[User] = fixtures["tutees"]
    sessions: list[ClassSession] = fixtures["sessions"]
    semester: Semester = fixtures["semester"]
    program: PartnerProgram = fixtures["program"]

    loadtest_mode = os.environ.get("MPTS_LOADTEST_MODE", "full")
    participant_users = [value for pair in zip(tutors, tutees) for value in pair]
    participant_session_count = 300 if loadtest_mode == "300-only" else 100
    participant_sessions = [
        create_login_session(user)
        for user in participant_users[:participant_session_count]
    ]
    admin_sessions = [create_login_session(admin) for _ in range(5)]
    certificate_sessions = [create_login_session(user) for user in tutors[:10]]
    connections.close_all()

    port = pick_port()
    command = [
        "/opt/mpts/.venv/bin/gunicorn", "--workers", str(GUNICORN_WORKERS),
        "--worker-class", "sync", "--timeout", "60",
        "--access-logfile", "/dev/null", "--error-logfile", "-",
        "--log-level", "warning", "--bind", f"127.0.0.1:{port}",
        "config.wsgi:application",
    ]
    print(f"Starting isolated Gunicorn: workers={GUNICORN_WORKERS} port={port}", flush=True)
    process = subprocess.Popen(command, cwd="/opt/mpts")
    results: list[dict[str, object]] = []
    try:
        wait_for_server(port, process)
        post_only = loadtest_mode == "post-only"
        three_hundred_only = loadtest_mode == "300-only"
        if not post_only:
            dashboard_stages = (
                ((300, 3000),)
                if three_hundred_only
                else ((20, 1000), (50, 2500), (100, 5000))
            )
            for concurrency, requests in dashboard_stages:
                specs = [
                    {"method": "GET", "path": "/dashboard/", "session_key": key}
                    for key in participant_sessions[:concurrency]
                ]
                result = run_scenario(
                    "participant_dashboard", port=port, concurrency=concurrency,
                    requests=requests, request_specs=specs,
                )
                results.append(result)
                if result["errors"]:
                    break

            if not three_hundred_only:
                admin_specs = [
                    {"method": "GET", "path": "/dashboard/", "session_key": key}
                    for key in admin_sessions
                ]
                results.append(
                    run_scenario(
                        "admin_dashboard", port=port, concurrency=1, requests=3,
                        request_specs=admin_specs,
                    )
                )
                results.append(
                    run_scenario(
                        "admin_dashboard", port=port, concurrency=5, requests=10,
                        request_specs=admin_specs,
                    )
                )

            detail_specs = []
            sessions_by_tutor = {session.pairing.tutor_id: session for session in sessions}
            for user, key in zip(participant_users[:100], participant_sessions):
                if user.role == Role.TUTOR:
                    session = sessions_by_tutor[user.pk]
                else:
                    session = next(row for row in sessions if row.pairing.tutee_id == user.pk)
                detail_specs.append(
                    {
                        "method": "GET", "path": f"/matching/classes/{session.pk}/",
                        "session_key": key,
                    }
                )
            detail_stages = (
                ((300, 3000),)
                if three_hundred_only
                else ((20, 500), (50, 1000), (100, 2000))
            )
            for concurrency, requests in detail_stages:
                result = run_scenario(
                    "class_detail", port=port, concurrency=concurrency,
                    requests=requests, request_specs=detail_specs[:concurrency],
                )
                results.append(result)
                if result["errors"]:
                    break

        certificate_specs = []
        for key in certificate_sessions[:5]:
            secret = _get_new_csrf_string()
            token = _mask_cipher_secret(secret)
            body = urlencode(
                [
                    ("csrfmiddlewaretoken", token), ("mode", "semester"),
                    ("semester", str(semester.pk)), ("program", str(program.pk)),
                    ("language", "zh"), ("version", "detailed"),
                    ("detail_fields", "date"), ("detail_fields", "nationality"),
                    ("detail_fields", "level"), ("detail_fields", "hours"),
                    ("intent", "preview"),
                ]
            )
            certificate_specs.append(
                {
                    "method": "POST", "path": "/matching/hours/download/",
                    "session_key": key, "body": body, "csrf_secret": secret,
                }
            )
        for concurrency, requests in ((1, 2), (3, 6), (5, 10)):
            result = run_scenario(
                "detailed_certificate_pdf", port=port, concurrency=concurrency,
                requests=requests, request_specs=certificate_specs[:concurrency],
            )
            results.append(result)
            if result["errors"]:
                break

        for file_format in ("csv", "xlsx", "pdf"):
            secret = _get_new_csrf_string()
            token = _mask_cipher_secret(secret)
            body = urlencode(
                [
                    ("csrfmiddlewaretoken", token), ("program_id", str(program.pk)),
                    ("audience", "tutors"), ("period_mode", "semester"),
                    ("semester_id", str(semester.pk)), ("file_format", file_format),
                ]
            )
            results.append(
                run_scenario(
                    f"admin_export_{file_format}", port=port, concurrency=1, requests=1,
                    request_specs=[
                        {
                            "method": "POST", "path": "/matching/admin/export-excel/",
                            "session_key": admin_sessions[0], "body": body,
                            "csrf_secret": secret,
                        }
                    ],
                )
            )
    finally:
        process.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=15)
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)

    if any(result["errors"] for result in results):
        print("LOAD_TEST_STATUS=FAILED", flush=True)
        return 1
    print("LOAD_TEST_STATUS=PASSED", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
