from django.contrib import admin

from .models import Trader


@admin.register(Trader)
class TraderAdmin(admin.ModelAdmin):
    pass
