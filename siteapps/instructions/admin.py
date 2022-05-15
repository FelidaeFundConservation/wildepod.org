from django.contrib import admin
from django.db import models
from simple_history.admin import SimpleHistoryAdmin
from tinymce.widgets import TinyMCE

from .models import Instructions


# Register your models here.
@admin.register(Instructions)
class InstructionsAdmin(SimpleHistoryAdmin):
    list_display = ["version", "active"]
    list_display_links = ["version", "active"]

    formfield_overrides = {models.TextField: {"widget": TinyMCE()}}
