from contextlib import contextmanager
import importlib
import os

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

import config.settings as settings_module


@contextmanager
def patched_settings(overrides, remove=()):
    """Reload config/settings.py under a patched os.environ so its top-level fail-closed
    checks actually run against the given scenario, then always reload it back to its
    normal (DEBUG=1) state afterwards — even if the reload under test raised, and even if
    an assertion inside the `with` block fails.

    This only replaces the standalone `config.settings` module object in `sys.modules`.
    It does not touch the already-configured `django.conf.settings` singleton used by the
    rest of the running test process, since Django copies settings values out of the
    module once at startup and never re-reads it — so this can't corrupt other tests.
    """
    snapshot = dict(os.environ)
    try:
        for key in remove:
            os.environ.pop(key, None)
        os.environ.update(overrides)
        importlib.reload(settings_module)
        yield settings_module
    finally:
        os.environ.clear()
        os.environ.update(snapshot)
        importlib.reload(settings_module)


class ProductionSettingsFailClosedTests(SimpleTestCase):
    """DJANGO_DEBUG=0 must refuse to start with dev-grade secrets, blank DB credentials, or
    permissive host settings (docs/VULNERABILITY_SCAN_IMPROVEMENTS.md batch 2)."""

    valid_env = {
        "DJANGO_DEBUG": "0",
        "DJANGO_SECRET_KEY": "a-real-production-secret-key-2026",
        "DJANGO_ALLOWED_HOSTS": "mpts.example.ntnu.edu.tw",
        "POSTGRES_PASSWORD": "a-real-db-password",
    }

    def test_valid_production_env_starts_cleanly(self):
        with patched_settings(self.valid_env) as settings:
            self.assertFalse(settings.DEBUG)
            self.assertTrue(settings.SECURE_SSL_REDIRECT)

    def test_missing_secret_key_is_rejected(self):
        env = {key: value for key, value in self.valid_env.items() if key != "DJANGO_SECRET_KEY"}
        with self.assertRaises(ImproperlyConfigured):
            with patched_settings(env, remove=["DJANGO_SECRET_KEY"]):
                pass

    def test_dev_fallback_secret_key_is_rejected_even_if_set_explicitly(self):
        env = self.valid_env | {"DJANGO_SECRET_KEY": settings_module.DEV_SECRET_KEY_FALLBACK}
        with self.assertRaises(ImproperlyConfigured):
            with patched_settings(env):
                pass

    def test_blank_db_password_is_rejected(self):
        env = self.valid_env | {"POSTGRES_PASSWORD": ""}
        with self.assertRaises(ImproperlyConfigured):
            with patched_settings(env):
                pass

    def test_missing_db_password_is_rejected(self):
        env = {key: value for key, value in self.valid_env.items() if key != "POSTGRES_PASSWORD"}
        with self.assertRaises(ImproperlyConfigured):
            with patched_settings(env, remove=["POSTGRES_PASSWORD"]):
                pass

    def test_empty_allowed_hosts_is_rejected(self):
        env = self.valid_env | {"DJANGO_ALLOWED_HOSTS": ""}
        with self.assertRaises(ImproperlyConfigured):
            with patched_settings(env):
                pass

    def test_wildcard_allowed_hosts_is_rejected(self):
        env = self.valid_env | {"DJANGO_ALLOWED_HOSTS": "*"}
        with self.assertRaises(ImproperlyConfigured):
            with patched_settings(env):
                pass

    def test_localhost_only_allowed_hosts_is_rejected(self):
        env = self.valid_env | {"DJANGO_ALLOWED_HOSTS": "localhost,127.0.0.1"}
        with self.assertRaises(ImproperlyConfigured):
            with patched_settings(env):
                pass

    def test_localhost_mixed_with_a_real_host_is_accepted(self):
        env = self.valid_env | {"DJANGO_ALLOWED_HOSTS": "localhost,mpts.example.ntnu.edu.tw"}
        with patched_settings(env) as settings:
            self.assertFalse(settings.DEBUG)

    def test_debug_mode_skips_all_fail_closed_checks(self):
        env = {"DJANGO_DEBUG": "1"}
        with patched_settings(env, remove=["DJANGO_SECRET_KEY", "POSTGRES_PASSWORD"]) as settings:
            self.assertTrue(settings.DEBUG)

    def test_module_is_restored_to_dev_defaults_after_each_scenario(self):
        with patched_settings(self.valid_env):
            pass
        self.assertTrue(settings_module.DEBUG)


class CsrfTrustedOriginsParsingTests(SimpleTestCase):
    def test_unset_env_var_yields_empty_list(self):
        with patched_settings({}, remove=["DJANGO_CSRF_TRUSTED_ORIGINS"]) as settings:
            self.assertEqual(settings.CSRF_TRUSTED_ORIGINS, [])

    def test_comma_separated_origins_are_parsed_and_stripped(self):
        env = {
            "DJANGO_CSRF_TRUSTED_ORIGINS": "https://mpts.example.ntnu.edu.tw, https://admin.example.ntnu.edu.tw ",
        }
        with patched_settings(env) as settings:
            self.assertEqual(
                settings.CSRF_TRUSTED_ORIGINS,
                ["https://mpts.example.ntnu.edu.tw", "https://admin.example.ntnu.edu.tw"],
            )
