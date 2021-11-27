from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import BlankTagByBot, BlankTagByHuman, SpeciesTag, SpeciesTagByBot, SpeciesTagByHuman


@admin.register(BlankTagByHuman)
class BlankTagByHumanAdmin(SimpleHistoryAdmin):
    def filename(self, obj):
        return obj.image.dropbox_file_name.split(" - ")[1:]

    def station_id(self, obj):
        return obj.image.upload.camera_station.station_id

    def micro_site(self, obj):
        return obj.image.upload.camera_station.micro_site.name

    def macro_site(self, obj):
        return obj.image.upload.camera_station.micro_site.macro_site.name

    def time_taken(self, obj):
        return obj.image.time_taken

    list_display = ["filename", "human", "blank", "station_id", "micro_site", "macro_site", "time_taken"]
    list_display_links = [
        "filename",
        "station_id",
        "micro_site",
        "macro_site",
        "time_taken",
    ]
    ordering = ["-created"]
    search_fields = ["filename", "human", "station_id", "micro_site", "macro_site"]


@admin.register(BlankTagByBot)
class BlankTagByBotEffectAdmin(SimpleHistoryAdmin):
    pass


@admin.register(SpeciesTag)
class SpeciesTagAdmin(SimpleHistoryAdmin):
    pass


@admin.register(SpeciesTagByHuman)
class SpeciesTagByHumanAdmin(SimpleHistoryAdmin):
    def filename(self, obj):
        return obj.image.dropbox_file_name.split(" - ")[1:]

    def station_id(self, obj):
        return obj.image.upload.camera_station.station_id

    def micro_site(self, obj):
        return obj.image.upload.camera_station.micro_site.name

    def macro_site(self, obj):
        return obj.image.upload.camera_station.micro_site.macro_site.name

    def time_taken(self, obj):
        return obj.image.time_taken

    list_display = ["filename", "human", "species", "station_id", "micro_site", "macro_site", "time_taken"]
    list_display_links = [
        "filename",
        "station_id",
        "micro_site",
        "macro_site",
        "time_taken",
    ]
    ordering = ["-created"]
    search_fields = ["filename", "human", "species", "station_id", "micro_site", "macro_site"]


@admin.register(SpeciesTagByBot)
class SpeciesTagByBotAdmin(SimpleHistoryAdmin):
    pass
