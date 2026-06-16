from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from config.api_views import (
    AdminAnalyticsView,
    AdminAnalyticsDetailsView,
    AdminAdmissionApplicationsView,
    AdminApproveAdmissionView,
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
    AdminGradeViewSet,
    AdminFinanceViewSet,
    AdminNewsViewSet,
    AdminStudentViewSet,
    AdminSubjectViewSet,
    AdminTeacherViewSet,
    ParentAlertsView,
    ParentChildView,
    ParentFeesView,
    ParentGradesView,
    ParentHomeworkView,
    ParentQuizzesView,
    ParentStudentView,
    ParentSubmissionsView,
    PublicAccreditationViewSet,
    PublicActivityViewSet,
    PublicAlumniViewSet,
    PublicNewsViewSet,
    PublicPolicyViewSet,
    PublicProgramViewSet,
    PublicSchoolValuesView,
    PublicStatsView,
    PublicTeachersViewSet,
    TeacherClassDetailView,
    TeacherClassesView,
    TeacherHomeworkViewSet,
    TeacherProfileView,
    TeacherQuizViewSet,
)

router = DefaultRouter()
router.register("content/news", PublicNewsViewSet, basename="public-news")
router.register("content/programs", PublicProgramViewSet, basename="public-programs")
router.register("content/activities", PublicActivityViewSet, basename="public-activities")
router.register("content/alumni", PublicAlumniViewSet, basename="public-alumni")
router.register("content/policies", PublicPolicyViewSet, basename="public-policies")
router.register("content/accreditations", PublicAccreditationViewSet, basename="public-accreditations")
router.register("staff/teachers", PublicTeachersViewSet, basename="public-teachers")
router.register("admin/students", AdminStudentViewSet, basename="admin-students")
router.register("admin/grades", AdminGradeViewSet, basename="admin-grades")
router.register("admin/classes", AdminClassViewSet, basename="admin-classes")
router.register("admin/subjects", AdminSubjectViewSet, basename="admin-subjects")
router.register("admin/teachers", AdminTeacherViewSet, basename="admin-teachers")
router.register("admin/finance/plans", AdminFeePlanViewSet, basename="admin-finance-plans")
router.register("admin/finance/payments", AdminFinanceViewSet, basename="admin-finance")
router.register("admin/content/news", AdminNewsViewSet, basename="admin-news")
router.register("teacher/homework", TeacherHomeworkViewSet, basename="teacher-homework")
router.register("teacher/quizzes", TeacherQuizViewSet, basename="teacher-quizzes")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("accounts.urls")),
    path("api/content/values/", PublicSchoolValuesView.as_view()),
    path("api/content/stats/", PublicStatsView.as_view()),
    path("api/admin/analytics/", AdminAnalyticsView.as_view()),
    path("api/admin/analytics/details/", AdminAnalyticsDetailsView.as_view()),
    path("api/site-settings/", PublicSiteSettingsView.as_view()),
    path("api/admin/site-settings/", AdminSiteSettingsView.as_view()),
    path("api/admissions/", PublicAdmissionApplicationView.as_view()),
    path("api/contact/messages/", PublicContactMessageView.as_view()),
    path("api/admin/admissions/", AdminAdmissionApplicationsView.as_view()),
    path("api/admin/admissions/<str:app_id>/approve/", AdminApproveAdmissionView.as_view()),
    path("api/admin/messages/", AdminContactMessagesView.as_view()),
    path("api/admin/messages/<str:message_id>/archive/", AdminArchiveContactMessageView.as_view()),
    path("api/admin/notifications/blocked-students/", AdminBlockedStudentsView.as_view()),
    path("api/admin/notifications/inactive-students/", AdminInactiveStudentsView.as_view()),
    path("api/teacher/profile/", TeacherProfileView.as_view()),
    path("api/teacher/classes/", TeacherClassesView.as_view()),
    path("api/teacher/classes/<int:class_id>/", TeacherClassDetailView.as_view()),
    path("api/parent/alerts/", ParentAlertsView.as_view()),
    path("api/parent/child/", ParentChildView.as_view()),
    path("api/parent/student/", ParentStudentView.as_view()),
    path("api/parent/grades/", ParentGradesView.as_view()),
    path("api/parent/fees/", ParentFeesView.as_view()),
    path("api/parent/homework/", ParentHomeworkView.as_view()),
    path("api/parent/quizzes/", ParentQuizzesView.as_view()),
    path("api/parent/submissions/", ParentSubmissionsView.as_view()),
    path("api/", include(router.urls)),
]

if settings.DEBUG:
    from django.conf.urls.static import static

    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)