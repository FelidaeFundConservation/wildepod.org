from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Profile


@admin.register(Profile)
class ProfileAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Other", {"fields": ("phone_number",)}),)
