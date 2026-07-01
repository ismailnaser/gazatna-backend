from academics.academic_services import get_current_academic_term


def scope_to_current_term(qs, field="academic_term"):
    term = get_current_academic_term()
    if not term:
        return qs.none()
    return qs.filter(**{field: term})


def require_operational_term():
    term = get_current_academic_term()
    if not term:
        from rest_framework import serializers

        raise serializers.ValidationError({"detail": "لا يوجد فصل دراسي حالي"})
    return term


def stamp_operational_term(instance):
    if getattr(instance, "academic_term_id", None):
        return instance
    term = get_current_academic_term()
    if term:
        instance.academic_term = term
    return instance


def finalize_term_operational_closure(term):
    """Bind unscoped operational records to the closing term before it is marked closed."""
    from assignments.models import Homework, Quiz, SubjectAnnouncement, SubjectMaterial
    from content.models import Schedule

    from academics.models import ClassSubjectAssignment

    for model in (
        Schedule,
        Homework,
        Quiz,
        SubjectMaterial,
        SubjectAnnouncement,
        ClassSubjectAssignment,
    ):
        model.objects.filter(academic_term__isnull=True).update(academic_term=term)
