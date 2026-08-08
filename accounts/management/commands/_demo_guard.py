import os

from django.conf import settings
from django.core.management.base import CommandError


def ensure_demo_seed_allowed():
    """Require both `DEBUG=True` and an explicit `ALLOW_DEMO_SEED=1` before any seed/demo
    command may run.

    `DEBUG` alone isn't enough: a production host that's accidentally misconfigured with
    `DJANGO_DEBUG=1` would otherwise still let these commands create a persistent
    `DEMO-ADMIN` superuser or pollute the real roster with self-registerable TEST student
    IDs (see docs/VULNERABILITY_SCAN_IMPROVEMENTS.md batch 1). The extra env var must be
    set deliberately for a single command invocation, not left on by default.
    """
    if not settings.DEBUG or os.environ.get("ALLOW_DEMO_SEED") != "1":
        raise CommandError(
            "This command is disabled unless DEBUG=True and ALLOW_DEMO_SEED=1 are both set. "
            "/ This command requires both DEBUG=True and ALLOW_DEMO_SEED=1 to run."
        )
