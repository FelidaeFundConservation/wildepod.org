from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import Snapshot


@admin.register(Snapshot)
class SnapshotAdmin(SimpleHistoryAdmin):
    list_display = ["created", "volunteer", "status", "start_date", "end_date"]
    ordering = ["-created"]
    search_fields = ["created", "volunteer"]
