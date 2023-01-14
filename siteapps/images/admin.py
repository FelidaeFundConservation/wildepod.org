from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import Annotator, Bot, BoundingBox, CameraStationAction, Category, Image, Species, SpeciesName, Upload, ActivityType


@admin.register(Upload)
class UploadAdmin(SimpleHistoryAdmin):
    list_display = ["dropbox_folder_name", "date_retrieved", "last_action", "volunteer", "priority"]
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


@admin.register(CameraStationAction)
class CameraStationActionAdmin(SimpleHistoryAdmin):
    pass


@admin.register(Image)
class ImageAdmin(SimpleHistoryAdmin):
    def dropbox_folder_name(self, obj):
        return obj.upload.dropbox_folder_name

    list_display = ["dropbox_folder_name", "trigger_timestamp"]
    list_display_links = [
        "dropbox_folder_name",
        "trigger_timestamp",
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
    search_fields = ["id", "upload__id"]


@admin.register(Bot)
class BotAdmin(SimpleHistoryAdmin):
    pass


@admin.register(Annotator)
class AnnotatorAdmin(SimpleHistoryAdmin):
    search_fields = ["human__name", "bot__name"]


@admin.register(BoundingBox)
class BoundingBoxAdmin(SimpleHistoryAdmin):
    search_fields = ["id", "image__id"]


@admin.register(SpeciesName)
class SpeciesNameAdmin(SimpleHistoryAdmin):
    list_display = ["name", "scientific_name"]
    list_display_links = ["name", "scientific_name"]
    search_fields = ["name", "scientific_name"]


@admin.register(Species)
class SpeciesAdmin(SimpleHistoryAdmin):
    search_fields = ["id", "bounding_box__id"]


@admin.register(Category)
class CategoryAdmin(SimpleHistoryAdmin):
    search_fields = ["id", "bounding_box__id"]


@admin.register(ActivityType)
class ActivityTypeAdmin(SimpleHistoryAdmin):
    list_display = ["name", "comments"]
    list_display_links = ["name"]
    search_fields = ["name"]
