import asyncio
import traceback
from collections import deque
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import zip_longest

import numpy as np
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.forms import ValidationError
from django.urls import reverse
from django.utils import timezone

from arbitrage_traders.domain import ArbitrageCandle as DomainArbitrageCandle
from arbitrage_traders.domain import ArbitrageTrader as DomainArbitrageTrader
from arbitrage_traders.domain import ArbitrageTraderError as DomainArbitrageTraderError
from arbitrage_traders.domain import (
    ArbitrageTraderPosition as DomainArbitrageTraderPosition,
)
from arbitrage_traders.domain.exceptions import CandleDesyncError
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
    ArbitragePositionCloseReason,
    ArbitragePositionStatus,
    ArbitragePositionType,
    ArbitrageSignalType,
    ArbitrageTraderStatus,
)
from candle_sources.models import CandleSource
from core.utils.mixins import TimeStampedMixin
from exchange_clients.domain import AbstractExchangeClient
from exchange_clients.domain import ExchangeClientOrder as DomainExchangeClientOrder
from exchange_clients.models import ExchangeClient, ExchangeClientOrder
from exchange_clients.schemas import OrderSide, OrderStatus
from exchanges.domain import Timeframe as DomainTimeframe
from exchanges.models import ExchangeCandle, ExchangeTradingPair, TradingPair
from exchanges.schemas import Timeframe
from telegram_bots.tasks import send_notification

