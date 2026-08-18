from datetime import date

from django.test import TestCase

from academics.analytics_services import _students_registered_in_year
from academics.models import AcademicYear, Student


class AnalyticsRegistrationTests(TestCase):
    def test_active_year_counts_current_students(self):
        year = AcademicYear.objects.create(
            name="2026/2027",
            start_date=date(2026, 9, 1),
            end_date=date(2027, 6, 30),
            is_active=True,
        )
        Student.objects.create(
            name="طالب تجريبي",
            student_number="100001",
            grade_level="الأول",
            section="أ",
        )
        self.assertEqual(_students_registered_in_year(year).count(), 1)
