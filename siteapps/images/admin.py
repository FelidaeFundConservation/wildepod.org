# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import (
    ActivityType,
    Annotator,
    Bot,
    BoundingBox,
    CameraStationAction,
    Category,
    Image,
    Species,
    SpeciesName,
    SpeciesSubgroup,
    TimeCorrection,
    Upload,
)


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


@admin.register(TimeCorrection)
class TimeCorrectionAdmin(SimpleHistoryAdmin):
    list_display = ["id", "years", "months", "days", "hours", "minutes", "daylight_savings"]
    list_display_links = ["id", "years", "months", "days", "hours", "minutes", "daylight_savings"]
    readonly_fields = ()
    ordering = ["-created"]
    search_fields = ["id", "upload__id"]


@admin.register(Bot)
class BotAdmin(SimpleHistoryAdmin):
    pass


@admin.register(Annotator)
class AnnotatorAdmin(SimpleHistoryAdmin):
    search_fields = ["human__name", "bot__name"]
    list_display = ["__str__", "type", "automation_criteria"]
    list_filter = ["type", "automation_criteria"]


@admin.register(BoundingBox)
class BoundingBoxAdmin(SimpleHistoryAdmin):
    search_fields = ["id", "image__id"]


@admin.register(SpeciesName)
class SpeciesNameAdmin(SimpleHistoryAdmin):
    list_display = ["name", "scientific_name"]
    list_display_links = ["name", "scientific_name"]
    search_fields = ["name", "scientific_name"]


@admin.register(SpeciesSubgroup)
class SpeciesSubgroupAdmin(SimpleHistoryAdmin):
    list_display = ["name"]
    list_display_links = ["name"]
    search_fields = ["name"]


@admin.register(Species)
class SpeciesAdmin(SimpleHistoryAdmin):
    search_fields = ["id", "bounding_box__id"]


@admin.register(Category)
class CategoryAdmin(SimpleHistoryAdmin):
    search_fields = ["id", "bounding_box__id"]


@admin.register(ActivityType)
class ActivityTypeAdmin(SimpleHistoryAdmin):
    list_display = ["name", "category", "comments"]
    list_display_links = ["name"]
    search_fields = ["name"]
