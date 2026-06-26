from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from academics.academic_services import (
    _create_default_terms,
    _default_year_name,
    get_promotion_policy_for_student,
    serialize_academic_year,
    set_active_academic_year,
    set_current_academic_term,
)
from academics.models import (
    AcademicTerm,
    AcademicYear,
    CertificateConfig,
    Enrollment,
    Grade,
    PromotionPolicy,
    Student,
    SubjectGrade,
    YearEndPromotionRun,
)
from academics.grade_reset_services import reset_grade_inputs_for_term, strip_subject_details_from_preview_row
from academics.services import ensure_all_grade_sections, get_next_grade, promote_student_to_next_grade


def _pass_threshold(max_score, ratio) -> float:
    return float(max_score) * float(ratio)


def _subject_passed(score, max_score, ratio) -> bool:
    if score is None or max_score is None or float(max_score) <= 0:
        return False
    return float(score) >= _pass_threshold(max_score, ratio)


def _grades_by_subject(student, terms):
    grouped = defaultdict(list)
    for grade in SubjectGrade.objects.filter(student=student, academic_term__in=terms):
        grouped[grade.subject].append(grade)
    return grouped


def _build_subject_results(grouped, method, ratio):
    results = {}
    for subject, grades in grouped.items():
        if method == PromotionPolicy.CALC_YEAR_TOTAL:
            score = sum(float(item.score) for item in grades)
            max_score = sum(float(item.max_score) for item in grades)
        else:
            score = sum(float(item.score) for item in grades) / len(grades)
            max_score = sum(float(item.max_score) for item in grades) / len(grades)
        passed = _subject_passed(score, max_score, ratio)
        results[subject] = {
            "subject": subject,
            "score": round(score, 2),
            "maxScore": round(max_score, 2),
            "passScore": round(_pass_threshold(max_score, ratio), 2),
            "passed": passed,
        }
    return results


def _meets_pass_rule(subject_results: dict, policy: PromotionPolicy) -> bool:
    if not subject_results:
        return False

    required = [str(name).strip() for name in (policy.required_subjects or []) if str(name).strip()]
    for subject_name in required:
        row = subject_results.get(subject_name)
        if not row or not row["passed"]:
            return False

    passed_count = sum(1 for row in subject_results.values() if row["passed"])
    if policy.pass_rule == PromotionPolicy.PASS_ALL_SUBJECTS:
        return passed_count == len(subject_results)
    return passed_count >= int(policy.pass_minimum_count or 1)


def _evaluate_student_for_term(student, term: AcademicTerm, policy: PromotionPolicy):
    ratio = float(policy.pass_score_ratio or Decimal("0.5"))
    grouped = _grades_by_subject(student, [term])
    subject_results = _build_subject_results(grouped, PromotionPolicy.CALC_TERM_AVERAGE, ratio)
    return _meets_pass_rule(subject_results, policy), subject_results


def _evaluate_student_year_pass(student, year: AcademicYear):
    terms = list(year.terms.order_by("sort_order", "id"))
    if not terms:
        return False, {}, None

    policy = get_promotion_policy_for_student(student)
    for term in terms:
        term_passed, term_results = _evaluate_student_for_term(student, term, policy)
        if not term_passed:
            return False, term_results, policy

    grouped = _grades_by_subject(student, terms)
    ratio = float(policy.pass_score_ratio or Decimal("0.5"))
    display_results = _build_subject_results(grouped, PromotionPolicy.CALC_TERM_AVERAGE, ratio)
    return True, display_results, policy


def _suggested_action(student, year_passed: bool, policy: PromotionPolicy):
    next_grade = get_next_grade(student.grade_level)
    if year_passed:
        if not next_grade:
            return "graduate"
        if policy.pass_promotion_mode == PromotionPolicy.MODE_AUTOMATIC:
            return "promote"
        return "review_promote"
    if policy.fail_handling_mode == PromotionPolicy.FAIL_REPEAT_AUTO:
        return "repeat"
    return "review_repeat"


def _resolve_final_action(suggested: str, override: str | None):
    if override in {"promote", "repeat", "graduate"}:
        return override, False

    if suggested == "promote":
        return "promote", False
    if suggested == "repeat":
        return "repeat", False
    if suggested == "graduate":
        return "graduate", False
    return "pending", True


