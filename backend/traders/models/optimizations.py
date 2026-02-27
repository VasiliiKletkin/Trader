from datetime import timedelta
from decimal import Decimal
from functools import cached_property

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from candle_sources.models import CandleSource
from core.utils.common import get_all_init_args
from core.utils.mixins import ActiveManagerMixin, TimeStampedMixin
from exchanges.domain import Timeframe as DomainTimeframe
from exchanges.models import Exchange, TradingPair
from exchanges.schemas import Timeframe
from traders.domain import TraderOptimizer as DomainTraderOptimizer
from traders.domain.optimizations.base import (
    AbstractOptimizationAlgorithm,
    OptimizerRegistry,
)
from traders.domain.risk_managers.base import RiskManagerRegistry
from traders.domain.strategies.base import StrategyRegistry
from traders.schemas import OptimizerStatus


class TraderOptimizationAlgorithm(ActiveManagerMixin, TimeStampedMixin, models.Model):
    name = models.CharField(
        max_length=100,
        verbose_name="Название алгоритма оптимизации",
        unique=True,
    )
    class_name = models.CharField(
        max_length=100,
        choices=OptimizerRegistry.get_choices,
        verbose_name="Класс алгоритма оптимизации",
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

    def get_class(self) -> type[AbstractOptimizationAlgorithm]:
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
    )
    algorithm = models.ForeignKey(
        TraderOptimizationAlgorithm,
        on_delete=models.CASCADE,
        verbose_name="Алгоритм оптимизации",
        limit_choices_to={"is_active": True},
    )
    exchange = models.ForeignKey(
        Exchange,
        on_delete=models.CASCADE,
        verbose_name="Биржа",
        limit_choices_to={"is_active": True},
    )
    candle_source = models.ForeignKey(
        CandleSource,
        on_delete=models.CASCADE,
        verbose_name="Источник свечей",
        limit_choices_to={"is_active": True},
    )
    strategy_class_name = models.CharField(
        max_length=100,
        choices=StrategyRegistry.get_choices,
        verbose_name="Класс стратегии",
    )
    risk_manager_class_name = models.CharField(
        max_length=100,
        choices=RiskManagerRegistry.get_choices,
        verbose_name="Класс риск-менеджера",
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
    max_positions_count = models.PositiveSmallIntegerField(
        verbose_name="Макс. количество позиций",
        default=1,
        validators=[
            MinValueValidator(1),
            MaxValueValidator(100),
        ],
    )
    close_position_by_opposite_signal = models.BooleanField(
        default=True,
        verbose_name="Закрытие по противоположному сигналу",
    )
    close_position_by_strategy = models.BooleanField(
        default=True,
        verbose_name="Закрытие по стратегии",
    )
    close_position_by_stop_loss = models.BooleanField(
        default=True,
        verbose_name="Закрытие по Stop Loss",
    )
    close_position_by_take_profit = models.BooleanField(
        default=True,
        verbose_name="Закрытие по Take Profit",
    )
    trail_stop_enabled = models.BooleanField(
        default=True,
        verbose_name="Трейлинг-стоп",
    )
    roi_weight = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=Decimal("0.40"),
        verbose_name="Вес ROI",
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("1.00")),
        ],
    )
    r2_weight = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=Decimal("0.30"),
        verbose_name="Вес R²",
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("1.00")),
        ],
    )
    sharpe_weight = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=Decimal("0.20"),
        verbose_name="Вес Sharpe",
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("1.00")),
        ],
    )
    win_rate_weight = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=Decimal("0.10"),
        verbose_name="Вес Win Rate",
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("1.00")),
        ],
    )

    class Meta:
        verbose_name = "Оптимизатор трейдера"
        verbose_name_plural = "Оптимизаторы трейдеров"
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "algorithm",
                    "exchange",
                    "candle_source",
                    "strategy_class_name",
                    "risk_manager_class_name",
                    "initial_balance",
                    "max_positions_count",
                    "close_position_by_opposite_signal",
                    "close_position_by_strategy",
                    "close_position_by_stop_loss",
                    "close_position_by_take_profit",
                    "trail_stop_enabled",
                    "roi_weight",
                    "r2_weight",
                    "sharpe_weight",
                    "win_rate_weight",
                ],
                name="unique_trader_optimizer",
            )
        ]

    def __str__(self) -> str:
        return f"Optimizer {self.pk} - {self.exchange} {self.trading_pair} {self.timeframe}"

    def instantiate(self) -> DomainTraderOptimizer:
        end_date = timezone.now()
        start_date = end_date - timedelta(days=365)

        return DomainTraderOptimizer(
            start_date=start_date,
            end_date=end_date,
            optimization_algorithm=self.algorithm.instantiate(),
            candle_source=self.candle_source.instantiate(),
            trading_pair=self.trading_pair.instantiate(
                exchange=self.exchange,
            ),
            timeframe=DomainTimeframe(self.timeframe),
            strategy_class=StrategyRegistry.get_class(
                self.strategy_class_name,
            ),
            risk_manager_class=RiskManagerRegistry.get_class(
                self.risk_manager_class_name,
            ),
            initial_balance=self.initial_balance,
            max_positions_count=self.max_positions_count,
            trail_stop_enabled=self.trail_stop_enabled,
            close_position_by_stop_loss=self.close_position_by_stop_loss,
            close_position_by_take_profit=self.close_position_by_take_profit,
            close_position_by_strategy=self.close_position_by_strategy,
            close_position_by_opposite_signal=self.close_position_by_opposite_signal,
            roi_weight=self.roi_weight,
            r2_weight=self.r2_weight,
            sharpe_weight=self.sharpe_weight,
            win_rate_weight=self.win_rate_weight,
        )

    @cached_property
    def timeframe(self) -> Timeframe:
        return Timeframe(self.candle_source.timeframe)

    @cached_property
    def trading_pair(self) -> TradingPair:
        return self.candle_source.trading_pair

    def optimize(self):
        if self.status == OptimizerStatus.REBOOTING:
            return

        self.status = OptimizerStatus.REBOOTING
        self.save(
            update_fields=[
                "status",
            ]
        )
        try:
            optimizer = self.instantiate()
            result = optimizer.optimize()

            TraderOptimizationResult.objects.create(
                optimizer=self,
                pnl=result.pnl,
                win_rate=result.win_rate,
                avg_candles_per_position=result.avg_candles_per_position,
                pnl_r2=result.pnl_r2,
                roi=result.roi,
                sharpe=result.sharpe,
                total_positions=result.total_positions,
                strategy_arguments=result.strategy_arguments,
                risk_manager_arguments=result.risk_manager_arguments,
                duration=result.duration,
            )
        finally:
            self.status = OptimizerStatus.ENABLED
            self.save(
                update_fields=[
                    "status",
                ]
            )


