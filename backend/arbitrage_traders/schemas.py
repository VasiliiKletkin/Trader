from django.db import models


class ArbitrageSignalType(models.TextChoices):
    BUY = "buy", "Buy"
    SELL = "sell", "Sell"
    WAIT = "wait", "Wait"


class ArbitragePositionType(models.TextChoices):
    LONG = "long", "Long"
    SHORT = "short", "Short"


class ArbitragePositionStatus(models.TextChoices):
    OPENED = "opened", "Opened"
    CLOSED = "closed", "Closed"


class ArbitragePositionCloseReason(models.TextChoices):
    TAKE_PROFIT = "take_profit", "Take Profit"
    STOP_LOSS = "stop_loss", "Stop Loss"
    OPPOSITE_SIGNAL = "opposite_signal", "Opposite Signal"
    STRATEGY = "strategy", "Strategy"
    TIMEOUT = "timeout", "Timeout"
    MANUAL = "manual", "Manual"


class ArbitrageTraderStatus(models.TextChoices):
    ENABLED = "enabled", "Enabled"
    DISABLED = "disabled", "Disabled"
    REBOOTING = "rebooting", "Rebooting"
    ERROR = "error", "Error"
    PAUSED = "paused", "Paused"


class ArbitrageOptimizerStatus(models.TextChoices):
    ENABLED = "enabled", "Enabled"
    DISABLED = "disabled", "Disabled"
    REBOOTING = "rebooting", "Rebooting"
    ERROR = "error", "Error"
