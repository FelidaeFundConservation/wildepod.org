from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import CameraTrapAction, Image, ImageMeta, Upload, UploadError, UploadErrorEffect


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


@admin.register(Image)
class ImageAdmin(SimpleHistoryAdmin):
    def trap_id(self, obj):
        return obj.upload.camera_trap.trap_id

    def micro_site(self, obj):
        return obj.upload.camera_trap.micro_site.name

    def macro_site(self, obj):
        return obj.upload.camera_trap.micro_site.macro_site.name

    def date_retrieved(self, obj):
        return obj.upload.date_retrieved

    list_display = ["filename", "trap_id", "micro_site", "macro_site", "date_retrieved"]
    list_display_links = [
        "trap_id",
        "micro_site",
        "macro_site",
        "date_retrieved",
    ]
    ordering = ["-created"]
    search_fields = ["filename", "trap_id", "micro_site", "macro_site"]


@admin.register(ImageMeta)
class ImageMetaAdmin(SimpleHistoryAdmin):
    pass
