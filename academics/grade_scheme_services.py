import uuid
from decimal import Decimal, InvalidOperation

from django.db import transaction
from rest_framework import serializers

from academics.academic_services import get_current_academic_term, require_current_academic_term
from academics.models import (
    ClassSubjectAssignment,
    GradeSchemeTemplate,
    ParentGradesSeenState,
    Student,
    SubjectGrade,
    SubjectGradeScheme,
    SubjectGradeSchemeEntry,
)
from staff.models import TeacherClassAssignment


def teacher_assigned_class_ids(teacher):
    return set(
        TeacherClassAssignment.objects.filter(teacher=teacher).values_list("school_class_id", flat=True)
    )


def _class_subject_assignments_configured():
    return ClassSubjectAssignment.objects.exists()


def _to_decimal(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def normalize_components(raw_components):
    if not isinstance(raw_components, list):
        raise serializers.ValidationError({"components": "صيغة التقسيمة غير صالحة"})

    normalized = []
    for index, item in enumerate(raw_components):
        if not isinstance(item, dict):
            raise serializers.ValidationError({"components": f"عنصر التقسيمة {index + 1} غير صالح"})
        name = str(item.get("name") or "").strip()
        if not name:
            raise serializers.ValidationError({"components": f"أدخل اسم عنصر التقسيمة {index + 1}"})
        max_score = _to_decimal(item.get("maxScore"))
        if max_score is None or max_score <= 0:
            raise serializers.ValidationError({"components": f"علامة «{name}» يجب أن تكون أكبر من صفر"})
        component_id = str(item.get("id") or "").strip() or f"cmp-{uuid.uuid4().hex[:8]}"
        normalized.append({"id": component_id, "name": name, "maxScore": float(max_score)})
    return normalized


def validate_components_total(components, max_score):
    total = sum(Decimal(str(item["maxScore"])) for item in components)
    max_decimal = _to_decimal(max_score)
    if max_decimal is None or max_decimal <= 0:
        raise serializers.ValidationError({"maxScore": "العلامة الكاملة يجب أن تكون أكبر من صفر"})
    if total != max_decimal:
        raise serializers.ValidationError(
            {
                "components": f"مجموع التقسيمة ({total}) يجب أن يساوي العلامة الكاملة ({max_decimal})"
            }
        )
    return max_decimal, components


def teacher_subjects_for_class(teacher, school_class):
    teacher_subject_names = set(teacher.teaching_subjects.values_list("name", flat=True))
    if not teacher_subject_names:
        return []
    if school_class.id not in teacher_assigned_class_ids(teacher):
        return []
    class_subject_names = set(
        ClassSubjectAssignment.objects.filter(school_class=school_class).values_list(
            "subject__name", flat=True
        )
    )
    if class_subject_names:
        return sorted(teacher_subject_names & class_subject_names, key=lambda name: name)
    if not _class_subject_assignments_configured():
        return sorted(teacher_subject_names, key=lambda name: name)
    return []


def teacher_teachable_class_ids(teacher):
    teacher_subject_ids = set(teacher.teaching_subjects.values_list("id", flat=True))
    assigned_ids = teacher_assigned_class_ids(teacher)
    if not teacher_subject_ids or not assigned_ids:
        return []

    teachable = []
    for class_id in assigned_ids:
        if ClassSubjectAssignment.objects.filter(
            school_class_id=class_id,
            subject_id__in=teacher_subject_ids,
        ).exists():
            teachable.append(class_id)

    if teachable:
        return sorted(teachable)

    if not _class_subject_assignments_configured():
        return sorted(assigned_ids)

    return []


def teacher_subject_class_map(teacher):
    subject_id_to_name = {subject.id: subject.name for subject in teacher.teaching_subjects.all()}
    if not subject_id_to_name:
        return {}

    result = {name: [] for name in subject_id_to_name.values()}
    assigned_ids = teacher_assigned_class_ids(teacher)
    for class_id in assigned_ids:
        class_id_str = str(class_id)
        linked = ClassSubjectAssignment.objects.filter(
            school_class_id=class_id,
            subject_id__in=subject_id_to_name.keys(),
        )
        if linked.exists():
            for row in linked.select_related("subject"):
                result[subject_id_to_name[row.subject_id]].append(class_id_str)

    if not _class_subject_assignments_configured():
        for class_id in assigned_ids:
            class_id_str = str(class_id)
            for name in result:
                result[name].append(class_id_str)

    for name in result:
        result[name] = sorted(set(result[name]), key=lambda value: int(value))
    return result


def teacher_subjects_for_classes(teacher, school_classes):
    if not school_classes:
        return []
    subjects = set()
    for school_class in school_classes:
        subjects.update(teacher_subjects_for_class(teacher, school_class))
    return sorted(subjects, key=lambda name: name)


def teacher_teaches_subject(teacher, subject_name):
    subject_name = (subject_name or "").strip()
    if not subject_name:
        return False
    return teacher.teaching_subjects.filter(name=subject_name).exists()


def assert_teacher_can_manage_scheme(teacher, school_class, subject_name):
    if school_class.id not in teacher_teachable_class_ids(teacher):
        raise serializers.ValidationError({"classIds": f"لا تدرّس في فصل {school_class.name}"})
    if subject_name.strip() not in teacher_subjects_for_class(teacher, school_class):
        raise serializers.ValidationError({"subject": "هذه المادة غير مرتبطة بهذا الفصل"})


def ensure_scheme_entries(scheme):
    students = Student.objects.filter(school_class=scheme.school_class, is_active=True)
    for student in students:
        SubjectGradeSchemeEntry.objects.get_or_create(scheme=scheme, student=student, defaults={"scores": {}})

    active_ids = set(students.values_list("id", flat=True))
    SubjectGradeSchemeEntry.objects.filter(scheme=scheme).exclude(student_id__in=active_ids).delete()


def entry_total_score(scores, component_ids):
    if not isinstance(scores, dict):
        return Decimal("0")
    total = Decimal("0")
    for component_id in component_ids:
        raw = scores.get(component_id)
        if raw in (None, ""):
            continue
        parsed = _to_decimal(raw)
        if parsed is not None:
            total += parsed
    return total


def sync_subject_grade(scheme, student, total_score):
    academic_term = scheme.academic_term or require_current_academic_term()
    SubjectGrade.objects.update_or_create(
        student=student,
        subject=scheme.subject,
        academic_term=academic_term,
        defaults={
            "score": total_score,
            "max_score": scheme.max_score,
            "note": "",
            "term": academic_term.name,
        },
    )


def get_grade_scheme_template(term=None):
    if term is None:
        term = require_current_academic_term()
    if not term:
        return None
    return GradeSchemeTemplate.objects.filter(academic_term=term).first()


def sync_subject_grade_schemes_from_template(template):
    SubjectGradeScheme.objects.filter(academic_term=template.academic_term).update(
        max_score=template.max_score,
        components=template.components,
    )


@transaction.atomic
def upsert_grade_scheme_template(max_score, components, term=None):
    term = term or require_current_academic_term()
    max_decimal, normalized_components = validate_components_total(components, max_score)
    template, _ = GradeSchemeTemplate.objects.update_or_create(
        academic_term=term,
        defaults={
            "max_score": max_decimal,
            "components": normalized_components,
        },
    )
    template.max_score = max_decimal
    template.components = normalized_components
    template.save(update_fields=["max_score", "components", "updated_at"])
    sync_subject_grade_schemes_from_template(template)
    return template


def serialize_grade_scheme_template(template):
    if not template:
        return None
    return {
        "id": str(template.id),
        "classId": "",
        "className": "",
        "subject": "",
        "academicTermId": str(template.academic_term_id),
        "maxScore": float(template.max_score),
        "components": template.components or [],
        "updatedAt": template.updated_at.isoformat() if template.updated_at else None,
        "managedByAdmin": True,
    }


def ensure_teacher_scheme_from_template(teacher, school_class, subject_name, template=None):
    template = template or get_grade_scheme_template()
    if not template:
        return None
    subject_name = subject_name.strip()
    if not subject_name:
        return None
    assert_teacher_can_manage_scheme(teacher, school_class, subject_name)
    scheme, created = SubjectGradeScheme.objects.get_or_create(
        teacher=teacher,
        school_class=school_class,
        subject=subject_name,
        academic_term=template.academic_term,
        defaults={
            "max_score": template.max_score,
            "components": template.components,
        },
    )
    if not created and (
        scheme.max_score != template.max_score or scheme.components != template.components
    ):
        scheme.max_score = template.max_score
        scheme.components = template.components
        scheme.save(update_fields=["max_score", "components", "updated_at"])
    ensure_scheme_entries(scheme)
    return scheme


def ensure_teacher_schemes_for_classes(teacher, school_classes, subject_name, template=None):
    template = template or get_grade_scheme_template()
    if not template:
        return []
    schemes = []
    for school_class in school_classes:
        scheme = ensure_teacher_scheme_from_template(teacher, school_class, subject_name, template)
        if scheme:
            schemes.append(scheme)
    return schemes


@transaction.atomic
def upsert_grade_scheme(teacher, school_class, subject_name, max_score, components):
    assert_teacher_can_manage_scheme(teacher, school_class, subject_name)
    max_decimal, normalized_components = validate_components_total(components, max_score)
    academic_term = require_current_academic_term()

    scheme, _ = SubjectGradeScheme.objects.update_or_create(
        teacher=teacher,
        school_class=school_class,
        subject=subject_name.strip(),
        academic_term=academic_term,
        defaults={
            "max_score": max_decimal,
            "components": normalized_components,
        },
    )
    scheme.max_score = max_decimal
    scheme.components = normalized_components
    scheme.save(update_fields=["max_score", "components", "updated_at"])

    ensure_scheme_entries(scheme)
    return scheme


@transaction.atomic
def upsert_grade_schemes(teacher, school_classes, subject_name, max_score, components):
    schemes = []
    for school_class in school_classes:
        schemes.append(upsert_grade_scheme(teacher, school_class, subject_name, max_score, components))
    return schemes


@transaction.atomic
def save_scheme_entries_multi(teacher, school_classes, subject_name, entries_payload):
    academic_term = require_current_academic_term()
    schemes_by_class_id = {}
    template = get_grade_scheme_template(academic_term)
    for school_class in school_classes:
        scheme = None
        if template:
            scheme = ensure_teacher_scheme_from_template(
                teacher, school_class, subject_name, template
            )
        if not scheme:
            scheme = SubjectGradeScheme.objects.filter(
                teacher=teacher,
                school_class=school_class,
                subject=subject_name.strip(),
                academic_term=academic_term,
            ).first()
        if not scheme:
            raise serializers.ValidationError(
                {
                    "detail": "لم تُعرّف تقسيمة العلامات الموحّدة بعد. تواصل مع الإدارة."
                }
            )
        schemes_by_class_id[school_class.id] = scheme

    if not isinstance(entries_payload, list):
        raise serializers.ValidationError({"entries": "صيغة العلامات غير صالحة"})

    student_ids = [
        str(row.get("studentId") or row.get("id") or "")
        for row in entries_payload
        if row.get("studentId") or row.get("id")
    ]
    students_by_id = {
        str(student.id): student
        for student in Student.objects.filter(id__in=student_ids).select_related("school_class")
    }

    entries_by_class_id = {school_class.id: [] for school_class in school_classes}
    for row in entries_payload:
        student_id = str(row.get("studentId") or row.get("id") or "")
        student = students_by_id.get(student_id)
        if not student or student.school_class_id not in entries_by_class_id:
            continue
        entries_by_class_id[student.school_class_id].append(row)

    for school_class in school_classes:
        save_scheme_entries(schemes_by_class_id[school_class.id], entries_by_class_id[school_class.id])

    return list(schemes_by_class_id.values())


def pick_representative_scheme(schemes):
    existing = [scheme for scheme in schemes if scheme]
    if not existing:
        return None
    return existing[0]


def serialize_entries_for_classes(teacher, school_classes, subject_name=""):
    rows = []
    subject_name = (subject_name or "").strip()
    academic_term = require_current_academic_term()
    for school_class in school_classes:
        scheme = None
        if subject_name:
            scheme = SubjectGradeScheme.objects.filter(
                teacher=teacher,
                school_class=school_class,
                subject=subject_name,
                academic_term=academic_term,
            ).first()
            if scheme:
                ensure_scheme_entries(scheme)
        rows.extend(serialize_scheme_entries(scheme, school_class))
    return rows


@transaction.atomic
def upsert_grade_schemes_for_subjects(teacher, school_classes, subject_names, max_score, components):
    schemes = []
    for subject_name in subject_names:
        name = str(subject_name or "").strip()
        if not name:
            continue
        schemes.extend(upsert_grade_schemes(teacher, school_classes, name, max_score, components))
    return schemes


@transaction.atomic
def save_scheme_entries_for_subjects(teacher, school_classes, subject_names, entries_payload):
    schemes = []
    for subject_name in subject_names:
        name = str(subject_name or "").strip()
        if not name:
            continue
        schemes.extend(save_scheme_entries_multi(teacher, school_classes, name, entries_payload))
    return schemes


@transaction.atomic
def save_scheme_entries(scheme, entries_payload):
    component_ids = [item["id"] for item in (scheme.components or [])]
    component_max = {item["id"]: Decimal(str(item["maxScore"])) for item in (scheme.components or [])}

    if not isinstance(entries_payload, list):
        raise serializers.ValidationError({"entries": "صيغة العلامات غير صالحة"})

    students_by_id = {
        str(student.id): student
        for student in Student.objects.filter(school_class=scheme.school_class, is_active=True)
    }

    for row in entries_payload:
        student_id = str(row.get("studentId") or row.get("id") or "")
        student = students_by_id.get(student_id)
        if not student:
            continue
        raw_scores = row.get("scores") or {}
        if not isinstance(raw_scores, dict):
            raise serializers.ValidationError({"entries": "صيغة علامات الطالب غير صالحة"})

        cleaned = {}
        for component_id, raw_value in raw_scores.items():
            if component_id not in component_max:
                continue
            if raw_value in (None, ""):
                cleaned[component_id] = ""
                continue
            parsed = _to_decimal(raw_value)
            if parsed is None:
                raise serializers.ValidationError({"entries": "قيمة علامة غير صالحة"})
            if parsed < 0 or parsed > component_max[component_id]:
                raise serializers.ValidationError(
                    {"entries": f"علامة الطالب {student.name} خارج الحد المسموح"}
                )
            cleaned[component_id] = float(parsed)

        SubjectGradeSchemeEntry.objects.update_or_create(
            scheme=scheme,
            student=student,
            defaults={"scores": cleaned},
        )
        total = entry_total_score(cleaned, component_ids)
        sync_subject_grade(scheme, student, total)

    ensure_scheme_entries(scheme)
    return scheme


def serialize_grade_scheme(scheme):
    return {
        "id": str(scheme.id),
        "classId": str(scheme.school_class_id),
        "className": scheme.school_class.name,
        "subject": scheme.subject,
        "academicTermId": str(scheme.academic_term_id) if scheme.academic_term_id else None,
        "maxScore": float(scheme.max_score),
        "components": scheme.components or [],
        "updatedAt": scheme.updated_at.isoformat() if scheme.updated_at else None,
        "managedByAdmin": True,
    }


def _pass_threshold(max_score):
    return float(max_score) / 2


def _parse_score(raw):
    if raw in (None, ""):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _is_passed(score, max_score):
    if score is None:
        return None
    return float(score) >= _pass_threshold(max_score)


def _serialize_subject_for_parent(scheme, entry, grade):
    components_data = []
    if scheme:
        scores = entry.scores if entry and isinstance(entry.scores, dict) else {}
        for comp in scheme.components or []:
            comp_id = comp.get("id")
            comp_max = float(comp.get("maxScore", 0))
            score_val = _parse_score(scores.get(comp_id))
            components_data.append(
                {
                    "id": comp_id,
                    "name": comp.get("name", ""),
                    "maxScore": comp_max,
                    "score": score_val,
                    "passScore": _pass_threshold(comp_max),
                    "passed": _is_passed(score_val, comp_max),
                }
            )

    if grade:
        total = float(grade.score) if grade.score is not None else None
        max_total = float(grade.max_score)
        grade_id = str(grade.id)
        subject = grade.subject
        note = grade.note or ""
    elif scheme:
        component_ids = [item["id"] for item in (scheme.components or [])]
        scores = entry.scores if entry and isinstance(entry.scores, dict) else {}
        has_scores = any(scores.get(component_id) not in (None, "") for component_id in component_ids)
        total_decimal = entry_total_score(scores, component_ids) if has_scores else None
        total = float(total_decimal) if total_decimal is not None else None
        max_total = float(scheme.max_score)
        grade_id = f"scheme-{scheme.id}"
        subject = scheme.subject
        note = ""
    else:
        return None

    return {
        "id": grade_id,
        "subject": subject,
        "score": total,
        "maxScore": max_total,
        "passScore": _pass_threshold(max_total),
        "passed": _is_passed(total, max_total),
        "note": note,
        "components": components_data,
    }


def serialize_parent_subject_grades(student, academic_term=None):
    academic_term = academic_term or get_current_academic_term()
    if not academic_term:
        return []

    subject_grades = {
        grade.subject: grade
        for grade in SubjectGrade.objects.filter(student=student, academic_term=academic_term)
    }
    if not student.school_class_id:
        return [
            item
            for item in (
                _serialize_subject_for_parent(None, None, grade)
                for grade in SubjectGrade.objects.filter(
                    student=student, academic_term=academic_term
                ).order_by("subject")
            )
            if item
        ]

    schemes = SubjectGradeScheme.objects.filter(
        school_class=student.school_class,
        academic_term=academic_term,
    ).order_by("subject")
    entries_by_scheme_id = {
        entry.scheme_id: entry
        for entry in SubjectGradeSchemeEntry.objects.filter(
            student=student,
            scheme__in=schemes,
        )
    }

    results = []
    seen_subjects = set()
    for scheme in schemes:
        seen_subjects.add(scheme.subject)
        grade = subject_grades.get(scheme.subject)
        entry = entries_by_scheme_id.get(scheme.id)
        item = _serialize_subject_for_parent(scheme, entry, grade)
        if item:
            results.append(item)

    for subject, grade in sorted(subject_grades.items()):
        if subject in seen_subjects:
            continue
        item = _serialize_subject_for_parent(None, None, grade)
        if item:
            results.append(item)

    return results


def serialize_scheme_entries(scheme, school_class):
    component_ids = [item["id"] for item in (scheme.components or [])] if scheme else []

    students = Student.objects.filter(school_class=school_class, is_active=True).order_by("name")
    entries_by_student = {}
    if scheme:
        for entry in scheme.entries.select_related("student"):
            entries_by_student[entry.student_id] = entry

    rows = []
    for student in students:
        entry = entries_by_student.get(student.id)
        scores = entry.scores if entry and isinstance(entry.scores, dict) else {}
        total = entry_total_score(scores, component_ids) if scheme else None
        rows.append(
            {
                "studentId": str(student.id),
                "classId": str(school_class.id),
                "className": school_class.name,
                "name": student.name,
                "studentNumber": student.student_number or "",
                "nationalId": student.national_id or "",
                "scores": scores,
                "total": float(total) if total is not None else "",
            }
        )
    return rows


def _scheme_entry_has_scores(entry):
    if not entry or not isinstance(entry.scores, dict):
        return False
    return any(value not in (None, "") for value in entry.scores.values())


def get_parent_grades_notification(student, parent):
    academic_term = get_current_academic_term()
    if not academic_term:
        return {"hasNew": False, "count": 0}

    state = ParentGradesSeenState.objects.filter(parent=parent, student=student).first()
    last_seen = state.last_seen_at if state else None
    new_subjects: set[str] = set()

    for grade in SubjectGrade.objects.filter(student=student, academic_term=academic_term):
        if grade.score is None:
            continue
        if last_seen is None or grade.updated_at > last_seen:
            new_subjects.add(grade.subject)

    entries = SubjectGradeSchemeEntry.objects.filter(
        student=student,
        scheme__academic_term=academic_term,
    ).select_related("scheme")
    for entry in entries:
        if not _scheme_entry_has_scores(entry):
            continue
        if last_seen is None or entry.updated_at > last_seen:
            new_subjects.add(entry.scheme.subject)

    count = len(new_subjects)
    return {"hasNew": count > 0, "count": count}


def mark_parent_grades_seen(parent, student):
    from django.utils import timezone

    ParentGradesSeenState.objects.update_or_create(
        parent=parent,
        student=student,
        defaults={"last_seen_at": timezone.now()},
    )
