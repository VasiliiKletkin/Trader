from decimal import Decimal
from django.db import models
from optimizers.domain import Optimizer as DomainOptimizer

from core.utils.mixins import TimeStampedMixin
from core.utils.types import OptimizerStatus
from core.utils.types import (
    OrderSide,
    OrderStatus,
    PositionCloseReason,
    PositionStatus,
    PositionType,
    SignalType,
    Timeframe,
    TraderStatus,
)
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.forms import ValidationError
from django.urls import reverse
from django.utils import timezone
from exchange_clients.domain import AbstractExchangeClient
from exchange_clients.domain import ExchangeClientOrder as DomainExchangeClientOrder
from exchange_clients.models import ExchangeClient, ExchangeClientOrder
from exchanges.domain import Candle as DomainCandle
from exchanges.domain import Timeframe as DomainTimeframe
from exchanges.models import Candle, Exchange, TradingPair
from risk_managers.domain import PositionCloseReason as DomainPositionCloseReason
from risk_managers.domain import PositionStatus as DomainPositionStatus
from risk_managers.domain import PositionType as DomainPositionType
from risk_managers.models import RiskManager
from strategies.domain import SignalType as DomainSignalType
from strategies.domain import TraderSignal as DomainTraderSignal
from strategies.models import Strategy
from telegram_bots.tasks import send_notification
from traders.domain import Trader as DomainTrader
from traders.domain import TraderPosition as DomainTraderPosition
from traders.domain import TraderState as DomainTraderState


class Optimizer(TimeStampedMixin, models.Model):
    status = models.CharField(
        max_length=10,
        choices=OptimizerStatus.choices,
        default=OptimizerStatus.PENDING,
        verbose_name="Статус оптимизатора",
        help_text="Текущий статус оптимизатора трейдера.",
    )

    favorite = models.BooleanField(
        default=False,
        verbose_name="Избранный оптимизатор",
        help_text="Отметьте, если хотите добавить трейдера в избранное.",
    )

    exchange = models.ForeignKey(
        Exchange,
        on_delete=models.CASCADE,
        verbose_name="Биржа",
        limit_choices_to={"is_active": True},
    )

    trading_pair = models.ForeignKey(
        TradingPair,
        on_delete=models.CASCADE,
        verbose_name="Торговая пара",
        help_text="Укажите торговую пару, с которой будет работать трейдер.",
    )
    timeframe = models.CharField(
        max_length=10,
        choices=Timeframe.choices,
        default=Timeframe.ONE_MINUTE,
        verbose_name="Таймфрейм",
        help_text="Выберите таймфрейм, на котором будет работать трейдер.",
    )
    strategy = models.ForeignKey(
        Strategy,
        on_delete=models.CASCADE,
        verbose_name="Стратегия",
        limit_choices_to={"is_active": True},
        help_text="Выберите стратегию, которую будет использовать трейдер.",
    )
    risk_manager = models.ForeignKey(
        RiskManager,
        on_delete=models.CASCADE,
        verbose_name="Риск-менеджер",
        limit_choices_to={"is_active": True},
        help_text="Выберите риск-менеджер, который будет использовать трейдер.",
    )
    initial_balance = models.DecimalField(
        verbose_name="Начальный баланс",
        max_digits=20,
        decimal_places=2,
        default=Decimal("100.00"),
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("1000000000.00")),
        ],
    )
    max_drawdown_pct = models.DecimalField(
        verbose_name="Макс. просадка (%)",
        max_digits=5,
        decimal_places=2,
        default=Decimal("10.00"),
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("100.00")),
        ],
        help_text="Максимальная допустимая просадка в процентах от начального баланса.",
    )

    max_positions_count = models.PositiveSmallIntegerField(
        verbose_name="Макс. количество позиций",
        default=1,
        help_text="Максимальное количество одновременно открытых позиций.",
        validators=[
            MinValueValidator(1),
            MaxValueValidator(100),
        ],
    )
    close_position_by_opposite_signal = models.BooleanField(
        default=True,
        verbose_name="Закрывать позиции при противоположном сигнале",
        help_text="Если выбрано, будет закрывать позицию при получении противоположного сигнала.",
    )
    close_position_by_strategy = models.BooleanField(
        default=True,
        verbose_name="Закрывать позиции по сигналу стратегии",
        help_text="Если выбрано, будет закрывать позицию при получении сигнала от стратегии.",
    )
    close_position_by_stop_loss = models.BooleanField(
        default=True,
        verbose_name="Закрывать позиции по Stop Loss",
        help_text="Если выбрано, будет закрывать позицию при достижении Stop Loss.",
    )
    close_position_by_take_profit = models.BooleanField(
        default=True,
        verbose_name="Закрывать позиции по Take Profit",
        help_text="Если выбрано, будет закрывать позицию при достижении Take Profit.",
    )
    trail_stop_enabled = models.BooleanField(
        default=True,
        verbose_name="Трейлинг-стоп",
        help_text="Если выбрано, будет использовать трейлинг-стоп для позиций.",
    )
    last_reboot = models.DateTimeField(
        verbose_name="Последний перезапуск",
        null=True,
        blank=True,
        help_text="Дата и время последнего перезапуска трейдера.",
    )
    errors = models.TextField(
        null=True,
        blank=True,
    )
    last_error = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Последняя ошибка",
        help_text="Дата и время последней ошибки трейдера. ",
    )

    class Meta:
        verbose_name = "Оптимизатор"
        verbose_name_plural = "Оптимизаторы"
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "exchange_client",
                    "trading_pair",
                    "timeframe",
                    "strategy",
                    "risk_manager",
                    "initial_balance",
                    "max_drawdown_pct",
                    "max_positions_count",
                    "close_position_by_opposite_signal",
                    "close_position_by_strategy",
                    "close_position_by_stop_loss",
                    "close_position_by_take_profit",
                    "trail_stop_enabled",
                ],
                name="unique_optimizer",
            )
        ]

    class Meta:
        verbose_name = "Оптимизатор"
        verbose_name_plural = "Оптимизаторы"

    def instantiate(self) -> DomainOptimizer:
        return DomainOptimizer(
            candles_iterator=(
                c.instantiate() for c in self.candles.order_by("timestamp").iterator()
            ),
            trading_pair=self.trading_pair.instantiate(exchange=self.exchange),
            timeframe=DomainTimeframe(self.timeframe),
            strategy=self.strategy.instantiate(),
            risk_manager=self.risk_manager.instantiate(),
            initial_balance=self.initial_balance,
            max_drawdown_pct=self.max_drawdown_pct,
            max_positions_count=self.max_positions_count,
            trail_stop_enabled=self.trail_stop_enabled,
            close_position_by_stop_loss=self.close_position_by_stop_loss,
            close_position_by_take_profit=self.close_position_by_take_profit,
            close_position_by_strategy=self.close_position_by_strategy,
            close_position_by_opposite_signal=self.close_position_by_opposite_signal,
            current_balance=self.initial_balance,
        )

    @property
    def candles(self) -> models.QuerySet[Candle]:
        return Candle.objects.filter(
            exchange=self.exchange,
            timeframe=self.timeframe,
            trading_pair=self.trading_pair,
        )


class OptimizerResult(TimeStampedMixin, models.Model):
    optimizer = models.ForeignKey(
        Optimizer,
        on_delete=models.CASCADE,
    )
    theoretical_profit = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        verbose_name="Теоретическая прибыль",
    )
    strategy_arguments = models.JSONField()

    class Meta:
        verbose_name = "Отчет оптимизации"
        verbose_name_plural = "Отчеты оптимизации"
