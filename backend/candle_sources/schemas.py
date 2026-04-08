from django.db import models


class CandleSourceStatus(models.TextChoices):
    ENABLED = "enabled", "Enabled"
    DISABLED = "disabled", "Disabled"
    SYNCING = "syncing", "Syncing"
    CLEARING = "clearing", "Clearing"
    ERROR = "error", "Error"
