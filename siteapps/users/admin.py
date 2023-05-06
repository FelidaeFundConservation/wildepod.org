from django.contrib import admin
from django.contrib.auth import admin as auth_admin
from django.contrib.auth import get_user_model

from .forms import UserAdminChangeForm, UserAdminCreationForm

User = get_user_model()


@admin.register(User)
class UserAdmin(auth_admin.UserAdmin):
    form = UserAdminChangeForm
    add_form = UserAdminCreationForm
    list_display = ("email", "name", "is_volunteer", "is_staff", "is_expert")
    list_filter = ("is_active", "is_volunteer", "is_staff", "is_expert")
    fieldsets = (
        (None, {"fields": ("email", "password", "name", "phone_number")}),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_volunteer",
                    "is_staff",
                    "is_expert",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "password1",
                    "password2",
                    "name",
                    "is_volunteer",
                    "is_staff",
                    "is_expert",
                    "is_active",
                ),
            },
        ),
    )
    search_fields = (
        "email",
        "name",
    )
    ordering = ("name",)
