from django.contrib import admin
from risk_managers import models


@admin.register(models.RiskManager)
class RiskManagerAdmin(admin.ModelAdmin):
    pass
