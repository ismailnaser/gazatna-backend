from django.db.models import Q

from academics.academic_services import get_current_academic_term, term_display_name
from academics.certificate_services import serialize_parent_certificates
from academics.grade_scheme_services import serialize_parent_subject_grades
from academics.models import (
    AcademicTerm,
    AcademicYear,
    CertificateConfig,
    Enrollment,
    SchoolClass,
    SubjectGrade,
    SubjectGradeScheme,
)
from assignments.models import Homework, Quiz


def _archived_terms_queryset():
    current = get_current_academic_term()
    qs = AcademicTerm.objects.filter(
        Q(is_closed=True) | Q(academic_year__status=AcademicYear.STATUS_ARCHIVED)
    ).select_related("academic_year")
    if current:
        qs = qs.exclude(id=current.id)
    return qs.order_by("-academic_year__start_date", "-sort_order", "-id")


def _student_archive_terms(student):
    term_ids = set(
        SubjectGrade.objects.filter(student=student).values_list("academic_term_id", flat=True)
    )
    term_ids.update(
        Homework.objects.filter(
            school_class_id=student.school_class_id,
            submissions__student=student,
        ).values_list("academic_term_id", flat=True)
    )
    term_ids.update(
        Quiz.objects.filter(
            school_class_id=student.school_class_id,
            submissions__student=student,
        ).values_list("academic_term_id", flat=True)
    )
    term_ids.discard(None)
    if not term_ids:
        return _archived_terms_queryset().none()

    current = get_current_academic_term()
    qs = AcademicTerm.objects.filter(id__in=term_ids).select_related("academic_year")
    if current:
        qs = qs.exclude(id=current.id)
    return qs.filter(
        Q(is_closed=True) | Q(academic_year__status=AcademicYear.STATUS_ARCHIVED)
    ).order_by("-academic_year__start_date", "-sort_order", "-id")


def serialize_parent_archive_overview(student):
    terms = _student_archive_terms(student)
    years_map: dict[str, dict] = {}

    for term in terms:
        year = term.academic_year
        year_key = str(year.id)
        bucket = years_map.setdefault(
            year_key,
            {
                "yearId": year_key,
                "yearName": year.name,
                "isArchived": year.status == AcademicYear.STATUS_ARCHIVED,
                "terms": [],
            },
        )
        grade_count = SubjectGrade.objects.filter(student=student, academic_term=term).count()
        bucket["terms"].append(
            {
                "termId": str(term.id),
                "termName": term_display_name(term),
                "sortOrder": term.sort_order,
                "isClosed": term.is_closed,
                "closedAt": term.closed_at.isoformat() if term.closed_at else None,
                "hasGrades": grade_count > 0,
            }
        )

    enrollment_years = Enrollment.objects.filter(student=student).values_list("academic_year", flat=True)
    for year_name in enrollment_years:
        year = AcademicYear.objects.filter(name=year_name).first()
        if not year:
            continue
        year_key = str(year.id)
        if year_key not in years_map:
            years_map[year_key] = {
                "yearId": year_key,
                "yearName": year.name,
                "isArchived": year.status == AcademicYear.STATUS_ARCHIVED,
                "terms": [],
            }

    return sorted(years_map.values(), key=lambda item: item["yearName"], reverse=True)


def serialize_parent_archive_term_grades(student, term: AcademicTerm):
    if term.is_current and term.academic_year.is_active:
        current = get_current_academic_term()
        if current and current.id == term.id:
            from rest_framework import serializers

            raise serializers.ValidationError({"detail": "العلامات الحالية متاحة من صفحة العلامات"})
    return serialize_parent_subject_grades(student, academic_term=term)


def serialize_parent_archive_certificates(student):
    from academics.certificate_services import serialize_parent_archived_certificates

    return serialize_parent_archived_certificates(student)


