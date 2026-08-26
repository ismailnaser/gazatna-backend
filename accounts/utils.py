import secrets
import string

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import IntegerField, Max
from django.db.models.functions import Cast

User = get_user_model()

_PASSWORD_ALPHABET = string.ascii_letters + string.digits


def generate_secure_password(length: int = 14) -> str:
    """Generate a strong random password (letters + digits)."""
    length = max(12, int(length or 14))
    for _ in range(20):
        password = "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(length))
        if not any(c.isdigit() for c in password):
            continue
        if not any(c.isalpha() for c in password):
            continue
        try:
            validate_password(password)
            return password
        except ValidationError:
            continue
    return secrets.token_urlsafe(18)


def generate_five_digit_password() -> str:
    """Deprecated alias — returns a secure password."""
    return generate_secure_password()


def next_numeric_username() -> str:
    """Allocate next numeric username without loading all usernames into memory."""
    max_existing = (
        User.objects.filter(username__regex=r"^\d+$")
        .annotate(num=Cast("username", IntegerField()))
        .aggregate(m=Max("num"))
        .get("m")
    )
    candidate = int(max_existing or 100000) + 1
    while User.objects.filter(username=str(candidate)).exists():
        candidate += 1
    return str(candidate)


def create_auto_user(*, name: str, role: str, username: str | None = None) -> tuple:
    password = generate_secure_password()
    last_error = None
    for _ in range(5):
        try:
            with transaction.atomic():
                uname = username or next_numeric_username()
                user = User.objects.create_user(
                    username=uname,
                    email=f"{uname}@school.local",
                    first_name=name,
                    role=role,
                    password=password,
                )
                return user, password
        except IntegrityError as exc:
            last_error = exc
            username = None
            continue
    raise last_error or IntegrityError("تعذر إنشاء حساب مستخدم")