def _proposed_grade_for_action(student, action: str):
    next_grade = get_next_grade(student.grade_level)
    if action == "promote" and next_grade:
        return next_grade.name
    return student.grade_level


def _serialize_preview_row(student, year: AcademicYear, override=None):
    try:
        year_passed, subject_results, policy = _evaluate_student_year_pass(student, year)
    except serializers.ValidationError:
        return None

    suggested = _suggested_action(student, year_passed, policy)
    final_action, needs_review = _resolve_final_action(suggested, override)
    passed_count = sum(1 for row in subject_results.values() if row["passed"])

    return {
        "studentId": str(student.id),
        "name": student.name,
        "studentNumber": student.student_number or "",
        "currentGrade": student.grade_level,
        "currentSection": student.section or "",
        "yearPassed": year_passed,
        "passedSubjectsCount": passed_count,
        "totalSubjectsCount": len(subject_results),
        "subjects": list(subject_results.values()),
        "suggestedAction": suggested,
        "finalAction": final_action,
        "proposedGrade": _proposed_grade_for_action(
            student,
            "graduate" if suggested == "graduate" else ("promote" if final_action == "promote" else "repeat"),
        ),
        "needsReview": needs_review,
        "overrideAction": override,
    }


def _serialize_grade_policies():
    from academics.academic_services import get_promotion_policy_for_grade

    rows = []
    for grade in Grade.objects.order_by("sort_order", "id"):
        policy = get_promotion_policy_for_grade(grade)
        rows.append(
            {
                "gradeId": str(grade.id),
                "gradeName": grade.name,
                "passRule": policy.pass_rule,
                "passMinimumCount": policy.pass_minimum_count,
                "requiredSubjects": policy.required_subjects or [],
            }
        )
    return rows


def preview_year_end(year: AcademicYear, overrides=None):
    from academics.term_end_services import get_term_for_year, is_last_term, ordered_terms, prior_terms_all_closed

    if not year.is_active:
        raise serializers.ValidationError({"detail": "المعاينة متاحة للسنة النشطة فقط"})

    current_term = get_term_for_year(year)
    if not current_term:
        raise serializers.ValidationError({"detail": "لا يوجد فصل دراسي حالي"})

    if not is_last_term(current_term, year):
        raise serializers.ValidationError(
            {"detail": "معاينة نهاية السنة متاحة عند الفصل الأخير فقط. أغلق الفصول السابقة من «نهاية الفصل»."}
        )

    if not prior_terms_all_closed(current_term, year):
        raise serializers.ValidationError({"detail": "يجب إغلاق جميع الفصول السابقة قبل نهاية السنة"})

    overrides = overrides or {}
    students = Student.objects.filter(is_active=True).select_related("school_class").order_by(
        "grade_level", "section", "name"
    )

    rows = []
    summary = {
        "promote": 0,
        "repeat": 0,
        "graduate": 0,
        "pending": 0,
        "passed": 0,
        "failed": 0,
    }

    for student in students:
        override = overrides.get(str(student.id))
        row = _serialize_preview_row(student, year, override)
        if row is None:
            continue
        rows.append(strip_subject_details_from_preview_row(row))
        if row["yearPassed"]:
            summary["passed"] += 1
        else:
            summary["failed"] += 1
        action = row["finalAction"]
        if action in summary:
            summary[action] += 1

    return {
        "scope": "year",
        "academicYearId": str(year.id),
        "academicYearName": year.name,
        "termId": str(current_term.id) if current_term else None,
        "termName": current_term.name if current_term else None,
        "gradePolicies": _serialize_grade_policies(),
        "summary": summary,
        "students": rows,
    }


def _next_year_name(current: AcademicYear) -> str:
    parts = current.name.split("-")
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        start = int(parts[1])
        return f"{start}-{start + 1}"
    return _default_year_name()


def _apply_student_action(student, action: str):
    if action == "promote":
        result = promote_student_to_next_grade(student)
        return "graduate" if result is None else "promote"
    if action == "graduate":
        return "graduate"
    return "repeat"