def _teacher_archive_terms(teacher):
    term_ids = set(
        SubjectGradeScheme.objects.filter(teacher=teacher).values_list("academic_term_id", flat=True)
    )
    term_ids.update(Homework.objects.filter(teacher=teacher).values_list("academic_term_id", flat=True))
    term_ids.update(Quiz.objects.filter(teacher=teacher).values_list("academic_term_id", flat=True))
    term_ids.discard(None)
    if not term_ids:
        return _archived_terms_queryset().none()

    current = get_current_academic_term()
    qs = AcademicTerm.objects.filter(id__in=term_ids).select_related("academic_year")
    if current:
        qs = qs.exclude(id=current.id)
    return qs.filter(
        Q(is_closed=True) | Q(academic_year__status=AcademicYear.STATUS_ARCHIVED)
    ).order_by("-academic_year__start_date", "-sort_order", "-id")


def serialize_teacher_archive_overview(teacher):
    terms = _teacher_archive_terms(teacher)
    years_map: dict[str, dict] = {}

    for term in terms:
        year = term.academic_year
        year_key = str(year.id)
        bucket = years_map.setdefault(
            year_key,
            {
                "yearId": year_key,
                "yearName": year.name,
                "isArchived": year.status == AcademicYear.STATUS_ARCHIVED,
                "terms": [],
            },
        )
        class_ids = set(
            SubjectGradeScheme.objects.filter(teacher=teacher, academic_term=term).values_list(
                "school_class_id", flat=True
            )
        )
        class_ids.update(
            Homework.objects.filter(teacher=teacher, academic_term=term).values_list("school_class_id", flat=True)
        )
        class_ids.update(
            Quiz.objects.filter(teacher=teacher, academic_term=term).values_list("school_class_id", flat=True)
        )
        bucket["terms"].append(
            {
                "termId": str(term.id),
                "termName": term_display_name(term),
                "sortOrder": term.sort_order,
                "classCount": len(class_ids),
            }
        )

    return sorted(years_map.values(), key=lambda item: item["yearName"], reverse=True)


def serialize_teacher_archive_term_classes(teacher, term: AcademicTerm):
    class_ids = set(
        SubjectGradeScheme.objects.filter(teacher=teacher, academic_term=term).values_list(
            "school_class_id", flat=True
        )
    )
    class_ids.update(
        Homework.objects.filter(teacher=teacher, academic_term=term).values_list("school_class_id", flat=True)
    )
    class_ids.update(
        Quiz.objects.filter(teacher=teacher, academic_term=term).values_list("school_class_id", flat=True)
    )
    classes = SchoolClass.objects.filter(id__in=class_ids).order_by("grade_level", "section", "name")
    return [
        {
            "classId": str(school_class.id),
            "name": school_class.name,
            "gradeLevel": school_class.grade_level,
            "section": school_class.section or "",
        }
        for school_class in classes
    ]


def serialize_teacher_archive_class_grades(teacher, term: AcademicTerm, school_class, subject=None):
    from academics.grade_scheme_services import serialize_scheme_entries

    schemes = SubjectGradeScheme.objects.filter(
        teacher=teacher,
        academic_term=term,
        school_class=school_class,
    ).order_by("subject")
    if subject:
        schemes = schemes.filter(subject=subject)

    if not schemes.exists():
        return {"subjects": [], "students": []}

    subjects = []
    student_rows: dict[str, dict] = {}

    for scheme in schemes:
        subjects.append(scheme.subject)
        rows = serialize_scheme_entries(scheme, school_class)
        max_score = float(scheme.max_score or 0)
        for row in rows:
            student_id = str(row.get("studentId"))
            total = row.get("total")
            score = float(total) if total not in (None, "") else None
            bucket = student_rows.setdefault(
                student_id,
                {
                    "studentId": student_id,
                    "name": row.get("name") or "",
                    "studentNumber": row.get("studentNumber") or "",
                    "subjects": {},
                },
            )
            passed = None
            if score is not None and max_score > 0:
                from academics.grade_scheme_services import _is_passed, _pass_threshold

                passed = _is_passed(score, max_score)
            bucket["subjects"][scheme.subject] = {
                "score": score,
                "maxScore": max_score,
                "passed": passed,
                "components": row.get("scores") or {},
            }

    students = list(student_rows.values())
    students.sort(key=lambda item: item["name"])
    return {"subjects": subjects, "students": students}
