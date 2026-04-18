import asyncio
import traceback
from collections import deque
from datetime import datetime, timedelta
from decimal import Decimal

import numpy as np
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.functions import Coalesce
from django.forms import ValidationError
from django.urls import reverse
from django.utils import timezone
from pydantic import BaseModel, ConfigDict

from arbitrage_traders.domain import ArbitrageCandle as DomainArbitrageCandle
from arbitrage_traders.domain import ArbitrageTrader as DomainArbitrageTrader
from arbitrage_traders.domain import ArbitrageTraderError as DomainArbitrageTraderError
from arbitrage_traders.domain import (
    ArbitrageTraderPosition as DomainArbitrageTraderPosition,
)
from arbitrage_traders.domain.schemas import (
    ArbitrageTraderSignal as DomainArbitrageTraderSignal,
)
from arbitrage_traders.domain.schemas import (
    PositionCloseReason as DomainPositionCloseReason,
)
from arbitrage_traders.domain.schemas import PositionStatus as DomainPositionStatus
from arbitrage_traders.domain.schemas import PositionType as DomainPositionType
from arbitrage_traders.domain.schemas import SignalType as DomainSignalType
from arbitrage_traders.domain.schemas import TraderStatus as DomainTraderStatus
from arbitrage_traders.schemas import (
    ArbitrageCandlesLookbackCount,
    ArbitragePositionCloseReason,
    ArbitragePositionStatus,
    ArbitragePositionType,
    ArbitrageSignalType,
    ArbitrageTraderStatus,
)
from candle_sources.models import CandleSource
from core.bus import get_bus_client
from core.utils.common import format_pnl
from core.utils.models import BaseErrorMixin, TimeStampedMixin
from exchange_clients.domain import ExchangeClientOrder as DomainExchangeClientOrder
from exchange_clients.domain.rpc.client import RPCExchangeClient
from exchange_clients.models import ExchangeClient, ExchangeClientOrder
from exchange_clients.schemas import OrderSide, OrderStatus
from exchanges.domain import Timeframe as DomainTimeframe
from exchanges.models import ExchangeCandle, ExchangeTradingPair, TradingPair
from exchanges.schemas import Timeframe
from telegram_bots.tasks import send_notification

from .risk_managers import ArbitrageRiskManager
from .strategies import ArbitrageStrategy


