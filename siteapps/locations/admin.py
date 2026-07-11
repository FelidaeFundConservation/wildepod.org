# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import Area, CameraStation, County, Grid, HabitatType, MacroSite, MicroSite, TrailType


@admin.register(Area)
class AreaAdmin(SimpleHistoryAdmin):
    list_display = ["name", "created"]
    list_display_links = ["name"]
    search_fields = ["name"]


@admin.register(County)
class CountyAdmin(SimpleHistoryAdmin):
    list_display = ["name", "created"]
    list_display_links = ["name"]
    search_fields = ["name"]


@admin.register(Grid)
class GridAdmin(SimpleHistoryAdmin):
    list_display = ["name", "created"]
    list_display_links = ["name"]
    search_fields = ["name"]


@admin.register(MacroSite)
class MacroSiteAdmin(SimpleHistoryAdmin):
    list_display = ["name", "created"]
    list_display_links = ["name"]
    search_fields = ["name"]


@admin.register(MicroSite)
class MicroSiteAdmin(SimpleHistoryAdmin):
    list_display = ["name", "created"]
    list_display_links = ["name"]
    search_fields = ["name"]


@admin.register(TrailType)
class TrailTypeAdmin(SimpleHistoryAdmin):
    list_display = ["name", "created"]
    list_display_links = ["name"]
    search_fields = ["name"]


@admin.register(HabitatType)
class HabitatTypeAdmin(SimpleHistoryAdmin):
    list_display = ["name", "created"]
    list_display_links = ["name"]
    search_fields = ["name"]


@admin.register(CameraStation)
class CameraStationAdmin(SimpleHistoryAdmin):
    list_display = [
        "station_id",
        "date_deployed",
        "latitude",
        "longitude",
        "micro_site",
    ]
    list_display_links = ["station_id", "micro_site"]
    ordering = ["-date_deployed"]
    search_fields = ["station_id", "micro_site__name"]
