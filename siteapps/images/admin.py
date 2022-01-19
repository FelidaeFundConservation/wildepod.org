from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import (
    Annotator,
    Bot,
    BoundingBox,
    CameraStationAction,
    Category,
    Image,
    Species,
    SpeciesName,
    Upload,
    UploadError,
    UploadErrorEffect,
)


@admin.register(Upload)
class UploadAdmin(SimpleHistoryAdmin):
    list_display = ["dropbox_folder_name", "date_retrieved", "last_action", "volunteer"]
    list_display_links = [
        "dropbox_folder_name",
    ]
    readonly_fields = (
        "dropbox_folder_name",
        "dropbox_folder_path",
        "dropbox_request_id",
        "dropbox_request_url",
        "dropbox_request_open",
        "dropbox_folder_id",
        "dropbox_share_url",
    )
    ordering = ["-created"]
    search_fields = ["dropbox_folder_name", "volunteer"]


@admin.register(UploadError)
class UploadErrorAdmin(SimpleHistoryAdmin):
    pass


@admin.register(UploadErrorEffect)
class UploadErrorEffectAdmin(SimpleHistoryAdmin):
    pass


@admin.register(CameraStationAction)
class CameraStationActionAdmin(SimpleHistoryAdmin):
    pass


@admin.register(Image)
class ImageAdmin(SimpleHistoryAdmin):
    def dropbox_folder_name(self, obj):
        return obj.upload.dropbox_folder_name

    def date_retrieved(self, obj):
        return obj.upload.date_retrieved

    list_display = ["dropbox_folder_name", "dropbox_file_name", "date_retrieved"]
    list_display_links = [
        "dropbox_folder_name",
        "dropbox_file_name",
        "date_retrieved",
    ]
    readonly_fields = (
        "upload",
        "dropbox_file_name",
        "dropbox_content_hash",
        "dropbox_file_path",
        "dropbox_file_path_display",
        "dropbox_file_id",
        "file_size",
        "is_video",
        "height",
        "width",
        "duration",
    )
    ordering = ["-created"]
    search_fields = ["dropbox_folder_name"]


@admin.register(Bot)
class BotAdmin(SimpleHistoryAdmin):
    pass


@admin.register(Annotator)
class AnnotatorAdmin(SimpleHistoryAdmin):
    pass


@admin.register(BoundingBox)
class BoundingBoxAdmin(SimpleHistoryAdmin):
    pass


@admin.register(SpeciesName)
class SpeciesNameAdmin(SimpleHistoryAdmin):
    pass


@admin.register(Species)
class SpeciesAdmin(SimpleHistoryAdmin):
    pass


@admin.register(Category)
class CategoryAdmin(SimpleHistoryAdmin):
    pass
