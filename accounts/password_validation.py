"""Bilingual wrappers around Django's built-in password validators.

Django's validators raise English (auto-translated) messages that don't follow this
project's "中文為主、英文副標" convention and give the user no actionable rule text
(封測老師端回饋 P1-02, 2026-09). Each wrapper simply calls the real Django validator —
so the actual pass/fail logic is untouched — and re-raises with a bilingual message on
failure.
"""

from django.contrib.auth.password_validation import (
    CommonPasswordValidator,
    MinimumLengthValidator,
    NumericPasswordValidator,
    UserAttributeSimilarityValidator,
)
from django.core.exceptions import ValidationError


class BilingualMinimumLengthValidator(MinimumLengthValidator):
    def validate(self, password, user=None):
        try:
            super().validate(password, user)
        except ValidationError:
            raise ValidationError(
                f"密碼至少需要 {self.min_length} 個字元。 / "
                f"Your password must be at least {self.min_length} characters long.",
                code="password_too_short",
            )


class BilingualUserAttributeSimilarityValidator(UserAttributeSimilarityValidator):
    def validate(self, password, user=None):
        try:
            super().validate(password, user)
        except ValidationError:
            raise ValidationError(
                "密碼與您的學號、姓名或 Email 太相似，請換一個不同的密碼。 / "
                "Your password is too similar to your student ID, name, or email. "
                "Please choose a different password.",
                code="password_too_similar",
            )


class BilingualCommonPasswordValidator(CommonPasswordValidator):
    def validate(self, password, user=None):
        try:
            super().validate(password, user)
        except ValidationError:
            raise ValidationError(
                "這個密碼太常見，容易被猜到，請換一個較不常見的密碼。 / "
                "This password is too common and easy to guess. Please choose a less common password.",
                code="password_too_common",
            )


class BilingualNumericPasswordValidator(NumericPasswordValidator):
    def validate(self, password, user=None):
        try:
            super().validate(password, user)
        except ValidationError:
            raise ValidationError(
                "密碼不能只有數字，請混合英文字母或符號。 / "
                "Your password cannot be entirely numeric. Please include letters or symbols.",
                code="password_entirely_numeric",
            )


class BilingualPasswordComplexityValidator:
    """Requires at least one uppercase letter, one lowercase letter, one digit, and one
    special/symbol character. None of Django's built-in validators check character-class
    mixing — an all-lowercase password like "abcdefghijk" passed every existing validator
    (length, similarity, common-password, not-all-numeric) — found while testing the Admin
    profile edit form's own password-change field (2026-09-09)."""

    def validate(self, password, user=None):
        if (
            any(char.isupper() for char in password)
            and any(char.islower() for char in password)
            and any(char.isdigit() for char in password)
            and any(not char.isalnum() for char in password)
        ):
            return
        raise ValidationError(
            "密碼需混合大寫字母、小寫字母、數字與特殊符號。 / "
            "Your password must mix uppercase letters, lowercase letters, digits, and special symbols.",
            code="password_missing_complexity",
        )

    def get_help_text(self):
        return (
            "密碼需混合大寫字母、小寫字母、數字與特殊符號。 / "
            "Your password must mix uppercase letters, lowercase letters, digits, and special symbols."
        )
