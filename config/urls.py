from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from config.api_views import (
    AcademicContextView,
    AdminAnalyticsView,
    AdminAnalyticsDetailsView,
    AdminAcademicYearViewSet,
    AdminAdmissionApplicationsView,
    AdminApproveAdmissionView,
    AdminDeleteAdmissionView,
    AdminUnapproveAdmissionView,
    AdminArchiveContactMessageView,
    AdminBlockedStudentsView,
    AdminContactMessagesView,
    AdminInactiveStudentsView,
    AdminSiteSettingsView,
    PublicSiteSettingsView,
    PublicAdmissionApplicationView,
    PublicContactMessageView,
    AdminClassViewSet,
    AdminFeePlanViewSet,
    AdminGradeSchemeTemplateView,
    AdminGradeViewSet,
    AdminFinanceViewSet,
    AdminNewsViewSet,
    AdminScheduleViewSet,
    AdminStudentViewSet,
    AdminSubjectViewSet,
    AdminTeacherViewSet,
    AdminStaffTypeViewSet,
    ParentAlertsView,
    ParentAlertDismissView,
    ParentArchiveCertificatesView,
    ParentArchiveTermGradesView,
    ParentArchiveView,
    ParentCertificatesView,
    ParentChildView,
    ParentFeesView,
    ParentGradesView,
    ParentGradesNotificationView,
    ParentAssessmentsView,
    ParentHomeworkView,
    ParentHomeworkBySubjectView,
    ParentHomeworkDetailView,
    ParentSubjectDetailView,
    ParentSubjectsView,
    ParentQuizzesView,
    ParentQuizReviewView,
    ParentSchedulesView,
    ParentStudentView,
    ParentSubmissionsView,
    PublicNewsViewSet,
    PublicProgramViewSet,
    PublicSchoolValuesView,
    PublicStatsView,
    PublicTeachersViewSet,
    TeacherAssessmentsView,
    TeacherAlertsView,
    TeacherArchiveClassGradesView,
    TeacherArchiveTermClassesView,
    TeacherArchiveView,
    TeacherAlertReadView,
    TeacherClassDetailView,
    TeacherClassesView,
    TeacherAnnouncementViewSet,
    TeacherGradeSchemeView,
    TeacherHomeworkViewSet,
    TeacherMaterialViewSet,
    TeacherProfileView,
    TeacherQuizViewSet,
    TeacherSchedulesView,
)

