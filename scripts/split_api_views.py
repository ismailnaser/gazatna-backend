"""
One-shot splitter: move config/api_views.py view classes into domain apps.

Run from gazatna-backend:
  python scripts/split_api_views.py
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "config" / "api_views.py"
BACKUP = ROOT / "config" / "api_views.py.bak"

# Target module -> class names
TARGETS: dict[str, list[str]] = {
    "accounts/api_views.py": [
        "AdminUserViewSet",
    ],
    "content/api_views.py": [
        "PublicNewsViewSet",
        "PublicProgramViewSet",
        "PublicStatsView",
        "PublicSchoolValuesView",
        "AdminNewsViewSet",
        "PublicSiteSettingsView",
        "AdminSiteSettingsView",
        "PublicAdmissionApplicationView",
        "AdminAdmissionApplicationsView",
        "AdminApproveAdmissionView",
        "AdminUnapproveAdmissionView",
        "AdminDeleteAdmissionView",
        "PublicContactMessageView",
        "AdminContactMessagesView",
        "AdminArchiveContactMessageView",
    ],
    "staff/api_views.py": [
        "PublicTeachersViewSet",
        "AdminTeacherViewSet",
        "AdminStaffTypeViewSet",
        "TeacherProfileView",
    ],
    "finance/api_views.py": [
        "AdminFeePlanViewSet",
        "AdminFinanceViewSet",
        "ParentFeesView",
        "AdminBlockedStudentsView",
        "_build_fees_chart",
    ],
    "assignments/api_views.py": [
        "TeacherHomeworkViewSet",
        "TeacherAssessmentsView",
        "TeacherAlertsView",
        "TeacherAlertReadView",
        "TeacherQuizViewSet",
        "TeacherAnnouncementViewSet",
        "TeacherMaterialViewSet",
        "ParentAlertsView",
        "ParentAlertDismissView",
        "ParentHomeworkView",
        "ParentHomeworkBySubjectView",
        "ParentSubjectsView",
        "ParentSubjectDetailView",
        "ParentHomeworkDetailView",
        "ParentQuizzesView",
        "ParentQuizReviewView",
        "ParentSubmissionsView",
        "_publish_homework_grades",
        "_publish_quiz_grades",
        "_subject_label",
        "_subject_homework_q",
        "_subject_quiz_q",
        "_subject_announcement_q",
        "_subject_material_q",
        "_parse_class_ids",
        "_validate_teacher_class_ids_response",
        "_teacher_school_class_or_response",
        "_teacher_for_user",
        "_operational_term",
        "_scope_operational_term",
    ],
    "academics/api_views.py": [
        "AdminStudentViewSet",
        "AdminClassViewSet",
        "AdminGradeViewSet",
        "AdminSubjectViewSet",
        "AdminGradeSchemeTemplateView",
        "AdminAnalyticsView",
        "AdminAnalyticsDetailsView",
        "AdminInactiveStudentsView",
        "AdminScheduleViewSet",
        "TeacherClassesView",
        "TeacherClassDetailView",
        "TeacherGradeSchemeView",
        "TeacherSchedulesView",
        "ParentChildView",
        "ParentStudentView",
        "ParentGradesView",
        "ParentGradesNotificationView",
        "ParentCertificatesView",
        "ParentAssessmentsView",
        "ParentSchedulesView",
        "AcademicContextView",
        "AdminAcademicYearViewSet",
        "ParentArchiveView",
        "ParentArchiveTermGradesView",
        "ParentArchiveCertificatesView",
        "TeacherArchiveView",
        "TeacherArchiveTermClassesView",
        "TeacherArchiveClassGradesView",
        "_sync_grade_sections",
        "_sync_grade_sections_count",
        "_parse_gradebook_score",
        "_shift_month",
        "_build_grade_chart",
        "_linked_student_for_parent",
        "_child_for_parent",
        "_normalize_teacher_name",
        "_schedule_entry_text",
        "_school_class_label",
        "AR_MONTHS",
    ],
}

HELPER_SHARED = [
    "_teacher_for_user",
    "_operational_term",
    "_scope_operational_term",
    "_parse_class_ids",
    "_validate_teacher_class_ids_response",
    "_teacher_school_class_or_response",
    "_linked_student_for_parent",
    "_child_for_parent",
]


def split_top_level(source: str) -> tuple[str, list[tuple[str, str, str]]]:
    """Return (header_imports, [(kind, name, body), ...])."""
    lines = source.splitlines(keepends=True)
    # Find first top-level def/class after imports
    start = 0
    for i, line in enumerate(lines):
        if line.startswith("class ") or line.startswith("def ") or line.startswith("AR_MONTHS"):
            start = i
            break
    header = "".join(lines[:start])
    blocks: list[tuple[str, str, str]] = []
    i = start
    while i < len(lines):
        line = lines[i]
        if line.startswith("class "):
            m = re.match(r"class\s+(\w+)", line)
            name = m.group(1) if m else f"class_{i}"
            kind = "class"
        elif line.startswith("def "):
            m = re.match(r"def\s+(\w+)", line)
            name = m.group(1) if m else f"def_{i}"
            kind = "def"
        elif line.startswith("AR_MONTHS"):
            name = "AR_MONTHS"
            kind = "const"
        else:
            i += 1
            continue
        j = i + 1
        while j < len(lines):
            nxt = lines[j]
            if nxt.startswith("class ") or nxt.startswith("def ") or (
                nxt.startswith("AR_MONTHS") and name != "AR_MONTHS"
            ):
                break
            j += 1
        body = "".join(lines[i:j])
        blocks.append((kind, name, body))
        i = j
    return header, blocks


def main() -> None:
    source = SRC.read_text(encoding="utf-8")
    if not BACKUP.exists():
        shutil.copy2(SRC, BACKUP)
        print(f"Backup -> {BACKUP}")

    header, blocks = split_top_level(source)
    by_name = {name: (kind, body) for kind, name, body in blocks}

    # Shared helpers module used across apps
    helpers_names = [
        "_teacher_for_user",
        "_operational_term",
        "_scope_operational_term",
        "_parse_class_ids",
        "_validate_teacher_class_ids_response",
        "_teacher_school_class_or_response",
        "_linked_student_for_parent",
        "_child_for_parent",
        "_parse_gradebook_score",
        "_shift_month",
        "_build_fees_chart",
        "_build_grade_chart",
        "_publish_homework_grades",
        "_publish_quiz_grades",
        "_subject_label",
        "_subject_homework_q",
        "_subject_quiz_q",
        "_subject_announcement_q",
        "_subject_material_q",
        "_sync_grade_sections",
        "_sync_grade_sections_count",
        "_normalize_teacher_name",
        "_schedule_entry_text",
        "_school_class_label",
        "AR_MONTHS",
    ]
    helpers_body = []
    for name in helpers_names:
        if name in by_name:
            helpers_body.append(by_name[name][1])

    helpers_path = ROOT / "config" / "api_helpers.py"
    helpers_path.write_text(
        header
        + "\n# --- shared helpers extracted from api_views ---\n\n"
        + "\n".join(helpers_body),
        encoding="utf-8",
    )
    print(f"Wrote {helpers_path}")

    # Per-app modules: header + import helpers + selected classes only
    all_assigned = set()
    for rel, names in TARGETS.items():
        parts = []
        for name in names:
            if name in helpers_names:
                continue  # live in api_helpers
            if name not in by_name:
                print(f"WARN missing {name}")
                continue
            parts.append(by_name[name][1])
            all_assigned.add(name)
        path = ROOT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        content = (
            header
            + "\nfrom config.api_helpers import *  # noqa: F401,F403\n\n"
            + "\n".join(parts)
        )
        path.write_text(content, encoding="utf-8")
        print(f"Wrote {path} ({len(parts)} symbols)")

    # Compatibility shim
    shim = '''"""Backward-compatible re-exports. Prefer importing from domain apps. """
from accounts.api_views import *  # noqa: F401,F403
from academics.api_views import *  # noqa: F401,F403
from assignments.api_views import *  # noqa: F401,F403
from content.api_views import *  # noqa: F401,F403
from finance.api_views import *  # noqa: F401,F403
from staff.api_views import *  # noqa: F401,F403
from config.api_helpers import *  # noqa: F401,F403
'''
    SRC.write_text(shim, encoding="utf-8")
    print(f"Replaced {SRC} with compatibility shim")

    unassigned = [n for n in by_name if n not in all_assigned and n not in helpers_names]
    if unassigned:
        print("UNASSIGNED:", unassigned)


if __name__ == "__main__":
    main()
