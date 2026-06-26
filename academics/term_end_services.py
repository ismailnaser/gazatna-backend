from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from academics.academic_services import set_current_academic_term
from academics.certificate_services import get_or_create_certificate_config, publish_certificates
from academics.models import AcademicTerm, AcademicYear, CertificateConfig, Student
from academics.academic_services import get_promotion_policy_for_student
from academics.grade_reset_services import reset_grade_inputs_for_term, strip_subject_details_from_preview_row


def ordered_terms(year: AcademicYear):
    return list(year.terms.order_by("sort_order", "id"))


def get_term_for_year(year: AcademicYear, term_id=None) -> AcademicTerm | None:
    if term_id:
        return AcademicTerm.objects.filter(id=term_id, academic_year=year).first()
    return AcademicTerm.objects.filter(academic_year=year, is_current=True).order_by("sort_order").first()


def is_last_term(term: AcademicTerm, year: AcademicYear | None = None) -> bool:
    year = year or term.academic_year
    terms = ordered_terms(year)
    return bool(terms) and terms[-1].id == term.id


def next_open_term(term: AcademicTerm, year: AcademicYear | None = None) -> AcademicTerm | None:
    year = year or term.academic_year
    terms = ordered_terms(year)
    for index, item in enumerate(terms):
        if item.id == term.id and index + 1 < len(terms):
            return terms[index + 1]
    return None


def prior_terms_all_closed(term: AcademicTerm, year: AcademicYear | None = None) -> bool:
    year = year or term.academic_year
    for item in ordered_terms(year):
        if item.id == term.id:
            return True
        if not item.is_closed:
            return False
    return True


def _serialize_term_preview_row(student, term: AcademicTerm, policy=None):
    try:
        policy = policy or get_promotion_policy_for_student(student)
        term_passed, subject_results = _evaluate_student_for_term(student, term, policy)
    except serializers.ValidationError:
        return None

    passed_count = sum(1 for row in subject_results.values() if row["passed"])
    return {
        "studentId": str(student.id),
        "name": student.name,
        "studentNumber": student.student_number or "",
        "currentGrade": student.grade_level,
        "currentSection": student.section or "",
        "yearPassed": term_passed,
        "passedSubjectsCount": passed_count,
        "totalSubjectsCount": len(subject_results),
        "subjects": list(subject_results.values()),
        "suggestedAction": "",
        "finalAction": "pending",
        "proposedGrade": student.grade_level,
        "needsReview": False,
        "overrideAction": None,
    }


def preview_term_end(year: AcademicYear, term_id=None):
    if not year.is_active:
        raise serializers.ValidationError({"detail": "معاينة نهاية الفصل متاحة للسنة النشطة فقط"})

    term = get_term_for_year(year, term_id)
    if not term:
        raise serializers.ValidationError({"detail": "حدد الفصل الدراسي للمعاينة"})

    if term.is_closed:
        raise serializers.ValidationError({"detail": "هذا الفصل مُغلق مسبقاً"})

    if is_last_term(term, year):
        raise serializers.ValidationError(
            {"detail": "الفصل الأخير يُغلق عبر «نهاية السنة» وليس «نهاية الفصل»"}
        )

    if not term.is_current:
        raise serializers.ValidationError({"detail": "يمكن معاينة نهاية الفصل الحالي فقط"})

    if not prior_terms_all_closed(term, year):
        raise serializers.ValidationError({"detail": "يجب إغلاق الفصول السابقة قبل إنهاء هذا الفصل"})

    students = Student.objects.filter(is_active=True).select_related("school_class").order_by(
        "grade_level", "section", "name"
    )

    rows = []
    summary = {"passed": 0, "failed": 0, "promote": 0, "repeat": 0, "graduate": 0, "pending": 0}

    for student in students:
        row = _serialize_term_preview_row(student, term)
        if row is None:
            continue
        rows.append(strip_subject_details_from_preview_row(row))
        if row["yearPassed"]:
            summary["passed"] += 1
        else:
            summary["failed"] += 1

    following = next_open_term(term, year)

    return {
        "scope": "term",
        "academicYearId": str(year.id),
        "academicYearName": year.name,
        "termId": str(term.id),
        "termName": term.name,
        "nextTermId": str(following.id) if following else None,
        "nextTermName": following.name if following else None,
        "gradePolicies": _serialize_grade_policies(),
        "summary": summary,
        "students": rows,
    }


@transaction.atomic
def execute_term_end(year: AcademicYear, user, term_id=None, publish_certs=True):
    if not year.is_active:
        raise serializers.ValidationError({"detail": "يمكن تنفيذ نهاية الفصل للسنة النشطة فقط"})

    term = get_term_for_year(year, term_id)
    if not term:
        raise serializers.ValidationError({"detail": "حدد الفصل الدراسي"})

    preview = preview_term_end(year, term_id=str(term.id))
    following = next_open_term(term, year)
    if not following:
        raise serializers.ValidationError({"detail": "لا يوجد فصل تالٍ للانتقال إليه"})

    if publish_certs:
        config = get_or_create_certificate_config(year)
        if config.issuance_scope != CertificateConfig.SCOPE_TERM:
            config.issuance_scope = CertificateConfig.SCOPE_TERM
            config.save(update_fields=["issuance_scope"])
        publish_certificates(year, user, term_id=str(term.id))

    now = timezone.now()
    term.is_closed = True
    term.is_current = False
    term.closed_at = now
    term.save(update_fields=["is_closed", "is_current", "closed_at"])

    set_current_academic_term(following)
    reset_grade_inputs_for_term(following)

    return {
        "scope": "term",
        "closedTerm": {
            "id": str(term.id),
            "name": term.name,
            "closedAt": term.closed_at.isoformat() if term.closed_at else None,
        },
        "nextTerm": {
            "id": str(following.id),
            "name": following.name,
        },
        "certificatesPublished": bool(publish_certs),
        "academicYear": None,
        "summary": preview["summary"],
        "students": preview["students"],
    }
