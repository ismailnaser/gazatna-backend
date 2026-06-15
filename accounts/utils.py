import secrets

from django.contrib.auth import get_user_model

User = get_user_model()


def generate_five_digit_password() -> str:
    return f"{secrets.randbelow(100000):05d}"


def next_numeric_username() -> str:
    numeric_usernames = User.objects.filter(username__regex=r"^\d+$").values_list(
        "username", flat=True
    )
    numbers = [int(u) for u in numeric_usernames if u.isdigit()]
    candidate = max(numbers) + 1 if numbers else 100001
    while User.objects.filter(username=str(candidate)).exists():
        candidate += 1
    return str(candidate)


def create_auto_user(*, name: str, role: str, username: str | None = None) -> tuple:
    username = username or next_numeric_username()
    password = generate_five_digit_password()
    user = User.objects.create_user(
        username=username,
        email=f"{username}@school.local",
        first_name=name,
        role=role,
        password=password,
    )
    return user, password
