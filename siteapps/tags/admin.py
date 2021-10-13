from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import BlankTagByBot, BlankTagByHuman, SpeciesTag, SpeciesTagByBot, SpeciesTagByHuman


@admin.register(BlankTagByHuman)
class BlankTagByHumanAdmin(SimpleHistoryAdmin):
    def filename(self, obj):
        return obj.image.filename

    def trap_id(self, obj):
        return obj.image.upload.camera_trap.trap_id

    def micro_site(self, obj):
        return obj.image.upload.camera_trap.micro_site.name

    def macro_site(self, obj):
        return obj.image.upload.camera_trap.micro_site.macro_site.name

    def date_retrieved(self, obj):
        return obj.image.upload.date_retrieved

    list_display = ["filename", "human", "blank", "trap_id", "micro_site", "macro_site", "date_retrieved"]
    list_display_links = [
        "trap_id",
        "micro_site",
        "macro_site",
        "date_retrieved",
    ]
    ordering = ["-created"]
    search_fields = ["filename", "human", "trap_id", "micro_site", "macro_site"]


@admin.register(BlankTagByBot)
class BlankTagByBotEffectAdmin(SimpleHistoryAdmin):
    pass


@admin.register(SpeciesTag)
class SpeciesTagAdmin(SimpleHistoryAdmin):
    pass


@admin.register(SpeciesTagByHuman)
class SpeciesTagByHumanAdmin(SimpleHistoryAdmin):
    def filename(self, obj):
        return obj.image.filename

    def trap_id(self, obj):
        return obj.image.upload.camera_trap.trap_id

    def micro_site(self, obj):
        return obj.image.upload.camera_trap.micro_site.name

    def macro_site(self, obj):
        return obj.image.upload.camera_trap.micro_site.macro_site.name

    def date_retrieved(self, obj):
        return obj.image.upload.date_retrieved

    list_display = ["filename", "human", "species", "trap_id", "micro_site", "macro_site", "date_retrieved"]
    list_display_links = [
        "trap_id",
        "micro_site",
        "macro_site",
        "date_retrieved",
    ]
    ordering = ["-created"]
    search_fields = ["filename", "human", "species", "trap_id", "micro_site", "macro_site"]


@admin.register(SpeciesTagByBot)
class SpeciesTagByBotAdmin(SimpleHistoryAdmin):
    pass