class TraderOptimizationResult(TimeStampedMixin, models.Model):
    optimizer = models.ForeignKey(
        TraderOptimizer,
        on_delete=models.CASCADE,
        verbose_name="Конфигурация оптимизации",
    )
    duration = models.DurationField(
        verbose_name="Длительность оптимизации",
    )
    pnl = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        verbose_name="Теоретический PnL",
    )
    win_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        verbose_name="Процент побед (Win Rate)",
    )
    avg_candles_per_position = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="Среднее свечей на позицию",
    )
    pnl_r2 = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        verbose_name="R² для PnL",
    )
    roi = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        verbose_name="ROI",
    )
    sharpe = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        verbose_name="Sharpe Ratio",
    )
    total_positions = models.PositiveIntegerField(
        verbose_name="Количество позиций",
    )
    strategy_arguments = models.JSONField(
        verbose_name="Параметры стратегии",
    )
    risk_manager_arguments = models.JSONField(
        verbose_name="Параметры риск-менеджера",
    )

    class Meta:
        verbose_name = "Результат оптимизации"
        verbose_name_plural = "Результаты оптимизации"

    def __str__(self) -> str:
        return f"OptimizationResult {self.optimizer.id} - Profit {self.pnl} - Date {self.get_created_at_display()}"


class TraderOptimizerError(TimeStampedMixin, models.Model):
    """Ошибки оптимизатора трейдера."""

    optimizer = models.ForeignKey(
        TraderOptimizer,
        on_delete=models.CASCADE,
        verbose_name="Оптимизатор",
    )
    message = models.TextField(
        verbose_name="Сообщение об ошибке",
    )
    traceback = models.TextField(
        blank=True,
        default="",
        verbose_name="Трассировка ошибки",
    )
    type = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="Тип ошибки",
    )

    class Meta:
        verbose_name = "Ошибка оптимизатора"
        verbose_name_plural = "Ошибки оптимизатора"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.type} | {self.message}"
