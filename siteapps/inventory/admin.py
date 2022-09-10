from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import Box, Camera, CameraBrand, CameraModel, Padlock, PythonLock


@admin.register(Padlock)
class PadlockAdmin(SimpleHistoryAdmin):
    list_display = ["name", "created"]
    list_display_links = ["name"]
    search_fields = ["name"]


@admin.register(PythonLock)
class PythonLockAdmin(SimpleHistoryAdmin):
    list_display = ["number", "duplicate_key_exists", "created"]
    list_display_links = ["number"]
    search_fields = ["number"]


# @admin.register(Box)
# class BoxAdmin(SimpleHistoryAdmin):
#     list_display = ["name", "created"]
#     list_display_links = ["name"]
#     search_fields = ["name"]


@admin.register(CameraBrand)
class CameraBrandAdmin(SimpleHistoryAdmin):
    list_display = ["name", "created"]
    list_display_links = ["name"]
    search_fields = ["name"]


@admin.register(CameraModel)
class CameraModelAdmin(SimpleHistoryAdmin):
    def brand(self, obj):
        return obj.brand.name

    list_display = ["name", "brand", "created"]
    list_display_links = ["name"]
    ordering = ["-created"]
    search_fields = ["name"]


@admin.register(Camera)
class CameraAdmin(SimpleHistoryAdmin):
    def camera_model(self, obj):
        return obj.model.name

    list_display = ["serial_number", "camera_model", "created"]
    list_display_links = ["serial_number"]
    ordering = ["-created"]
    search_fields = ["serial_number", "model__name"]
