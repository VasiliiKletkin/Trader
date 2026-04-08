import traceback
from decimal import Decimal
from functools import cached_property

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from arbitrage_traders.domain import (
    ArbitrageTraderOptimizer as DomainArbitrageTraderOptimizer,
)
from arbitrage_traders.domain.optimizations.base import (
    AbstractOptimizationAlgorithm,
    ArbitrageOptimizerRegistry,
)
from arbitrage_traders.domain.risk_managers.base import ArbitrageRiskManagerRegistry
from arbitrage_traders.domain.schemas import ArbitrageCandle
from arbitrage_traders.domain.strategies.base import ArbitrageStrategyRegistry
from arbitrage_traders.schemas import (
    ArbitrageOptimizationPeriod,
    ArbitrageOptimizerStatus,
)
from candle_sources.models import CandleSource
from core.utils.common import get_all_init_args
from core.utils.mixins import ActiveManagerMixin, BaseErrorMixin, TimeStampedMixin
from exchanges.domain import Timeframe as DomainTimeframe
from exchanges.models import TradingPair
from exchanges.schemas import Timeframe


class ArbitrageOptimizationAlgorithm(
    ActiveManagerMixin, TimeStampedMixin, models.Model
):
    name = models.CharField(
        max_length=100,
        verbose_name="Название алгоритма оптимизации",
        unique=True,
    )
    class_name = models.CharField(
        max_length=100,
        choices=ArbitrageOptimizerRegistry.get_choices,
        verbose_name="Класс алгоритма оптимизации",
    )
    arguments = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Параметры (аргументы)",
    )

    class Meta:
        verbose_name = "Арбитражный алгоритм оптимизации"
        verbose_name_plural = "Арбитражные алгоритмы оптимизации"

    def __str__(self):
        return f"{self.name} ({self.class_name})"

    def save(self, *args, **kwargs):
        if not self.arguments:
            cls = self.get_class()
            self.arguments = get_all_init_args(cls)
        super().save(*args, **kwargs)

    def get_class(self) -> type[AbstractOptimizationAlgorithm]:
        return ArbitrageOptimizerRegistry.get_class(self.class_name)

    def get_description(self) -> str:
        cls = self.get_class()
        return (cls.__doc__ or "").strip()

    def instantiate(self, **kwargs) -> AbstractOptimizationAlgorithm:
        cls = self.get_class()
        return cls(**self.arguments, **kwargs)


