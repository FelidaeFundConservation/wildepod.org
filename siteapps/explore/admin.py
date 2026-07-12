# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import Snapshot


@admin.register(Snapshot)
class SnapshotAdmin(SimpleHistoryAdmin):
    list_display = ["created", "volunteer", "status", "start_date", "end_date"]
    ordering = ["-created"]
    search_fields = ["created", "volunteer"]