router = DefaultRouter()
router.register("content/news", PublicNewsViewSet, basename="public-news")
router.register("content/programs", PublicProgramViewSet, basename="public-programs")
router.register("staff/teachers", PublicTeachersViewSet, basename="public-teachers")
router.register("admin/students", AdminStudentViewSet, basename="admin-students")
router.register("admin/academic-years", AdminAcademicYearViewSet, basename="admin-academic-years")
router.register("admin/grades", AdminGradeViewSet, basename="admin-grades")
router.register("admin/classes", AdminClassViewSet, basename="admin-classes")
router.register("admin/subjects", AdminSubjectViewSet, basename="admin-subjects")
router.register("admin/teachers", AdminTeacherViewSet, basename="admin-teachers")
router.register("admin/staff-types", AdminStaffTypeViewSet, basename="admin-staff-types")
router.register("admin/finance/plans", AdminFeePlanViewSet, basename="admin-finance-plans")
router.register("admin/finance/payments", AdminFinanceViewSet, basename="admin-finance")
router.register("admin/schedules", AdminScheduleViewSet, basename="admin-schedules")
router.register("admin/content/news", AdminNewsViewSet, basename="admin-news")
router.register("teacher/homework", TeacherHomeworkViewSet, basename="teacher-homework")
router.register("teacher/quizzes", TeacherQuizViewSet, basename="teacher-quizzes")
router.register("teacher/announcements", TeacherAnnouncementViewSet, basename="teacher-announcements")
router.register("teacher/materials", TeacherMaterialViewSet, basename="teacher-materials")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("accounts.urls")),
    path("api/content/values/", PublicSchoolValuesView.as_view()),
    path("api/content/stats/", PublicStatsView.as_view()),
    path("api/admin/analytics/", AdminAnalyticsView.as_view()),
    path("api/admin/analytics/details/", AdminAnalyticsDetailsView.as_view()),
    path("api/academic-context/", AcademicContextView.as_view()),
    path("api/site-settings/", PublicSiteSettingsView.as_view()),
    path("api/admin/site-settings/", AdminSiteSettingsView.as_view()),
    path("api/admissions/", PublicAdmissionApplicationView.as_view()),
    path("api/contact/messages/", PublicContactMessageView.as_view()),
    path("api/admin/admissions/", AdminAdmissionApplicationsView.as_view()),
    path("api/admin/admissions/<str:app_id>/approve/", AdminApproveAdmissionView.as_view()),
    path("api/admin/admissions/<str:app_id>/unapprove/", AdminUnapproveAdmissionView.as_view()),
    path("api/admin/admissions/<str:app_id>/", AdminDeleteAdmissionView.as_view()),
    path("api/admin/messages/", AdminContactMessagesView.as_view()),
    path("api/admin/messages/<str:message_id>/archive/", AdminArchiveContactMessageView.as_view()),
    path("api/admin/notifications/blocked-students/", AdminBlockedStudentsView.as_view()),
    path("api/admin/notifications/inactive-students/", AdminInactiveStudentsView.as_view()),
    path("api/admin/grade-scheme-template/", AdminGradeSchemeTemplateView.as_view()),
    path("api/teacher/profile/", TeacherProfileView.as_view()),
    path("api/teacher/schedules/", TeacherSchedulesView.as_view()),
    path("api/teacher/classes/", TeacherClassesView.as_view()),
    path("api/teacher/classes/<int:class_id>/", TeacherClassDetailView.as_view()),
    path("api/teacher/assessments/", TeacherAssessmentsView.as_view()),
    path("api/teacher/grade-schemes/", TeacherGradeSchemeView.as_view()),
    path("api/teacher/archive/", TeacherArchiveView.as_view()),
    path("api/teacher/archive/terms/<int:term_id>/classes/", TeacherArchiveTermClassesView.as_view()),
    path(
        "api/teacher/archive/terms/<int:term_id>/classes/<int:class_id>/grades/",
        TeacherArchiveClassGradesView.as_view(),
    ),
    path("api/teacher/alerts/", TeacherAlertsView.as_view()),
    path("api/teacher/alerts/read/", TeacherAlertReadView.as_view()),
    path("api/parent/alerts/", ParentAlertsView.as_view()),
    path("api/parent/alerts/dismiss/", ParentAlertDismissView.as_view()),
    path("api/parent/child/", ParentChildView.as_view()),
    path("api/parent/schedules/", ParentSchedulesView.as_view()),
    path("api/parent/student/", ParentStudentView.as_view()),
    path("api/parent/grades/", ParentGradesView.as_view()),
    path("api/parent/grades/notification/", ParentGradesNotificationView.as_view()),
    path("api/parent/archive/", ParentArchiveView.as_view()),
    path("api/parent/archive/certificates/", ParentArchiveCertificatesView.as_view()),
    path("api/parent/archive/terms/<int:term_id>/grades/", ParentArchiveTermGradesView.as_view()),
    path("api/parent/certificates/", ParentCertificatesView.as_view()),
    path("api/parent/assessments/", ParentAssessmentsView.as_view()),
    path("api/parent/fees/", ParentFeesView.as_view()),
    path("api/parent/homework/", ParentHomeworkView.as_view()),
    path("api/parent/homework/<int:homework_id>/", ParentHomeworkDetailView.as_view()),
    path("api/parent/homework/by-subject/", ParentHomeworkBySubjectView.as_view()),
    path("api/parent/subjects/", ParentSubjectsView.as_view()),
    path("api/parent/subjects/<str:subject>/", ParentSubjectDetailView.as_view()),
    path("api/parent/quizzes/", ParentQuizzesView.as_view()),
    path("api/parent/quizzes/<int:quiz_id>/review/", ParentQuizReviewView.as_view()),
    path("api/parent/submissions/", ParentSubmissionsView.as_view()),
    path("api/", include(router.urls)),
]

if settings.DEBUG:
    from django.conf.urls.static import static

    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
else:
    # cPanel/Passenger: serve uploaded media in production (no separate CDN/alias).
    from django.urls import re_path
    from django.views.static import serve

    urlpatterns += [
        re_path(
            r"^media/(?P<path>.*)$",
            serve,
            {"document_root": settings.MEDIA_ROOT},
        ),
    ]