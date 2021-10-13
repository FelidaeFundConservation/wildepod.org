from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import Bot, BotTaskType


@admin.register(BotTaskType)
class BotTaskTypeAdmin(SimpleHistoryAdmin):
    pass


@admin.register(Bot)
class BotAdmin(SimpleHistoryAdmin):
    pass