@transaction.atomic
def execute_year_end(year: AcademicYear, user, decisions=None, new_year_name=None, publish_certs=True):
    from academics.certificate_services import get_or_create_certificate_config, publish_certificates
    from academics.term_end_services import get_term_for_year, is_last_term, prior_terms_all_closed

    if not year.is_active:
        raise serializers.ValidationError({"detail": "يمكن تنفيذ نهاية السنة للسنة النشطة فقط"})

    current_term = get_term_for_year(year)
    if not current_term or not is_last_term(current_term, year):
        raise serializers.ValidationError(
            {"detail": "تنفيذ نهاية السنة متاح عند الفصل الأخير فقط. أغلق الفصول السابقة من «نهاية الفصل»."}
        )

    if not prior_terms_all_closed(current_term, year):
        raise serializers.ValidationError({"detail": "يجب إغلاق جميع الفصول السابقة قبل نهاية السنة"})

    if YearEndPromotionRun.objects.filter(
        academic_year=year, status=YearEndPromotionRun.STATUS_EXECUTED
    ).exists():
        raise serializers.ValidationError({"detail": "تم تنفيذ نهاية هذه السنة مسبقاً"})

    decision_map = {}
    if isinstance(decisions, list):
        for item in decisions:
            if not isinstance(item, dict):
                continue
            student_id = str(item.get("studentId") or item.get("id") or "").strip()
            action = str(item.get("action") or "").strip()
            if student_id and action in {"promote", "repeat", "graduate"}:
                decision_map[student_id] = action

    preview = preview_year_end(year, overrides=decision_map)
    pending = [row for row in preview["students"] if row["finalAction"] == "pending"]
    if pending:
        raise serializers.ValidationError(
            {
                "detail": f"يوجد {len(pending)} طالب يحتاج قراراً يدوياً قبل التنفيذ",
                "pendingStudentIds": [row["studentId"] for row in pending[:20]],
            }
        )

    executed_rows = []
    outcome_counts = {"promote": 0, "repeat": 0, "graduate": 0}

    for row in preview["students"]:
        student = Student.objects.select_related("school_class").get(id=row["studentId"])
        outcome = _apply_student_action(student, row["finalAction"])
        outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
        executed_rows.append({**row, "executedAction": outcome})

    if publish_certs:
        config = get_or_create_certificate_config(year)
        if config.issuance_scope != CertificateConfig.SCOPE_YEAR:
            config.issuance_scope = CertificateConfig.SCOPE_YEAR
            config.save(update_fields=["issuance_scope"])
        publish_certificates(year, user)

    if current_term and not current_term.is_closed:
        current_term.is_closed = True
        current_term.is_current = False
        current_term.closed_at = timezone.now()
        current_term.save(update_fields=["is_closed", "is_current", "closed_at"])

    ensure_all_grade_sections()

    year.is_active = False
    year.status = AcademicYear.STATUS_ARCHIVED
    year.save(update_fields=["is_active", "status"])

    next_name = (new_year_name or _next_year_name(year)).strip()
    if AcademicYear.objects.filter(name=next_name).exists():
        raise serializers.ValidationError({"newYearName": "اسم السنة الجديدة موجود مسبقاً"})

    start_year = int(next_name.split("-")[0])
    new_year = AcademicYear.objects.create(
        name=next_name,
        start_date=date(start_year, 9, 1),
        end_date=date(start_year + 1, 6, 30),
        status=AcademicYear.STATUS_ACTIVE,
        is_active=True,
    )
    first_term = _create_default_terms(new_year, mark_first_current=True)

    set_active_academic_year(new_year)
    if first_term:
        set_current_academic_term(first_term)
        reset_grade_inputs_for_term(first_term)

    for student in Student.objects.filter(is_active=True).select_related("school_class"):
        if student.school_class_id:
            Enrollment.objects.update_or_create(
                student=student,
                academic_year=new_year.name,
                defaults={"school_class": student.school_class},
            )

    run = YearEndPromotionRun.objects.create(
        academic_year=year,
        new_academic_year=new_year,
        executed_by=user if getattr(user, "is_authenticated", False) else None,
        status=YearEndPromotionRun.STATUS_EXECUTED,
        summary={"outcomeCounts": outcome_counts, "previewSummary": preview["summary"]},
        student_results=executed_rows,
    )

    return {
        "runId": str(run.id),
        "archivedYear": serialize_academic_year(year),
        "newYear": serialize_academic_year(new_year),
        "summary": outcome_counts,
        "students": executed_rows,
    }
