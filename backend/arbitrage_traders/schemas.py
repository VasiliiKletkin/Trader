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


# class ArbitrageOptimizationPeriod(models.IntegerChoices):
#     ONE_WEEK = 7, "1 неделя"
#     TWO_WEEKS = 14, "2 недели"
#     ONE_MONTH = 30, "1 месяц"
#     THREE_MONTHS = 90, "3 месяца"
#     SIX_MONTHS = 180, "6 месяцев"
#     ONE_YEAR = 365, "1 год"
#     TWO_YEARS = 730, "2 года"
#     THREE_YEARS = 1095, "3 года"


class ArbitrageCandlesLookbackCount(models.IntegerChoices):
    COUNT_50 = 50, "50"
    COUNT_100 = 100, "100"
    COUNT_200 = 200, "200"
    COUNT_500 = 500, "500"
    COUNT_1000 = 1000, "1000"
    COUNT_2000 = 2000, "2000"
    COUNT_5000 = 5000, "5000"
    COUNT_10000 = 10000, "10000"
