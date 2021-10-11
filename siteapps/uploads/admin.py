from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import CameraTrapAction, Upload, UploadError, UploadErrorEffect


@admin.register(Upload)
class UploadAdmin(SimpleHistoryAdmin):
    def trap_id(self, obj):
        return obj.camera_trap.trap_id

    def micro_site(self, obj):
        return obj.camera_trap.micro_site.name

    def macro_site(self, obj):
        return obj.camera_trap.micro_site.macro_site.name

    list_display = ["trap_id", "micro_site", "macro_site", "date_retrieved", "last_action", "volunteer"]
    list_display_links = [
        "trap_id",
        "micro_site",
        "macro_site",
        "date_retrieved",
    ]
    ordering = ["-created"]
    search_fields = ["trap_id", "micro_site", "macro_site", "volunteer"]


@admin.register(UploadError)
class UploadErrorAdmin(SimpleHistoryAdmin):
    pass


@admin.register(UploadErrorEffect)
class UploadErrorEffectAdmin(SimpleHistoryAdmin):
    pass


@admin.register(CameraTrapAction)
class CameraTrapActionAdmin(SimpleHistoryAdmin):
    pass