class ArbitrageExchangeCandle(BaseModel):
    """ORM-уровневая арбитражная свеча (пара ExchangeCandle)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    left: ExchangeCandle
    right: ExchangeCandle

    @property
    def spread(self) -> float | None:
        """Спред между биржами (коэффициент left/right)."""
        if self.right.close == 0:
            return None
        return float(self.left.close / self.right.close)

    def instantiate(self) -> DomainArbitrageCandle:
        return DomainArbitrageCandle(
            left=self.left.instantiate(),
            right=self.right.instantiate(),
        )


class ArbitrageTrader(TimeStampedMixin, models.Model):
    """Арбитражный трейдер с двумя клиентами бирж."""

    favorite = models.BooleanField(
        default=False,
        verbose_name="Избранный",
    )
    status = models.CharField(
        choices=ArbitrageTraderStatus.choices,
        default=ArbitrageTraderStatus.DISABLED,
        verbose_name="Статус",
    )
    left_candle_source = models.ForeignKey(
        CandleSource,
        on_delete=models.CASCADE,
        related_name="arbitrage_left_traders",
        verbose_name="Первый источник свечей",
    )
    right_candle_source = models.ForeignKey(
        CandleSource,
        on_delete=models.CASCADE,
        related_name="arbitrage_right_traders",
        verbose_name="Второй источник свечей",
    )
    left_exchange_client = models.ForeignKey(
        ExchangeClient,
        on_delete=models.CASCADE,
        related_name="arbitrage_left_traders",
        verbose_name="Первый клиент биржи",
        limit_choices_to={"is_active": True},
    )
    right_exchange_client = models.ForeignKey(
        ExchangeClient,
        on_delete=models.CASCADE,
        related_name="arbitrage_right_traders",
        verbose_name="Второй клиент биржи",
        limit_choices_to={"is_active": True},
    )
    strategy = models.ForeignKey(
        ArbitrageStrategy,
        on_delete=models.CASCADE,
        verbose_name="Стратегия",
        limit_choices_to={"is_active": True},
    )
    risk_manager = models.ForeignKey(
        ArbitrageRiskManager,
        on_delete=models.CASCADE,
        verbose_name="Риск-менеджер",
        limit_choices_to={"is_active": True},
    )
    use_fixed_balance = models.BooleanField(
        default=True,
        verbose_name="Фиксированный баланс",
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
    check_drawdown = models.BooleanField(
        default=True,
        verbose_name="Проверка просадки",
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
    )
    create_new_orders = models.BooleanField(
        default=True,
        verbose_name="Создавать ордера",
    )
    max_positions_count = models.PositiveSmallIntegerField(
        verbose_name="Макс. количество позиций",
        default=1,
        validators=[
            MinValueValidator(1),
            MaxValueValidator(100),
        ],
    )
    candles_lookback_count = models.PositiveSmallIntegerField(
        verbose_name="Макс. количество свечей",
        choices=ArbitrageCandlesLookbackCount.choices,
        default=ArbitrageCandlesLookbackCount.COUNT_1000,
    )
    close_position_by_opposite_signal = models.BooleanField(
        default=True,
        verbose_name="Закрытие по противоположному сигналу",
    )
    close_position_by_strategy = models.BooleanField(
        default=True,
        verbose_name="Закрытие по стратегии",
    )
    last_reboot = models.DateTimeField(  # type: ignore[misc]
        verbose_name="Последний перезапуск",
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "Арбитражный трейдер"
        verbose_name_plural = "Арбитражные трейдеры"
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "left_candle_source",
                    "right_candle_source",
                    "left_exchange_client",
                    "right_exchange_client",
                    "strategy",
                    "risk_manager",
                    "initial_balance",
                    "max_drawdown_pct",
                    "max_positions_count",
                    "close_position_by_opposite_signal",
                    "close_position_by_strategy",
                ],
                name="unique_arbitrage_trader",
            )
        ]

    # --- Meta, str, url ---

    def __str__(self) -> str:
        return (
            f"{self.get_status_display()} | {self.pk} | "
            f"{self.left_exchange_client} <-> {self.right_exchange_client} | "
            f"{self.strategy}"
        )

    def get_absolute_url(self):
        return reverse("arbitrage_trader_detail", kwargs={"pk": self.pk})

    # --- Свойства ---

    @property
    def is_ready(self) -> bool:
        return all(
            [
                self.left_candle_source.is_ready,
                self.right_candle_source.is_ready,
                self.left_exchange_client.is_ready,
                self.right_exchange_client.is_ready,
                self.strategy.is_ready,
                self.risk_manager.is_ready,
            ]
        )

    @property
    def timeframe(self) -> Timeframe:
        """Возвращает timeframe трейдера."""
        return Timeframe(self.left_candle_source.timeframe)

    @property
    def trading_pair(self) -> TradingPair | ExchangeTradingPair:
        """Возвращает торговую пару трейдера."""
        return self.left_candle_source.trading_pair

    # --- Валидация ---

    def clean(self) -> None:
        super().clean()
        for ec in (self.left_exchange_client, self.right_exchange_client):
            total = (
                ec.traders.count()
                + ec.arbitrage_left_traders.count()
                + ec.arbitrage_right_traders.count()
            )
            if total > 50:
                raise ValidationError(f"Нельзя более 50 трейдеров для клиента «{ec}».")
        if self.left_exchange_client.pk == self.right_exchange_client.pk:
            raise ValidationError("Первый и второй клиенты биржи должны быть разными.")
        if self.left_exchange_client.exchange == self.right_exchange_client.exchange:
            raise ValidationError("Клиенты должны быть на разных биржах.")
        if self.left_candle_source.exchange != self.left_exchange_client.exchange:
            raise ValidationError(
                "Биржа первого источника свечей должна совпадать с биржей первого клиента."
            )
        if self.right_candle_source.exchange != self.right_exchange_client.exchange:
            raise ValidationError(
                "Биржа второго источника свечей должна совпадать с биржей второго клиента."
            )
        if self.left_candle_source.timeframe != self.right_candle_source.timeframe:
            raise ValidationError("Таймфреймы источников свечей должны совпадать.")

    # --- Запросы позиций и ордеров ---

    def get_opened_positions(self) -> models.QuerySet["ArbitrageTraderPosition"]:
        """Возвращает открытые позиции."""
        return self.positions.filter(status=ArbitragePositionStatus.OPENED)

    def get_closed_positions(self) -> models.QuerySet["ArbitrageTraderPosition"]:
        """Возвращает закрытые позиции."""
        return self.positions.filter(status=ArbitragePositionStatus.CLOSED)

    @property
    def opened_positions(self) -> models.QuerySet["ArbitrageTraderPosition"]:
        """Свойство для доступа к открытым позициям."""
        return self.get_opened_positions()

    @property
    def closed_positions(self) -> models.QuerySet["ArbitrageTraderPosition"]:
        """Свойство для доступа к закрытым позициям."""
        return self.get_closed_positions()

    def get_total_positions_count(self) -> int:
        return self.positions.count()

    def get_total_positions_count_with_orders(self) -> int:
        return self.positions.filter(orders__isnull=False).distinct().count()

    def get_total_orders_count(self) -> int:
        return self.orders.count()

    # --- Запросы свечей ---

    def get_candle_iterator(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ):
        """Возвращает итератор ArbitrageExchangeCandle, сопоставляя по timestamp."""
        left_iterator = self.left_candle_source.get_candle_iterator(
            start=start, end=end
        )
        right_iterator = self.right_candle_source.get_candle_iterator(
            start=start, end=end
        )

        left_candle, right_candle = (
            next(left_iterator, None),
            next(right_iterator, None),
        )

        while left_candle and right_candle:
            if left_candle.timestamp == right_candle.timestamp:
                yield ArbitrageExchangeCandle(left=left_candle, right=right_candle)
                left_candle, right_candle = (
                    next(left_iterator, None),
                    next(right_iterator, None),
                )
            elif left_candle.timestamp < right_candle.timestamp:
                left_candle = next(left_iterator, None)
            elif left_candle.timestamp > right_candle.timestamp:
                right_candle = next(right_iterator, None)

    def get_candles(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[ArbitrageExchangeCandle]:
        """Получить свечи за диапазон дат, сопоставляя по timestamp."""
        return list(self.get_candle_iterator(start=start, end=end))

    def get_last_candle(
        self, lookup_window: int = 10
    ) -> ArbitrageExchangeCandle | None:
        """Получить последнюю синхронизированную пару свечей.

        Итерирует свечи обоих источников с конца (DESC) и возвращает
        первую пару с совпадающим timestamp.
        """
        lookup_window = 10
        left_iterator = self.left_candle_source.candles.order_by("-timestamp")[
            :lookup_window
        ].iterator()
        right_iterator = self.right_candle_source.candles.order_by("-timestamp")[
            :lookup_window
        ].iterator()

        left_candle, right_candle = (
            next(left_iterator, None),
            next(right_iterator, None),
        )

        while left_candle and right_candle:
            if left_candle.timestamp == right_candle.timestamp:
                return ArbitrageExchangeCandle(left=left_candle, right=right_candle)
            elif left_candle.timestamp > right_candle.timestamp:
                left_candle = next(left_iterator, None)
            else:
                right_candle = next(right_iterator, None)

        return None

    def get_last_candles(self, count: int = 1000) -> list[ArbitrageExchangeCandle]:
        """Получить последние N свечей, сопоставляя по timestamp.

        Итерирует свечи обоих источников с конца (DESC) и матчит
        по timestamp аналогично get_candle_iterator.
        """
        left_iterator = self.left_candle_source.candles.order_by("-timestamp")[
            : count * 2
        ].iterator()
        right_iterator = self.right_candle_source.candles.order_by("-timestamp")[
            : count * 2
        ].iterator()

        result: list[ArbitrageExchangeCandle] = []
        left_candle, right_candle = (
            next(left_iterator, None),
            next(right_iterator, None),
        )

        while left_candle and right_candle and len(result) < count:
            if left_candle.timestamp == right_candle.timestamp:
                result.append(
                    ArbitrageExchangeCandle(left=left_candle, right=right_candle)
                )
                left_candle, right_candle = (
                    next(left_iterator, None),
                    next(right_iterator, None),
                )
            elif left_candle.timestamp > right_candle.timestamp:
                left_candle = next(left_iterator, None)
            elif left_candle.timestamp < right_candle.timestamp:
                right_candle = next(right_iterator, None)

        result.reverse()
        return result

    # --- PnL аннотации и статистика ---

    @staticmethod
    def theoretical_pnl_annotation():
        """SQL-аннотация для теоретического PnL позиции (left + right)."""
        left_sign = models.Case(
            models.When(left_type=ArbitragePositionType.LONG, then=models.Value(1)),
            models.When(left_type=ArbitragePositionType.SHORT, then=models.Value(-1)),
            default=models.Value(0),
            output_field=models.SmallIntegerField(),
        )
        right_sign = models.Case(
            models.When(right_type=ArbitragePositionType.LONG, then=models.Value(1)),
            models.When(right_type=ArbitragePositionType.SHORT, then=models.Value(-1)),
            default=models.Value(0),
            output_field=models.SmallIntegerField(),
        )
        left_open_cost = Coalesce(
            "left_open_cost",
            models.F("left_open_price") * Coalesce("left_open_amount", "amount"),
        )
        left_close_cost = Coalesce(
            "left_close_cost",
            models.F("left_close_price") * Coalesce("left_close_amount", "amount"),
        )
        left_pnl = left_sign * (left_close_cost - left_open_cost) - models.F(
            "left_total_fee"
        )
        right_open_cost = Coalesce(
            "right_open_cost",
            models.F("right_open_price") * Coalesce("right_open_amount", "amount"),
        )
        right_close_cost = Coalesce(
            "right_close_cost",
            models.F("right_close_price") * Coalesce("right_close_amount", "amount"),
        )
        right_pnl = right_sign * (right_close_cost - right_open_cost) - models.F(
            "right_total_fee"
        )
        return left_pnl + right_pnl

    @staticmethod
    def fact_pnl_annotation():
        """SQL-аннотация для фактического PnL по ордерам (left + right)."""
        left_sign = models.Case(
            models.When(left_order__side=OrderSide.SELL, then=models.Value(1)),
            models.When(left_order__side=OrderSide.BUY, then=models.Value(-1)),
            default=models.Value(0),
            output_field=models.SmallIntegerField(),
        )
        right_sign = models.Case(
            models.When(right_order__side=OrderSide.SELL, then=models.Value(1)),
            models.When(right_order__side=OrderSide.BUY, then=models.Value(-1)),
            default=models.Value(0),
            output_field=models.SmallIntegerField(),
        )
        left_pnl = left_sign * models.F("left_order__cost") - models.F(
            "left_order__fee"
        )
        right_pnl = right_sign * models.F("right_order__cost") - models.F(
            "right_order__fee"
        )
        return left_pnl + right_pnl

    def get_win_rate(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> float:
        positions = self.closed_positions
        if start_date:
            positions = positions.filter(closed_at__gte=start_date)
        if end_date:
            positions = positions.filter(closed_at__lt=end_date)

        total = positions.count()
        if total == 0:
            return 0.0

        wins = (
            positions.annotate(computed_pnl=self.theoretical_pnl_annotation())
            .filter(computed_pnl__gt=0)
            .count()
        )
        return wins / total

    def get_avg_candles_per_position(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> float | None:
        positions = self.closed_positions
        if start_date:
            positions = positions.filter(closed_at__gte=start_date)
        if end_date:
            positions = positions.filter(closed_at__lt=end_date)

        avg_duration = positions.annotate(
            duration=models.F("closed_at") - models.F("opened_at"),
        ).aggregate(avg_duration=models.Avg("duration"))["avg_duration"]

        if avg_duration is None:
            return None
        return avg_duration / self.timeframe.timedelta()

    def get_balance(self, date: datetime | None = None) -> Decimal:
        """Возвращает текущий баланс трейдера."""
        if self.use_fixed_balance:
            return self.initial_balance
        return self.initial_balance + self.get_fact_pnl(end_date=date)

    def get_fact_pnl(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> Decimal:
        """Возвращает фактический PnL по ордерам."""
        positions = self.closed_positions
        if start_date:
            positions = positions.filter(closed_at__gte=start_date)
        if end_date:
            positions = positions.filter(closed_at__lt=end_date)

        orders = self.orders.filter(position__in=positions)
        result = orders.aggregate(pnl=models.Sum(self.fact_pnl_annotation()))
        return result["pnl"] or Decimal("0.00")

    def get_theoretical_pnl(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> Decimal:
        """Возвращает теоретический PnL по позициям без ордеров."""
        positions = self.closed_positions
        if start_date:
            positions = positions.filter(closed_at__gte=start_date)
        if end_date:
            positions = positions.filter(closed_at__lt=end_date)

        positions = positions.filter(orders__isnull=True)
        result = positions.aggregate(pnl=models.Sum(self.theoretical_pnl_annotation()))
        return result["pnl"] or Decimal("0.00")

    def get_pnl_r2(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> float:
        """
        Возвращает R² (коэффициент детерминации) для cumulative PnL.
        R² рассчитывается по линейной регрессии cumulative PnL
        по времени закрытия позиции.
        """
        closed_positions = self.closed_positions.order_by("closed_at")
        if start_date:
            closed_positions = closed_positions.filter(closed_at__gte=start_date)
        if end_date:
            closed_positions = closed_positions.filter(closed_at__lt=end_date)

        positions = list(
            closed_positions.annotate(
                computed_pnl=self.theoretical_pnl_annotation(),
            ).values("closed_at", "computed_pnl")
        )

        if len(positions) < 2:
            return 0.0

        cumulative_pnl = 0.0
        x_list: list[float] = []
        y_list: list[float] = []
        for pos in positions:
            cumulative_pnl += float(pos["computed_pnl"])
            x_list.append(pos["closed_at"].timestamp())
            y_list.append(cumulative_pnl)

        x_arr = np.array(x_list)
        y_arr = np.array(y_list)
        coeffs = np.polyfit(x_arr, y_arr, 1)
        slope, intercept = coeffs
        y_pred = slope * x_arr + intercept
        ss_res = np.sum((y_arr - y_pred) ** 2)
        ss_tot = np.sum((y_arr - np.mean(y_arr)) ** 2)
        return 1 - (ss_res / ss_tot) if ss_tot != 0 else 0.0

    # --- Domain ↔ ORM (sync/load/instantiate) ---

    def instantiate(self) -> DomainArbitrageTrader:
        """Создает domain объект ArbitrageTrader из ORM модели."""
        bus_client = get_bus_client(local=False)
        return DomainArbitrageTrader(
            left_trading_pair=self.trading_pair.instantiate(
                exchange=self.left_exchange_client.exchange
            ),
            right_trading_pair=self.trading_pair.instantiate(
                exchange=self.right_exchange_client.exchange
            ),
            timeframe=DomainTimeframe(self.timeframe),
            left_exchange_client=RPCExchangeClient(
                id=self.left_exchange_client_id,
                bus_client=bus_client,
                exchange=self.left_exchange_client.exchange.instantiate(),
            ),
            right_exchange_client=RPCExchangeClient(
                id=self.right_exchange_client_id,
                bus_client=bus_client,
                exchange=self.right_exchange_client.exchange.instantiate(),
            ),
            strategy=self.strategy.instantiate(),
            risk_manager=self.risk_manager.instantiate(),
            use_fixed_balance=self.use_fixed_balance,
            initial_balance=self.initial_balance,
            balance=self.get_balance(),
            check_drawdown=self.check_drawdown,
            max_drawdown_pct=self.max_drawdown_pct,
            max_positions_count=self.max_positions_count,
            candles_lookback_count=self.candles_lookback_count,
            create_new_orders=self.create_new_orders,
            close_position_by_strategy=self.close_position_by_strategy,
            close_position_by_opposite_signal=self.close_position_by_opposite_signal,
            status=DomainTraderStatus(self.status),
        )

    def load(self, trader: DomainArbitrageTrader) -> None:
        """Загружает состояние domain трейдера из базы данных."""
        candles = self.get_last_candles(count=self.candles_lookback_count)
        trader.candles = deque(
            (candle.instantiate() for candle in candles),
            maxlen=self.candles_lookback_count,
        )
        trader.positions = [
            pos.instantiate() for pos in self.opened_positions.order_by("opened_at")
        ]

    def sync_signals(self, trader: DomainArbitrageTrader) -> None:
        """Сохраняет новые сигналы в базу данных."""
        if not trader.signals:
            return

        new_signals = [signal for signal in trader.signals if not signal.id]

        if not new_signals:
            return

        trader_signals = []
        for signal in new_signals:
            trader_signals.append(
                ArbitrageTraderSignal(
                    trader=self,
                    timestamp=signal.timestamp,
                    left_price=signal.left_price,
                    right_price=signal.right_price,
                    left_type=ArbitrageSignalType(signal.left_type),
                    right_type=ArbitrageSignalType(signal.right_type),
                    left_candle_id=signal.left_candle.id,
                    right_candle_id=signal.right_candle.id,
                    data=signal.data,
                )
            )

        ArbitrageTraderSignal.objects.bulk_create(
            trader_signals, batch_size=settings.BULK_BATCH_SIZE
        )

    def sync_positions(self, trader: DomainArbitrageTrader) -> None:
        """Сохраняет позиции в базу данных."""
        if not trader.positions:
            return
        positions = [
            ArbitrageTraderPosition(
                trader=self,
                left_type=ArbitragePositionType(position.left_type),
                right_type=ArbitragePositionType(position.right_type),
                status=ArbitragePositionStatus(position.status),
                amount=position.amount,
                left_open_price=position.left_open_price,
                left_close_price=position.left_close_price,
                right_open_price=position.right_open_price,
                right_close_price=position.right_close_price,
                left_open_amount=position.left_open_amount,
                left_close_amount=position.left_close_amount,
                right_open_amount=position.right_open_amount,
                right_close_amount=position.right_close_amount,
                left_open_cost=position.left_open_cost,
                left_close_cost=position.left_close_cost,
                right_open_cost=position.right_open_cost,
                right_close_cost=position.right_close_cost,
                opened_at=position.opened_at,
                closed_at=position.closed_at,
                close_reason=(
                    ArbitragePositionCloseReason(position.close_reason)
                    if position.close_reason
                    else ""
                ),
                left_total_fee=position.left_total_fee,
                right_total_fee=position.right_total_fee,
            )
            for position in trader.positions
        ]

        ArbitrageTraderPosition.objects.bulk_create(
            positions,
            update_conflicts=True,
            update_fields=[
                "status",
                "left_open_price",
                "left_close_price",
                "right_open_price",
                "right_close_price",
                "left_open_amount",
                "left_close_amount",
                "right_open_amount",
                "right_close_amount",
                "left_open_cost",
                "left_close_cost",
                "right_open_cost",
                "right_close_cost",
                "closed_at",
                "close_reason",
                "left_total_fee",
                "right_total_fee",
            ],
            unique_fields=[
                "trader",
                "opened_at",
                "amount",
                "left_type",
                "right_type",
            ],
            batch_size=settings.BULK_BATCH_SIZE,
        )

    def sync_orders(self, trader: DomainArbitrageTrader) -> None:
        """Сохраняет ордера в базу данных."""
        if not trader.orders:
            return

        # Создаем ExchangeClientOrder для обоих exchange_client
        left_exchange_client_orders = []
        right_exchange_client_orders = []

        for left_order, right_order, _ in trader.orders:
            left_exchange_client_orders.append(
                ExchangeClientOrder(
                    exchange_client=self.left_exchange_client,
                    status=OrderStatus(left_order.status),
                    exchange_order_id=left_order.exchange_order_id,
                    trading_pair=self.trading_pair,  # type: ignore[misc]
                    side=OrderSide(left_order.side),
                    timestamp=left_order.timestamp,
                    amount=left_order.amount,
                    price=left_order.price,
                    cost=left_order.cost,
                    fee=left_order.fee,
                )
            )
            right_exchange_client_orders.append(
                ExchangeClientOrder(
                    exchange_client=self.right_exchange_client,
                    status=OrderStatus(right_order.status),
                    exchange_order_id=right_order.exchange_order_id,
                    trading_pair=self.trading_pair,  # type: ignore[misc]
                    side=OrderSide(right_order.side),
                    timestamp=right_order.timestamp,
                    amount=right_order.amount,
                    price=right_order.price,
                    cost=right_order.cost,
                    fee=right_order.fee,
                )
            )

        ExchangeClientOrder.objects.bulk_create(
            left_exchange_client_orders, batch_size=settings.BULK_BATCH_SIZE
        )
        ExchangeClientOrder.objects.bulk_create(
            right_exchange_client_orders, batch_size=settings.BULK_BATCH_SIZE
        )

        # Получаем созданные ордера
        left_client_orders = ExchangeClientOrder.objects.filter(
            exchange_client=self.left_exchange_client,
            trading_pair=self.trading_pair,  # type: ignore[misc]
            exchange_order_id__in=[o[0].exchange_order_id for o in trader.orders],
        )
        right_client_orders = ExchangeClientOrder.objects.filter(
            exchange_client=self.right_exchange_client,
            trading_pair=self.trading_pair,  # type: ignore[misc]
            exchange_order_id__in=[o[1].exchange_order_id for o in trader.orders],
        )

        # Создаем map для быстрого поиска
        left_orders_map = {o.exchange_order_id: o for o in left_client_orders}
        right_orders_map = {o.exchange_order_id: o for o in right_client_orders}

        # Получаем позиции
        position_keys = [
            (
                pos.opened_at,
                pos.amount,
                ArbitragePositionType(pos.left_type),
                ArbitragePositionType(pos.right_type),
            )
            for _, _, pos in trader.orders
        ]
        orm_positions = list(
            self.positions.filter(
                models.Q(
                    *[
                        models.Q(
                            opened_at=opened_at,
                            amount=amount,
                            left_type=left_type,
                            right_type=right_type,
                        )
                        for opened_at, amount, left_type, right_type in position_keys
                    ],
                    _connector=models.Q.OR,
                )
            )
        )

        orm_positions_map = {
            (pos.opened_at, pos.amount, pos.left_type, pos.right_type): pos
            for pos in orm_positions
        }

        # Создаем ArbitrageTraderOrder
        trader_orders = []
        for left_order, right_order, position in trader.orders:
            key = (
                position.opened_at,
                position.amount,
                ArbitragePositionType(position.left_type),
                ArbitragePositionType(position.right_type),
            )
            orm_pos = orm_positions_map.get(key)

            if orm_pos:
                left_order_obj = left_orders_map.get(left_order.exchange_order_id)
                right_order_obj = right_orders_map.get(right_order.exchange_order_id)

                if left_order_obj and right_order_obj:
                    trader_orders.append(
                        ArbitrageTraderOrder(
                            trader=self,
                            left_order=left_order_obj,
                            right_order=right_order_obj,
                            position=orm_pos,
                        )
                    )

        ArbitrageTraderOrder.objects.bulk_create(
            trader_orders,
            ignore_conflicts=True,
            batch_size=settings.BULK_BATCH_SIZE,
        )

    def sync_errors(self, trader: DomainArbitrageTrader) -> None:
        """Сохраняет ошибки domain трейдера в базу данных."""
        new_errors = [error for error in trader.errors if not error.id]
        if not new_errors:
            return

        error_messages = "\n".join(
            f"{error.timestamp}: {error.type}: {error.message}" for error in new_errors
        )
        send_notification.delay(
            message=f"Арбитражный трейдер {self.pk} столкнулся с ошибками:\n{error_messages}"
        )

        ArbitrageTraderError.objects.bulk_create(
            [
                ArbitrageTraderError(
                    trader=self,
                    message=error.message,
                    traceback=error.traceback,
                    type=error.type,
                )
                for error in new_errors
            ],
            batch_size=settings.BULK_BATCH_SIZE,
        )

        self.status = ArbitrageTraderStatus.ERROR
        self.save(update_fields=["status"])

    def sync(self, trader: DomainArbitrageTrader) -> None:
        """Синхронизирует состояние domain трейдера с базой данных."""
        self.sync_signals(trader=trader)
        self.sync_positions(trader=trader)
        self.sync_orders(trader=trader)
        self.sync_errors(trader=trader)

    # --- Управление состоянием ---

    def enable(self):
        self.status = ArbitrageTraderStatus.ENABLED
        self.save(update_fields=["status"])

    def disable(self):
        self.status = ArbitrageTraderStatus.DISABLED
        self.save(update_fields=["status"])

    def _set_clearing_status(self) -> str:
        """Ставит CLEARING и возвращает предыдущий статус."""
        previous_status = self.status
        self.status = ArbitrageTraderStatus.CLEARING
        self.save(update_fields=["status"])
        return previous_status

    def _restore_status(self, previous_status: str) -> None:
        self.status = previous_status
        self.save(update_fields=["status"])

    def clear_all_errors(self) -> None:
        previous_status = self._set_clearing_status()
        try:
            self.errors.all().delete()
            self._restore_status(previous_status)
        except Exception as e:
            self.status = ArbitrageTraderStatus.ERROR
            self.save(update_fields=["status"])
            self.errors.create(
                message=f"Ошибка при очистке ошибок: {e!s}",
                type=type(e).__name__,
                traceback=traceback.format_exc(),
            )

    def clear_all_data(self) -> None:
        previous_status = self._set_clearing_status()
        try:
            self.signals.all().delete()
            self.orders.all().delete()
            self.positions.all().delete()
            self.errors.all().delete()
            self._restore_status(previous_status)
        except Exception as e:
            self.status = ArbitrageTraderStatus.ERROR
            self.save(update_fields=["status"])
            self.errors.create(
                message=f"Ошибка при очистке данных: {e!s}",
                type=type(e).__name__,
                traceback=traceback.format_exc(),
            )

    # --- Торговый цикл ---

    def has_existing_signal(self, timestamp: datetime) -> bool:
        return self.signals.filter(timestamp__gte=timestamp).exists()

    def handle_candle(
        self,
        left_candle: ExchangeCandle,
        right_candle: ExchangeCandle,
    ) -> None:
        trader = self.instantiate()
        self.load(trader=trader)

        candle = DomainArbitrageCandle(
            left=left_candle.instantiate(),
            right=right_candle.instantiate(),
        )

        asyncio.run(trader.handle_candle(candle))
        self.sync(trader=trader)

    def close_all_opened_positions(self) -> None:
        trader = self.instantiate()
        self.load(trader=trader)

        asyncio.run(trader.close_all_opened_positions())
        self.sync(trader=trader)

    def close_position(self, position: "ArbitrageTraderPosition") -> None:
        """Закрывает одну открытую позицию вручную (reason=MANUAL)."""
        if position.status == ArbitragePositionStatus.CLOSED:
            raise ValueError(f"Позиция #{position.pk} уже закрыта")

        trader = self.instantiate()
        self.load(trader=trader)

        domain_position = next(
            (p for p in trader.positions if p.id == position.pk),
            None,
        )
        if domain_position is None:
            raise ValueError(
                f"Открытая позиция #{position.pk} не найдена у трейдера #{self.pk}"
            )

        if not trader.candles:
            raise ValueError(
                f"Нет свечей для трейдера #{self.pk} — невозможно закрыть позицию"
            )

        last_candle = trader.candles[-1]
        signal = DomainArbitrageTraderSignal(
            timestamp=timezone.now(),
            left_type=DomainSignalType.WAIT,
            right_type=DomainSignalType.WAIT,
            left_price=last_candle.left.close,
            right_price=last_candle.right.close,
            left_candle=last_candle.left,
            right_candle=last_candle.right,
        )

        asyncio.run(
            trader.close_position(
                position=domain_position,
                signal=signal,
                reason=DomainPositionCloseReason.MANUAL,
            )
        )
        self.sync(trader=trader)

    def reboot(self) -> None:
        """Перезапускает арбитражного трейдера на исторических данных."""
        end_date = timezone.now()
        start_date = end_date - timedelta(days=365)

        if self.status == ArbitrageTraderStatus.REBOOTING:
            return

        try:
            self.clear_all_data()
            self.last_reboot = timezone.now()
            self.status = ArbitrageTraderStatus.REBOOTING
            self.save(update_fields=["status", "last_reboot"])

            trader = self.instantiate()
            candle_iterator = (
                c.instantiate()
                for c in self.get_candle_iterator(
                    start=start_date,
                    end=end_date,
                )
            )

            asyncio.run(trader.reboot(candle_iterator=candle_iterator))
            self.sync(trader=trader)
        except Exception as e:
            self.status = ArbitrageTraderStatus.ERROR
            self.errors.create(
                message=f"Ошибка при перезапуске трейдера: {e!s}",
                type=type(e).__name__,
                traceback=traceback.format_exc(),
            )
        except BaseException:
            self.status = ArbitrageTraderStatus.ERROR
        else:
            self.status = ArbitrageTraderStatus.PAUSED
        finally:
            self.save(update_fields=["status", "last_reboot"])


class ArbitrageTraderError(BaseErrorMixin, TimeStampedMixin, models.Model):
    """Ошибки арбитражного трейдера."""

    trader = models.ForeignKey(
        ArbitrageTrader,
        on_delete=models.CASCADE,
        related_name="errors",
        verbose_name="Арбитражный трейдер",
    )

    class Meta:
        verbose_name = "Арбитражная ошибка трейдера"
        verbose_name_plural = "Арбитражные ошибки трейдера"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return super().__str__()

    def instantiate(self) -> DomainArbitrageTraderError:
        """Возвращает domain модель ArbitrageTraderError."""
        return DomainArbitrageTraderError(
            id=self.pk,
            timestamp=self.created_at,
            message=self.message,
            type=self.type,
            traceback=self.traceback,
        )


class ArbitrageTraderSignal(models.Model):
    trader = models.ForeignKey(
        ArbitrageTrader,
        on_delete=models.CASCADE,
        related_name="signals",
        verbose_name="Арбитражный трейдер",
    )
    timestamp = models.DateTimeField(
        verbose_name="Время сигнала",
    )
    left_price = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        verbose_name="Цена (первая биржа)",
    )
    right_price = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        verbose_name="Цена (вторая биржа)",
    )
    left_type = models.CharField(
        max_length=10,
        choices=ArbitrageSignalType.choices,
        verbose_name="Тип (первая биржа)",
    )
    right_type = models.CharField(
        max_length=10,
        choices=ArbitrageSignalType.choices,
        verbose_name="Тип (вторая биржа)",
    )
    left_candle = models.ForeignKey(
        ExchangeCandle,
        on_delete=models.CASCADE,
        related_name="arbitrage_left_signals",
        verbose_name="Первая свеча",
    )
    right_candle = models.ForeignKey(
        ExchangeCandle,
        on_delete=models.CASCADE,
        related_name="arbitrage_right_signals",
        verbose_name="Вторая свеча",
    )

    data = models.JSONField()

    class Meta:
        verbose_name = "Арбитражный сигнал трейдера"
        verbose_name_plural = "Арбитражные сигналы трейдера"
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "trader",
                    "timestamp",
                    "left_type",
                    "right_type",
                ],
                name="unique_arb_trader_signal",
            )
        ]

    def __str__(self) -> str:
        return (
            f"{self.trader.pk} | {self.get_left_type_display()}/{self.get_right_type_display()} | "
            f"{self.timestamp}"
        )

    def instantiate(self) -> DomainArbitrageTraderSignal:
        """Возвращает domain модель ArbitrageTraderSignal."""
        return DomainArbitrageTraderSignal(
            id=self.pk,
            timestamp=self.timestamp,
            left_type=DomainSignalType(self.left_type),
            right_type=DomainSignalType(self.right_type),
            left_price=self.left_price,
            right_price=self.right_price,
            left_candle=self.left_candle.instantiate(),
            right_candle=self.right_candle.instantiate(),
            data=self.data,
        )


class ArbitrageTraderPosition(TimeStampedMixin, models.Model):
    trader = models.ForeignKey(
        ArbitrageTrader,
        on_delete=models.CASCADE,
        related_name="positions",
        verbose_name="Арбитражный трейдер",
    )
    left_type = models.CharField(
        max_length=10,
        choices=ArbitragePositionType.choices,
        verbose_name="Тип позиции (первая биржа)",
    )
    right_type = models.CharField(
        max_length=10,
        choices=ArbitragePositionType.choices,
        verbose_name="Тип позиции (вторая биржа)",
    )
    status = models.CharField(
        max_length=10,
        choices=ArbitragePositionStatus.choices,
        default=ArbitragePositionStatus.OPENED,
        verbose_name="Статус позиции",
    )
    amount = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        verbose_name="Количество актива",
    )
    left_open_price = models.DecimalField(  # type: ignore[misc]
        max_digits=30,
        decimal_places=18,
        null=True,
        blank=True,
        verbose_name="Цена открытия (первая биржа)",
    )
    left_close_price = models.DecimalField(  # type: ignore[misc]
        max_digits=30,
        decimal_places=18,
        null=True,
        blank=True,
        verbose_name="Цена закрытия (первая биржа)",
    )
    right_open_price = models.DecimalField(  # type: ignore[misc]
        max_digits=30,
        decimal_places=18,
        null=True,
        blank=True,
        verbose_name="Цена открытия (вторая биржа)",
    )
    right_close_price = models.DecimalField(  # type: ignore[misc]
        max_digits=30,
        decimal_places=18,
        null=True,
        blank=True,
        verbose_name="Цена закрытия (вторая биржа)",
    )
    left_open_amount = models.DecimalField(  # type: ignore[misc]
        max_digits=30,
        decimal_places=18,
        null=True,
        blank=True,
        verbose_name="Кол-во открытия (первая биржа)",
    )
    left_close_amount = models.DecimalField(  # type: ignore[misc]
        max_digits=30,
        decimal_places=18,
        null=True,
        blank=True,
        verbose_name="Кол-во закрытия (первая биржа)",
    )
    right_open_amount = models.DecimalField(  # type: ignore[misc]
        max_digits=30,
        decimal_places=18,
        null=True,
        blank=True,
        verbose_name="Кол-во открытия (вторая биржа)",
    )
    right_close_amount = models.DecimalField(  # type: ignore[misc]
        max_digits=30,
        decimal_places=18,
        null=True,
        blank=True,
        verbose_name="Кол-во закрытия (вторая биржа)",
    )
    left_open_cost = models.DecimalField(  # type: ignore[misc]
        max_digits=30,
        decimal_places=18,
        null=True,
        blank=True,
        verbose_name="Стоимость открытия (первая биржа)",
    )
    left_close_cost = models.DecimalField(  # type: ignore[misc]
        max_digits=30,
        decimal_places=18,
        null=True,
        blank=True,
        verbose_name="Стоимость закрытия (первая биржа)",
    )
    right_open_cost = models.DecimalField(  # type: ignore[misc]
        max_digits=30,
        decimal_places=18,
        null=True,
        blank=True,
        verbose_name="Стоимость открытия (вторая биржа)",
    )
    right_close_cost = models.DecimalField(  # type: ignore[misc]
        max_digits=30,
        decimal_places=18,
        null=True,
        blank=True,
        verbose_name="Стоимость закрытия (вторая биржа)",
    )
    opened_at = models.DateTimeField(  # type: ignore[misc]
        null=True,
        blank=True,
        verbose_name="Время открытия",
    )
    closed_at = models.DateTimeField(  # type: ignore[misc]
        null=True,
        blank=True,
        verbose_name="Время закрытия",
    )
    close_reason = models.CharField(
        max_length=20,
        blank=True,
        default="",
        choices=ArbitragePositionCloseReason.choices,
        verbose_name="Причина закрытия",
    )
    left_total_fee = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        default=Decimal("0.00"),
        verbose_name="Комиссия (первая биржа)",
    )
    right_total_fee = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        default=Decimal("0.00"),
        verbose_name="Комиссия (вторая биржа)",
    )

    class Meta:
        verbose_name = "Арбитражная позиция трейдера"
        verbose_name_plural = "Арбитражные позиции трейдера"
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "trader",
                    "opened_at",
                    "amount",
                    "left_type",
                    "right_type",
                ],
                name="unique_arbitrage_position",
            )
        ]

    def __str__(self) -> str:
        position = self.instantiate()
        pnl = position.pnl
        pnl_str = format_pnl(pnl) if pnl is not None else "N/A"
        return f"{self.get_status_display()} | PNL:{pnl_str}"

    def instantiate(self) -> DomainArbitrageTraderPosition:
        return DomainArbitrageTraderPosition(
            id=self.pk,
            left_type=DomainPositionType(self.left_type),
            right_type=DomainPositionType(self.right_type),
            status=DomainPositionStatus(self.status),
            amount=self.amount,
            left_open_price=self.left_open_price,
            left_close_price=self.left_close_price,
            right_open_price=self.right_open_price,
            right_close_price=self.right_close_price,
            left_open_amount=self.left_open_amount,
            left_close_amount=self.left_close_amount,
            right_open_amount=self.right_open_amount,
            right_close_amount=self.right_close_amount,
            left_open_cost=self.left_open_cost,
            left_close_cost=self.left_close_cost,
            right_open_cost=self.right_open_cost,
            right_close_cost=self.right_close_cost,
            opened_at=self.opened_at,
            closed_at=self.closed_at,
            close_reason=(
                DomainPositionCloseReason(self.close_reason)
                if self.close_reason
                else None
            ),
            left_total_fee=self.left_total_fee,
            right_total_fee=self.right_total_fee,
        )

    @property
    def total_fee(self) -> Decimal:
        """Общая комиссия по обеим биржам."""
        return self.instantiate().total_fee

    @property
    def pnl(self) -> Decimal | None:
        """Profit and Loss."""
        return self.instantiate().pnl

    @property
    def pnl_pct(self) -> Decimal | None:
        """Profit and Loss Percentage."""
        return self.instantiate().pnl_pct

    @property
    def is_closed(self) -> bool:
        return self.instantiate().is_closed

    def refresh(self) -> None:
        """Пересчитывает позицию по данным ордеров.

        Каждый ArbitrageTraderOrder содержит left_order и right_order.
        По side определяем: open или close ордер.
        Если ордера нет — записывает None.
        """
        orders = self.orders.select_related("left_order", "right_order")
        if not orders.exists():
            return

        left_open_side = (
            OrderSide.BUY
            if self.left_type == ArbitragePositionType.LONG
            else OrderSide.SELL
        )
        right_open_side = (
            OrderSide.BUY
            if self.right_type == ArbitragePositionType.LONG
            else OrderSide.SELL
        )

        left_open = None
        left_close = None
        right_open = None
        right_close = None
        left_total_fee = Decimal("0")
        right_total_fee = Decimal("0")

        for order in orders:
            lo = order.left_order
            ro = order.right_order

            if lo.side == left_open_side:
                left_open = lo
            else:
                left_close = lo

            if ro.side == right_open_side:
                right_open = ro
            else:
                right_close = ro

            left_total_fee += lo.fee
            right_total_fee += ro.fee

        self.left_open_price = left_open.price if left_open else None
        self.left_open_amount = left_open.amount if left_open else None
        self.left_open_cost = left_open.cost if left_open else None
        self.left_close_price = left_close.price if left_close else None
        self.left_close_amount = left_close.amount if left_close else None
        self.left_close_cost = left_close.cost if left_close else None

        self.right_open_price = right_open.price if right_open else None
        self.right_open_amount = right_open.amount if right_open else None
        self.right_open_cost = right_open.cost if right_open else None
        self.right_close_price = right_close.price if right_close else None
        self.right_close_amount = right_close.amount if right_close else None
        self.right_close_cost = right_close.cost if right_close else None

        self.left_total_fee = left_total_fee
        self.right_total_fee = right_total_fee

        self.save(
            update_fields=[
                "left_open_price",
                "left_close_price",
                "right_open_price",
                "right_close_price",
                "left_open_amount",
                "left_close_amount",
                "right_open_amount",
                "right_close_amount",
                "left_open_cost",
                "left_close_cost",
                "right_open_cost",
                "right_close_cost",
                "left_total_fee",
                "right_total_fee",
            ],
        )


class ArbitrageTraderOrder(TimeStampedMixin, models.Model):
    """Ордера арбитражного трейдера."""

    trader = models.ForeignKey(
        ArbitrageTrader,
        on_delete=models.CASCADE,
        related_name="orders",
        verbose_name="Арбитражный трейдер",
    )
    left_order = models.OneToOneField(
        ExchangeClientOrder,
        on_delete=models.CASCADE,
        related_name="arbitrage_trader_left_order",
        verbose_name="Первый ордер",
    )
    right_order = models.OneToOneField(
        ExchangeClientOrder,
        on_delete=models.CASCADE,
        related_name="arbitrage_trader_right_order",
        verbose_name="Второй ордер",
    )
    position = models.ForeignKey(
        ArbitrageTraderPosition,
        on_delete=models.CASCADE,
        related_name="orders",
        verbose_name="Позиция трейдера",
    )

    class Meta:
        verbose_name = "Ордер арбитражного трейдера"
        verbose_name_plural = "Ордера арбитражного трейдера"
        constraints = [
            models.UniqueConstraint(
                fields=["trader", "left_order", "right_order", "position"],
                name="unique_arbitrage_trader_order",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.trader} | "
            f"First: {self.left_order.side} {self.left_order.amount} @ {self.left_order.price} | "
            f"Second: {self.right_order.side} {self.right_order.amount} @ {self.right_order.price}"
        )

    def clean(self) -> None:
        super().clean()

        if self.position and self.position.trader.pk != self.trader.pk:
            raise ValidationError(
                "Позиция должна принадлежать тому же арбитражному трейдеру."
            )

    def instantiate(
        self,
    ) -> tuple[DomainExchangeClientOrder, DomainExchangeClientOrder]:
        """Возвращает tuple из двух domain ордеров."""
        return (self.left_order.instantiate(), self.right_order.instantiate())
