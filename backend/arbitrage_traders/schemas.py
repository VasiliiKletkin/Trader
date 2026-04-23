from datetime import timedelta

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
    CLEARING = "clearing", "Clearing"
    ERROR = "error", "Error"
    PAUSED = "paused", "Paused"


class ArbitrageOptimizerStatus(models.TextChoices):
    ENABLED = "enabled", "Enabled"
    DISABLED = "disabled", "Disabled"
    REBOOTING = "rebooting", "Rebooting"
    ERROR = "error", "Error"


class ArbitrageOptimizationPeriod(models.TextChoices):
    ONE_WEEK = "1w", "1 неделя"
    TWO_WEEKS = "2w", "2 недели"
    ONE_MONTH = "1M", "1 месяц"
    THREE_MONTHS = "3M", "3 месяца"
    SIX_MONTHS = "6M", "6 месяцев"
    ONE_YEAR = "1y", "1 год"
    TWO_YEARS = "2y", "2 года"
    THREE_YEARS = "3y", "3 года"

    def timedelta(self) -> timedelta:
        return {
            self.ONE_WEEK: timedelta(weeks=1),
            self.TWO_WEEKS: timedelta(weeks=2),
            self.ONE_MONTH: timedelta(days=30),
            self.THREE_MONTHS: timedelta(days=90),
            self.SIX_MONTHS: timedelta(days=180),
            self.ONE_YEAR: timedelta(days=365),
            self.TWO_YEARS: timedelta(days=730),
            self.THREE_YEARS: timedelta(days=1095),
        }[self]


class ArbitrageCandlesLookbackCount(models.IntegerChoices):
    COUNT_1 = 1, "1"
    COUNT_10 = 10, "10"
    COUNT_50 = 50, "50"
    COUNT_100 = 100, "100"
    COUNT_200 = 200, "200"
    COUNT_500 = 500, "500"
    COUNT_1000 = 1000, "1000"
    COUNT_2000 = 2000, "2000"
    COUNT_5000 = 5000, "5000"
    COUNT_10000 = 10000, "10000"
