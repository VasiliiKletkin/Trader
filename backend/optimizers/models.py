from decimal import Decimal

from core.utils.common import get_all_init_args
from core.utils.mixins import ActiveManagerMixin, TimeStampedMixin
from core.utils.types import OptimizerStatus, Timeframe
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from exchanges.domain import Timeframe as DomainTimeframe
from exchanges.models import Candle, Exchange, TradingPair
from optimizers.domain import TraderOptimizer as DomainTraderOptimizer
from optimizers.domain.base import AbstractOptimizationAlgorithm, OptimizerRegistry
from risk_managers.models import RiskManager
from strategies.models import Strategy


class TraderOptimizationAlgorithm(ActiveManagerMixin, TimeStampedMixin, models.Model):
    name = models.CharField(
        max_length=100,
        verbose_name="Название алгоритма оптимизации",
        unique=True,
    )
    class_name = models.CharField(
        max_length=100,
        choices=OptimizerRegistry.get_choices,
        verbose_name="Класс стратегии",
    )
    arguments = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Параметры (аргументы)",
    )

    class Meta:
        verbose_name = "Алгоритм оптимизации"
        verbose_name_plural = "Алгоритмы оптимизации"

    def __str__(self):
        return f"{self.name} ({self.class_name})"

    def save(self, *args, **kwargs):
        if not self.arguments:
            cls = self.get_class()
            self.arguments = get_all_init_args(cls)
        super().save(*args, **kwargs)

    def get_class(self) -> AbstractOptimizationAlgorithm:
        return OptimizerRegistry.get_class(self.class_name)

    def get_description(self) -> str:
        cls = self.get_class()
        return (cls.__doc__ or "").strip()

    def instantiate(self, **kwargs) -> AbstractOptimizationAlgorithm:
        cls = self.get_class()
        return cls(**self.arguments, **kwargs)


class TraderOptimizer(TimeStampedMixin, models.Model):
    status = models.CharField(
        max_length=10,
        choices=OptimizerStatus.choices,
        default=OptimizerStatus.ENABLED,
        verbose_name="Статус оптимизатора",
        help_text="Текущий статус оптимизатора трейдера.",
    )
    algorithm = models.ForeignKey(
        TraderOptimizationAlgorithm,
        on_delete=models.CASCADE,
        verbose_name="Алгоритм оптимизации",
        limit_choices_to={"is_active": True},
        help_text="Выберите алгоритм оптимизации для данного оптимизатора.",
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
        default=Timeframe.ONE_HOUR,
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

    class Meta:
        verbose_name = "Оптимизатор трейдера"
        verbose_name_plural = "Оптимизаторы трейдеров"
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "algorithm",
                    "exchange",
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
                name="unique_trader_optimizer",
            )
        ]

    def instantiate(self) -> DomainTraderOptimizer:
        return DomainTraderOptimizer(
            candles_iterator=(
                c.instantiate() for c in self.candles.order_by("timestamp").iterator()
            ),
            optimization_algorithm=self.algorithm.instantiate(),
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

    def __str__(self) -> str:
        return f"Optimizer {self.id} - {self.exchange.name} {self.trading_pair.symbol} {self.timeframe}"

    def optimize(self):
        if self.status == OptimizerStatus.REBOOTING:
            return

        self.status = OptimizerStatus.REBOOTING
        self.save(
            update_fields=[
                "status",
            ]
        )
        optimizer = self.instantiate()
        result = optimizer.optimize()

        self.status = OptimizerStatus.ENABLED
        self.save(
            update_fields=[
                "status",
            ]
        )

        TraderOptimizationResult.objects.create(
            optimizer=self,
            theoretical_profit=result.theoretical_profit,
            strategy_arguments=result.strategy_arguments,
            risk_manager_arguments=result.risk_manager_arguments,
        )


class TraderOptimizationResult(TimeStampedMixin, models.Model):
    optimizer = models.ForeignKey(
        TraderOptimizer,
        on_delete=models.CASCADE,
        verbose_name="Конфигурация оптимизации",
    )
    theoretical_profit = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        verbose_name="Теоретическая прибыль",
    )
    strategy_arguments = models.JSONField()
    risk_manager_arguments = models.JSONField()
    errors = models.TextField(
        blank=True,
        verbose_name="Ошибки",
        help_text="Лог ошибок, возникших во время оптимизации.",
    )

    class Meta:
        verbose_name = "Результат оптимизации"
        verbose_name_plural = "Результаты оптимизации"

    def __str__(self) -> str:
        return f"OptimizationResult {self.optimizer.id} - Profit {self.theoretical_profit} - Date {self.get_created_at_display()}"
