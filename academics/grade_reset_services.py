from academics.models import SubjectGrade, SubjectGradeScheme, SubjectGradeSchemeEntry


def reset_grade_inputs_for_term(term):
    """Prepare a term for fresh grade entry: remove schemes, entries, and stored grades."""
    schemes = SubjectGradeScheme.objects.filter(academic_term=term)
    SubjectGradeSchemeEntry.objects.filter(scheme__in=schemes).delete()
    schemes.delete()
    SubjectGrade.objects.filter(academic_term=term).delete()


def strip_subject_details_from_preview_row(row):
    """Hide per-subject breakdown in term/year-end previews."""
    if not row:
        return row
    return {
        **row,
        "subjects": [],
        "passedSubjectsCount": 0,
        "totalSubjectsCount": 0,
    }
