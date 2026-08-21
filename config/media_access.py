"""Media access control and signed URLs for protected uploads."""

from __future__ import annotations

import hashlib
import hmac
import time
from pathlib import Path
from urllib.parse import urlencode, urlparse

from django.conf import settings

from accounts.roles import SUPER_ADMIN_ROLE, is_admin_role, role_has_scope

# Public assets — no signature required (homepage hero, news, faculty photos).
PUBLIC_MEDIA_PREFIXES = (
    "site/",
    "news/",
    "teachers/",
)

SIGN_TTL_SECONDS = 60 * 60 * 12


def normalize_media_path(path: str) -> str:
    cleaned = (path or "").replace("\\", "/")
    while ".." in cleaned:
        cleaned = cleaned.replace("..", "")
    return cleaned.lstrip("/")


def is_public_media_path(path: str) -> bool:
    cleaned = normalize_media_path(path)
    return any(cleaned.startswith(prefix) for prefix in PUBLIC_MEDIA_PREFIXES)


def media_path_from_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    raw = parsed.path or url
    prefix = settings.MEDIA_URL.lstrip("/")
    if raw.startswith("/"):
        raw = raw[1:]
    if prefix and raw.startswith(prefix):
        raw = raw[len(prefix) :]
    if raw.startswith("media/"):
        raw = raw[len("media/") :]
    return normalize_media_path(raw)


def sign_media_path(path: str, exp: int | None = None) -> tuple[str, int]:
    cleaned = normalize_media_path(path)
    expires = exp if exp is not None else int(time.time()) + SIGN_TTL_SECONDS
    payload = f"{cleaned}:{expires}"
    signature = hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return signature, expires


def verify_media_signature(path: str, signature: str | None, exp: str | None) -> bool:
    if not signature or not exp:
        return False
    try:
        expires = int(exp)
    except (TypeError, ValueError):
        return False
    if expires < int(time.time()):
        return False
    expected, _ = sign_media_path(normalize_media_path(path), expires)
    return hmac.compare_digest(expected, signature)


def append_media_signature(relative_url: str) -> str:
    path = media_path_from_url(relative_url)
    if not path or is_public_media_path(path):
        return relative_url
    signature, expires = sign_media_path(path)
    query = urlencode({"sig": signature, "exp": expires})
    joiner = "&" if "?" in relative_url else "?"
    return f"{relative_url}{joiner}{query}"


def build_media_url(request, file_field) -> str | None:
    if not file_field:
        return None
    relative = file_field.url
    absolute = request.build_absolute_uri(relative) if request else relative
    path = media_path_from_url(relative)
    if is_public_media_path(path):
        return absolute
    return append_media_signature(absolute)


def resolve_media_file(path: str) -> Path | None:
    cleaned = normalize_media_path(path)
    if not cleaned:
        return None
    root = Path(settings.MEDIA_ROOT).resolve()
    candidate = (root / cleaned).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


def _lookup_by_file(model, field: str, cleaned: str):
    obj = model.objects.filter(**{field: cleaned}).first()
    if obj:
        return obj
    alt = cleaned.replace("/", "\\")
    if alt != cleaned:
        return model.objects.filter(**{field: alt}).first()
    return None


def _parent_owns_student_document(user, cleaned: str) -> bool:
    from academics.models import StudentDocument

    doc = _lookup_by_file(StudentDocument, "file", cleaned)
    if not doc:
        return False
    return doc.student.parent_id == getattr(user, "id", None)


def _parent_owns_payment_file(user, cleaned: str) -> bool:
    from finance.models import PaymentNotice

    notice = _lookup_by_file(PaymentNotice, "receipt", cleaned)
    if not notice:
        return False
    return notice.student.parent_id == getattr(user, "id", None)


def _can_access_homework_attachment(user, cleaned: str) -> bool:
    from assignments.models import Homework, HomeworkAttachment

    att = _lookup_by_file(HomeworkAttachment, "file", cleaned)
    homework = att.homework if att else _lookup_by_file(Homework, "attachment", cleaned)
    if not homework:
        return False
    return _can_access_class_file(user, homework.school_class_id, homework.teacher_id)


def _can_access_homework_submission(user, cleaned: str) -> bool:
    from assignments.models import HomeworkSubmission

    sub = _lookup_by_file(HomeworkSubmission, "attachment", cleaned)
    if not sub:
        return False
    role = getattr(user, "role", "")
    if role == "parent":
        return sub.student.parent_id == getattr(user, "id", None)
    if role == "teacher":
        return _teacher_owns_profile(user, sub.homework.teacher_id)
    return False


def _can_access_quiz_attachment(user, cleaned: str) -> bool:
    from assignments.models import QuizAnswerAttachment

    att = _lookup_by_file(QuizAnswerAttachment, "file", cleaned)
    if not att:
        return False
    role = getattr(user, "role", "")
    if role == "parent":
        return att.submission.student.parent_id == getattr(user, "id", None)
    if role == "teacher":
        return _teacher_owns_profile(user, att.submission.quiz.teacher_id)
    return False


def _can_access_subject_material(user, cleaned: str) -> bool:
    from assignments.models import SubjectMaterialFile

    material_file = _lookup_by_file(SubjectMaterialFile, "file", cleaned)
    if not material_file:
        return False
    material = material_file.material
    return _can_access_class_file(user, material.school_class_id, material.teacher_id)


def _teacher_owns_profile(user, teacher_profile_id: int) -> bool:
    from staff.models import TeacherProfile

    return TeacherProfile.objects.filter(id=teacher_profile_id, user_id=user.id).exists()


def _can_access_class_file(user, school_class_id: int, teacher_profile_id: int) -> bool:
    role = getattr(user, "role", "")
    if role == "teacher":
        return _teacher_owns_profile(user, teacher_profile_id)
    if role == "parent":
        from academics.models import Student

        return Student.objects.filter(parent=user, school_class_id=school_class_id).exists()
    return False


def user_can_access_media(user, path: str) -> bool:
    cleaned = normalize_media_path(path)
    if is_public_media_path(cleaned):
        return True
    if not user or not getattr(user, "is_authenticated", False):
        return False

    role = getattr(user, "role", "")
    if role == SUPER_ADMIN_ROLE:
        return True

    if cleaned.startswith("payments/"):
        if role_has_scope(role, "finance"):
            return True
        return _parent_owns_payment_file(user, cleaned)

    if cleaned.startswith("students/documents/"):
        if role_has_scope(role, "students"):
            return True
        return _parent_owns_student_document(user, cleaned)

    if cleaned.startswith("homework/attachments/"):
        if role_has_scope(role, "staff") or role_has_scope(role, "academics"):
            return True
        return _can_access_homework_attachment(user, cleaned)

    if cleaned.startswith("homework/submissions/"):
        if role_has_scope(role, "staff") or role_has_scope(role, "academics"):
            return True
        return _can_access_homework_submission(user, cleaned)

    if cleaned.startswith("quiz/answer_attachments/"):
        if role_has_scope(role, "staff") or role_has_scope(role, "academics"):
            return True
        return _can_access_quiz_attachment(user, cleaned)

    if cleaned.startswith("subject_materials/"):
        if role_has_scope(role, "staff") or role_has_scope(role, "academics"):
            return True
        return _can_access_subject_material(user, cleaned)

    return is_admin_role(role)