from .risk_managers import ArbitrageRiskManager
from .strategies import ArbitrageStrategy


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
        limit_choices_to={"is_active": True},
    )
    right_candle_source = models.ForeignKey(
        CandleSource,
        on_delete=models.CASCADE,
        related_name="arbitrage_right_traders",
        verbose_name="Второй источник свечей",
        limit_choices_to={"is_active": True},
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

    def __str__(self) -> str:
        return (
            f"{self.get_status_display()} | {self.pk} | "
            f"{self.left_exchange_client} <-> {self.right_exchange_client} | "
            f"{self.strategy}"
        )

    def get_absolute_url(self):
        return reverse("arbitrage_trader_detail", kwargs={"pk": self.pk})

    @property
    def timeframe(self) -> Timeframe:
        """Возвращает timeframe трейдера."""
        return Timeframe(self.left_candle_source.timeframe)

    @property
    def trading_pair(self) -> TradingPair | ExchangeTradingPair:
        """Возвращает торговую пару трейдера."""
        return self.left_candle_source.trading_pair

    def clean(self) -> None:
        super().clean()
        if self.left_exchange_client.pk == self.right_exchange_client.pk:
            raise ValidationError("Первый и второй клиенты биржи должны быть разными.")
        if self.left_exchange_client.exchange == self.right_exchange_client.exchange:
            raise ValidationError("Клиенты должны быть на разных биржах.")
        if (
            self.left_candle_source.exchange_client.exchange
            != self.left_exchange_client.exchange
        ):
            raise ValidationError(
                "Биржа первого источника свечей должна совпадать с биржей первого клиента."
            )
        if (
            self.right_candle_source.exchange_client.exchange
            != self.right_exchange_client.exchange
        ):
            raise ValidationError(
                "Биржа второго источника свечей должна совпадать с биржей второго клиента."
            )

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

    def get_candles(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ):
        """Получить свечи за диапазон дат."""
        return (
            self.left_candle_source.get_candles(start, end),
            self.right_candle_source.get_candles(start, end),
        )

    def get_last_candles(
        self, count: int = 1000
    ) -> tuple[list[ExchangeCandle], list[ExchangeCandle]]:
        """Получить последние N свечей для арбитражного трейдера."""
        return (
            self.left_candle_source.get_last_candles(count),
            self.right_candle_source.get_last_candles(count),
        )

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
        left_pnl = left_sign * (
            models.F("left_close_price") - models.F("left_open_price")
        ) * models.F("amount") - models.F("left_total_fee")
        right_pnl = right_sign * (
            models.F("right_close_price") - models.F("right_open_price")
        ) * models.F("amount") - models.F("right_total_fee")

        wins = (
            positions.annotate(computed_pnl=left_pnl + right_pnl)
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
        left_pnl = left_sign * models.F("left_order__price") * models.F(
            "left_order__amount"
        ) - models.F("left_order__fee")
        right_pnl = right_sign * models.F("right_order__price") * models.F(
            "right_order__amount"
        ) - models.F("right_order__fee")

        orders = self.orders.filter(position__in=positions)
        result = orders.aggregate(pnl=models.Sum(left_pnl + right_pnl))
        return result["pnl"] or Decimal("0.00")

    def get_theoretical_pnl(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> Decimal:
        """Возвращает теоретический PnL по закрытым позициям."""
        positions = self.closed_positions
        if start_date:
            positions = positions.filter(closed_at__gte=start_date)
        if end_date:
            positions = positions.filter(closed_at__lt=end_date)

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
        left_pnl = left_sign * (
            models.F("left_close_price") - models.F("left_open_price")
        ) * models.F("amount") - models.F("left_total_fee")
        right_pnl = right_sign * (
            models.F("right_close_price") - models.F("right_open_price")
        ) * models.F("amount") - models.F("right_total_fee")
        result = positions.aggregate(pnl=models.Sum(left_pnl + right_pnl))
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
        left_pnl = left_sign * (
            models.F("left_close_price") - models.F("left_open_price")
        ) * models.F("amount") - models.F("left_total_fee")
        right_pnl = right_sign * (
            models.F("right_close_price") - models.F("right_open_price")
        ) * models.F("amount") - models.F("right_total_fee")

        closed_positions = self.closed_positions.order_by("closed_at")
        if start_date:
            closed_positions = closed_positions.filter(closed_at__gte=start_date)
        if end_date:
            closed_positions = closed_positions.filter(closed_at__lt=end_date)

        positions = list(
            closed_positions.annotate(
                computed_pnl=left_pnl + right_pnl,
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

    def load(self, trader: DomainArbitrageTrader) -> None:
        """Загружает состояние domain трейдера из базы данных."""
        left_candles = self.left_candle_source.get_last_candles(count=1000)
        right_candles = self.right_candle_source.get_last_candles(count=1000)
        # Все свечи кроме последней (последняя ещё формируется)
        trader.candles = deque(
            DomainArbitrageCandle(
                left=left.instantiate(),
                right=right.instantiate(),
            )
            for left, right in zip(left_candles[:-1], right_candles[:-1])
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

        ArbitrageTraderSignal.objects.bulk_create(trader_signals)

    def sync_positions(self, trader: DomainArbitrageTrader) -> None:
        """Сохраняет позиции в базу данных."""
        if not trader.positions:
            return
        positions = [
            ArbitrageTraderPosition(
                trader=self,
                type=ArbitragePositionType(position.type),
                left_type=ArbitragePositionType(position.left_type),
                right_type=ArbitragePositionType(position.right_type),
                status=ArbitragePositionStatus(position.status),
                amount=position.amount,
                left_open_price=position.left_open_price,
                left_close_price=position.left_close_price,
                right_open_price=position.right_open_price,
                right_close_price=position.right_close_price,
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
                "left_type",
                "right_type",
                "left_open_price",
                "left_close_price",
                "right_open_price",
                "right_close_price",
                "closed_at",
                "close_reason",
                "left_total_fee",
                "right_total_fee",
            ],
            unique_fields=[
                "trader",
                "opened_at",
                "type",
                "amount",
            ],
        )

    def enable(self):
        self.status = ArbitrageTraderStatus.ENABLED
        self.save(update_fields=["status"])

    def disable(self):
        self.status = ArbitrageTraderStatus.DISABLED
        self.save(update_fields=["status"])

    def clear_all_data(self) -> None:
        """Очищает все данные трейдера: сигналы, позиции, ордера и ошибки."""
        self.signals.all().delete()
        self.positions.all().delete()
        self.orders.all().delete()
        self.errors.all().delete()

    def clear_all_errors(self) -> None:
        """Удаляет все ошибки арбитражного трейдера."""
        self.errors.all().delete()

    def has_existing_signal(self, left_candle: ExchangeCandle) -> bool:
        return self.signals.filter(timestamp=left_candle.timestamp).exists()

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

        async def _handle(
            trader: DomainArbitrageTrader,
            candle: DomainArbitrageCandle,
        ):
            async with trader:
                await trader.handle_candle(candle)

        asyncio.run(_handle(trader=trader, candle=candle))
        self.sync(trader=trader)

    def close_all_opened_positions(self) -> None:
        trader = self.instantiate()
        self.load(trader=trader)

        async def close_all_opened_positions(trader: DomainArbitrageTrader):
            async with trader:
                await trader.close_all_opened_positions()

        asyncio.run(close_all_opened_positions(trader=trader))
        self.sync(trader=trader)

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

        ExchangeClientOrder.objects.bulk_create(left_exchange_client_orders)
        ExchangeClientOrder.objects.bulk_create(right_exchange_client_orders)

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
            (pos.opened_at, pos.amount, ArbitragePositionType(pos.type))
            for _, _, pos in trader.orders
        ]
        orm_positions = list(
            self.positions.filter(
                models.Q(
                    *[
                        models.Q(opened_at=opened_at, amount=amount, type=pos_type)
                        for opened_at, amount, pos_type in position_keys
                    ],
                    _connector=models.Q.OR,
                )
            )
        )

        orm_positions_map = {
            (pos.opened_at, pos.amount, pos.type): pos for pos in orm_positions
        }

        # Создаем ArbitrageTraderOrder
        trader_orders = []
        for left_order, right_order, position in trader.orders:
            key = (
                position.opened_at,
                position.amount,
                ArbitragePositionType(position.type),
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
            ]
        )

        self.status = ArbitrageTraderStatus.ERROR
        self.save(update_fields=["status"])

    def sync(self, trader: DomainArbitrageTrader) -> None:
        """Синхронизирует состояние domain трейдера с базой данных."""
        self.sync_signals(trader=trader)
        self.sync_positions(trader=trader)
        self.sync_orders(trader=trader)
        self.sync_errors(trader=trader)

    def get_candle_iterator(
        self, start: datetime | None = None, end: datetime | None = None
    ):
        """Возвращает итератор ArbitrageCandle для арбитражного трейдера."""
        left_candles = self.left_candle_source.get_candle_iterator(start=start, end=end)
        right_candles = self.right_candle_source.get_candle_iterator(
            start=start, end=end
        )
        for left_candle, right_candle in zip_longest(left_candles, right_candles):
            try:
                yield DomainArbitrageCandle(
                    left=left_candle.instantiate(),
                    right=right_candle.instantiate(),
                )
            except (CandleDesyncError, AttributeError) as e:
                self.errors.create(
                    message=str(e),
                    type=type(e).__name__,
                    traceback=traceback.format_exc(),
                )
                self.status = ArbitrageTraderStatus.ERROR
                self.save(update_fields=["status"])
                return

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
            candle_iterator = self.get_candle_iterator(
                start=start_date,
                end=end_date,
            )

            async def _reboot(
                trader: DomainArbitrageTrader,
                candle_iterator,
            ):
                async with trader:
                    await trader.reboot(candle_iterator=candle_iterator)

            asyncio.run(_reboot(trader=trader, candle_iterator=candle_iterator))
            self.sync(trader=trader)
        except Exception as e:
            self.status = ArbitrageTraderStatus.ERROR
            self.errors.create(
                message=f"Ошибка при перезапуске трейдера: {e!s}",
                type=type(e).__name__,
                traceback=traceback.format_exc(),
            )
        else:
            self.status = ArbitrageTraderStatus.PAUSED
        finally:
            self.save(update_fields=["status", "last_reboot"])

    def instantiate(
        self,
        domain_left_exchange_client: AbstractExchangeClient | None = None,
        domain_right_exchange_client: AbstractExchangeClient | None = None,
    ) -> DomainArbitrageTrader:
        """Создает domain объект ArbitrageTrader из ORM модели."""
        return DomainArbitrageTrader(
            trading_pair=self.trading_pair.instantiate(),  # type: ignore[misc]
            timeframe=DomainTimeframe(self.timeframe),
            left_exchange_client=(
                domain_left_exchange_client or self.left_exchange_client.instantiate()
            ),
            right_exchange_client=(
                domain_right_exchange_client or self.right_exchange_client.instantiate()
            ),
            strategy=self.strategy.instantiate(),
            risk_manager=self.risk_manager.instantiate(),
            use_fixed_balance=self.use_fixed_balance,
            initial_balance=self.initial_balance,
            balance=self.get_balance(),
            check_drawdown=self.check_drawdown,
            max_drawdown_pct=self.max_drawdown_pct,
            max_positions_count=self.max_positions_count,
            create_new_orders=self.create_new_orders,
            close_position_by_strategy=self.close_position_by_strategy,
            close_position_by_opposite_signal=self.close_position_by_opposite_signal,
            status=DomainTraderStatus(self.status),
        )


class ArbitrageTraderError(TimeStampedMixin, models.Model):
    """Ошибки арбитражного трейдера."""

    trader = models.ForeignKey(
        ArbitrageTrader,
        on_delete=models.CASCADE,
        related_name="errors",
        verbose_name="Арбитражный трейдер",
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
        verbose_name = "Арбитражная ошибка трейдера"
        verbose_name_plural = "Арбитражные ошибки трейдера"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.trader.pk} | {self.type or 'Error'} | {self.created_at}"

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
    type = models.CharField(
        max_length=10,
        choices=ArbitragePositionType.choices,
        verbose_name="Тип позиции",
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
                    "type",
                    "amount",
                ],
                name="unique_arbitrage_position",
            )
        ]

    def __str__(self) -> str:
        position = self.instantiate()
        pnl = position.pnl
        pnl_str = f"{round(pnl, 2)}" if pnl is not None else "N/A"
        return (
            f"{self.get_status_display()} | {self.get_type_display()} | PNL:{pnl_str}"
        )

    def instantiate(self) -> DomainArbitrageTraderPosition:
        return DomainArbitrageTraderPosition(
            id=self.pk,
            type=DomainPositionType(self.type),
            left_type=DomainPositionType(self.left_type),
            right_type=DomainPositionType(self.right_type),
            status=DomainPositionStatus(self.status),
            amount=self.amount,
            left_open_price=self.left_open_price,
            left_close_price=self.left_close_price,
            right_open_price=self.right_open_price,
            right_close_price=self.right_close_price,
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
    def open_cost(self) -> Decimal | None:
        """Open Cost."""
        return self.instantiate().open_cost

    @property
    def close_cost(self) -> Decimal | None:
        """Close Cost."""
        return self.instantiate().close_cost

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
        related_name="arbitrage_left_orders",
        verbose_name="Первый ордер",
    )
    right_order = models.OneToOneField(
        ExchangeClientOrder,
        on_delete=models.CASCADE,
        related_name="arbitrage_right_orders",
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