class ArbitrageTraderOptimizer(TimeStampedMixin, models.Model):
    status = models.CharField(
        max_length=10,
        choices=ArbitrageOptimizerStatus.choices,
        default=ArbitrageOptimizerStatus.ENABLED,
        verbose_name="Статус оптимизатора",
    )
    algorithm = models.ForeignKey(
        ArbitrageOptimizationAlgorithm,
        on_delete=models.CASCADE,
        verbose_name="Алгоритм оптимизации",
        limit_choices_to={"is_active": True},
    )
    left_candle_source = models.ForeignKey(
        CandleSource,
        on_delete=models.CASCADE,
        related_name="arbitrage_optimizer_left",
        verbose_name="Первый источник свечей",
        limit_choices_to={"is_active": True},
    )
    right_candle_source = models.ForeignKey(
        CandleSource,
        on_delete=models.CASCADE,
        related_name="arbitrage_optimizer_right",
        verbose_name="Второй источник свечей",
        limit_choices_to={"is_active": True},
    )
    strategy_class_name = models.CharField(
        max_length=100,
        choices=ArbitrageStrategyRegistry.get_choices,
        verbose_name="Класс стратегии",
    )
    risk_manager_class_name = models.CharField(
        max_length=100,
        choices=ArbitrageRiskManagerRegistry.get_choices,
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
    lookback_period = models.CharField(
        max_length=5,
        verbose_name="Период оптимизации",
        choices=ArbitrageOptimizationPeriod.choices,
        default=ArbitrageOptimizationPeriod.ONE_WEEK,
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
        verbose_name = "Арбитражный оптимизатор трейдера"
        verbose_name_plural = "Арбитражные оптимизаторы трейдеров"
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "algorithm",
                    "left_candle_source",
                    "right_candle_source",
                    "strategy_class_name",
                    "risk_manager_class_name",
                    "initial_balance",
                    "max_positions_count",
                    "close_position_by_opposite_signal",
                    "close_position_by_strategy",
                    "lookback_period",
                    "roi_weight",
                    "r2_weight",
                    "sharpe_weight",
                    "win_rate_weight",
                ],
                name="unique_arbitrage_trader_optimizer",
            )
        ]

    def __str__(self) -> str:
        return f"Optimizer {self.pk} - {self.trading_pair} {self.timeframe}"

    @cached_property
    def timeframe(self) -> Timeframe:
        return Timeframe(self.left_candle_source.timeframe)

    @cached_property
    def trading_pair(self) -> TradingPair:
        return self.left_candle_source.trading_pair

    @cached_property
    def left_trading_pair(self) -> TradingPair:
        return self.left_candle_source.trading_pair

    @cached_property
    def right_trading_pair(self) -> TradingPair:
        return self.right_candle_source.trading_pair

    def get_candle_iterator(self):
        """Возвращает итератор арбитражных свечей за период lookback_period."""
        end_date = timezone.now()
        period = ArbitrageOptimizationPeriod(self.lookback_period).timedelta()
        start_date = end_date - period

        left_iterator = self.left_candle_source.get_candle_iterator(
            start=start_date, end=end_date
        )
        right_iterator = self.right_candle_source.get_candle_iterator(
            start=start_date, end=end_date
        )

        left_candle = next(left_iterator, None)
        right_candle = next(right_iterator, None)

        while left_candle and right_candle:
            if left_candle.timestamp == right_candle.timestamp:
                yield ArbitrageCandle(
                    left=left_candle.instantiate(),
                    right=right_candle.instantiate(),
                )
                left_candle = next(left_iterator, None)
                right_candle = next(right_iterator, None)
            elif left_candle.timestamp < right_candle.timestamp:
                left_candle = next(left_iterator, None)
            else:
                right_candle = next(right_iterator, None)

    def instantiate(self) -> DomainArbitrageTraderOptimizer:
        return DomainArbitrageTraderOptimizer(
            optimization_algorithm=self.algorithm.instantiate(),
            get_candle_iterator=self.get_candle_iterator,
            left_trading_pair=self.left_trading_pair.instantiate(
                exchange=self.left_candle_source.exchange,
            ),
            right_trading_pair=self.right_trading_pair.instantiate(
                exchange=self.right_candle_source.exchange,
            ),
            timeframe=DomainTimeframe(self.timeframe),
            strategy_class=ArbitrageStrategyRegistry.get_class(
                self.strategy_class_name,
            ),
            risk_manager_class=ArbitrageRiskManagerRegistry.get_class(
                self.risk_manager_class_name,
            ),
            initial_balance=self.initial_balance,
            max_positions_count=self.max_positions_count,
            close_position_by_strategy=self.close_position_by_strategy,
            close_position_by_opposite_signal=self.close_position_by_opposite_signal,
            roi_weight=self.roi_weight,
            r2_weight=self.r2_weight,
            sharpe_weight=self.sharpe_weight,
            win_rate_weight=self.win_rate_weight,
        )

    def optimize(self):
        if self.status == ArbitrageOptimizerStatus.REBOOTING:
            return

        self.status = ArbitrageOptimizerStatus.REBOOTING
        self.save(update_fields=["status"])
        try:
            optimizer = self.instantiate()
            result = optimizer.optimize()

            ArbitrageTraderOptimizationResult.objects.create(
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
        except Exception as e:
            self.status = ArbitrageOptimizerStatus.ERROR
            self.save(update_fields=["status"])
            self.errors.create(
                message=f"Ошибка при оптимизации: {e!s}",
                type=type(e).__name__,
                traceback=traceback.format_exc(),
            )
            return
        self.status = ArbitrageOptimizerStatus.ENABLED
        self.save(update_fields=["status"])


class ArbitrageTraderOptimizationResult(TimeStampedMixin, models.Model):
    optimizer = models.ForeignKey(
        ArbitrageTraderOptimizer,
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
        verbose_name = "Результат оптимизации (арбитраж)"
        verbose_name_plural = "Результаты оптимизации (арбитраж)"

    def __str__(self) -> str:
        return (
            f"OptimizationResult {self.optimizer_id} - "
            f"Profit {self.pnl} - Date {self.get_created_at_display()}"
        )


class ArbitrageTraderOptimizerError(BaseErrorMixin, TimeStampedMixin, models.Model):
    """Ошибки оптимизатора арбитражного трейдера."""

    optimizer = models.ForeignKey(
        ArbitrageTraderOptimizer,
        on_delete=models.CASCADE,
        related_name="errors",
        verbose_name="Оптимизатор",
    )

    class Meta:
        verbose_name = "Ошибка оптимизатора (арбитраж)"
        verbose_name_plural = "Ошибки оптимизатора (арбитраж)"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return super().__str__()
