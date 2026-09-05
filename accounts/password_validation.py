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
