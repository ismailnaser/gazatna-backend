from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from accounts.models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ("email", "first_name", "role", "status", "is_staff")
    list_filter = ("role", "status")
    fieldsets = UserAdmin.fieldsets + (("معلومات المدرسة", {"fields": ("role", "status")}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("معلومات المدرسة", {"fields": ("role", "status")}),)
