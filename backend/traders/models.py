import asyncio
import traceback
from datetime import datetime
from decimal import Decimal
from functools import cached_property
from typing import Optional

from core.utils.mixins import TimeStampedMixin
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
from django.db import models, transaction
from django.forms import ValidationError
from django.urls import reverse
from django.utils import timezone
from exchange_clients.domain import AbstractExchangeClient
from exchange_clients.domain import ExchangeClientOrder as DomainExchangeClientOrder
from exchange_clients.models import (
    ExchangeClient,
    ExchangeClientBalance,
    ExchangeClientOrder,
)
from exchanges.domain import Candle as DomainCandle
from exchanges.domain import Timeframe as DomainTimeframe
from exchanges.models import Candle, TradingPair
from risk_managers.domain import PositionCloseReason as DomainPositionCloseReason
from risk_managers.domain import PositionStatus as DomainPositionStatus
from risk_managers.domain import PositionType as DomainPositionType
from risk_managers.models import RiskManager
from strategies.domain import SignalType as DomainSignalType
from strategies.domain import TraderSignal as DomainTraderSignal
from strategies.models import Strategy
from traders.domain import Trader as DomainTrader
from traders.domain import TraderPosition as DomainTraderPosition
from traders.domain import TraderState as DomainTraderState


class Trader(TimeStampedMixin, models.Model):
    favorite = models.BooleanField(
        default=False,
        verbose_name="Избранный трейдер",
        help_text="Отметьте, если хотите добавить трейдера в избранное.",
    )
    status = models.CharField(
        choices=TraderStatus.choices,
        default=TraderStatus.DISABLED,
        verbose_name="Статус",
    )
    exchange_client = models.ForeignKey(
        ExchangeClient,
        on_delete=models.CASCADE,
        verbose_name="Клиент биржи",
        limit_choices_to={"is_active": True},
        help_text="Выберите клиента биржи, который будет использовать трейдер.",
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
    create_new_orders = models.BooleanField(
        default=True,
        verbose_name="Создавать ордера биржи",
        help_text="Если выбрано, трейдер будет создавать новые ордера согласно своей стратегии.",
    )
    max_positions_count = models.PositiveIntegerField(
        verbose_name="Макс. количество позиций",
        default=1,
        help_text="Максимальное количество одновременно открытых позиций.",
    )
    close_position_by_opposite_signal = models.BooleanField(
        default=True,
        verbose_name="Закрывать позиции при противоположном сигнале",
        help_text="Если выбрано, трейдер будет закрывать позицию при получении противоположного сигнала.",
    )
    close_position_by_strategy = models.BooleanField(
        default=True,
        verbose_name="Закрывать позиции по сигналу стратегии",
        help_text="Если выбрано, трейдер будет закрывать позицию при получении сигнала от стратегии.",
    )
    close_position_by_stop_loss = models.BooleanField(
        default=True,
        verbose_name="Закрывать позиции по Stop Loss",
        help_text="Если выбрано, трейдер будет закрывать позицию при достижении Stop Loss.",
    )
    close_position_by_take_profit = models.BooleanField(
        default=True,
        verbose_name="Закрывать позиции по Take Profit",
        help_text="Если выбрано, трейдер будет закрывать позицию при достижении Take Profit.",
    )
    trail_stop_enabled = models.BooleanField(
        default=True,
        verbose_name="Трейлинг-стоп",
        help_text="Если выбрано, трейдер будет использовать трейлинг-стоп для позиций.",
    )
    last_reboot = models.DateTimeField(
        verbose_name="Последний перезапуск",
        null=True,
        blank=True,
        help_text="Дата и время последнего перезапуска трейдера. "
        "Используется для отслеживания активности трейдера.",
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
        verbose_name = "Трейдер"
        verbose_name_plural = "Трейдеры"
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
                name="unique_trader",
            )
        ]

    def __str__(self):
        return f"{self.get_status_display()} | {self.pk} | {self.exchange_client} | {self.strategy}"

    def get_absolute_url(self):
        return reverse("trader_detail", kwargs={"pk": self.pk})

    def instantiate(
        self,
        domain_exchange_client: Optional[AbstractExchangeClient] = None,
    ) -> DomainTrader:
        exchange_client = domain_exchange_client or self.exchange_client.instantiate()
        return DomainTrader(
            errors=self.errors,
            last_error=self.last_error,
            trading_pair=self.trading_pair.instantiate(),
            timeframe=DomainTimeframe(self.timeframe),
            exchange_client=exchange_client,
            strategy=self.strategy.instantiate(),
            risk_manager=self.risk_manager.instantiate(),
            initial_balance=self.initial_balance,
            max_drawdown_pct=self.max_drawdown_pct,
            max_positions_count=self.max_positions_count,
            trail_stop_enabled=self.trail_stop_enabled,
            create_new_orders=self.create_new_orders,
            close_position_by_stop_loss=self.close_position_by_stop_loss,
            close_position_by_take_profit=self.close_position_by_take_profit,
            close_position_by_strategy=self.close_position_by_strategy,
            close_position_by_opposite_signal=self.close_position_by_opposite_signal,
            current_balance=self.current_balance,
        )

    @property
    def orders(self) -> models.QuerySet["TraderOrder"]:
        return TraderOrder.objects.filter(trader=self)

    @property
    def signals(self) -> models.QuerySet["TraderSignal"]:
        return TraderSignal.objects.filter(trader=self)

    @property
    def positions(self) -> models.QuerySet["TraderPosition"]:
        return TraderPosition.objects.filter(trader=self)

    @property
    def states(self) -> models.QuerySet["TraderState"]:
        return TraderState.objects.filter(trader=self)

    def get_opened_positions(self) -> models.QuerySet["TraderPosition"]:
        return self.positions.filter(status=PositionStatus.OPENED)

    def get_closed_positions(self) -> models.QuerySet["TraderPosition"]:
        return self.positions.filter(status=PositionStatus.CLOSED)

    @cached_property
    def opened_positions(self) -> models.QuerySet["TraderPosition"]:
        return self.get_opened_positions()

    @cached_property
    def closed_positions(self) -> models.QuerySet["TraderPosition"]:
        return self.get_closed_positions()

    @property
    def candles(self) -> models.QuerySet[Candle]:
        return Candle.objects.filter(
            exchange=self.exchange_client.exchange,
            timeframe=self.timeframe,
            trading_pair=self.trading_pair,
        )

    def get_total_positions_count(self) -> int:
        return self.positions.count()

    def get_total_positions_count_with_orders(self) -> int:
        return self.positions.filter(traderorder__isnull=False).distinct().count()

    def get_total_orders_count(self) -> int:
        return self.orders.count()

    def get_winrate(self) -> float:
        total = self.closed_positions.count()
        if total == 0:
            return 0.0
        wins = self.closed_positions.filter(
            models.Q(type=PositionType.LONG, close_price__gt=models.F("open_price"))
            | models.Q(type=PositionType.SHORT, close_price__lt=models.F("open_price"))
        ).count()
        return wins / total * 100

    def get_fact_profit(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Decimal:
        orders = self.orders.filter(
            order__status__in=[OrderStatus.CLOSED, OrderStatus.OPENED],
            position__status=PositionStatus.CLOSED,
        )
        if start_date:
            orders = orders.filter(order__timestamp__gte=start_date)
        if end_date:
            orders = orders.filter(order__timestamp__lte=end_date)
        buy_total = orders.filter(order__side=OrderSide.BUY).aggregate(
            total=models.Sum(models.F("order__price") * models.F("order__amount"))
        )["total"] or Decimal("0.00")
        sell_total = orders.filter(order__side=OrderSide.SELL).aggregate(
            total=models.Sum(models.F("order__price") * models.F("order__amount"))
        )["total"] or Decimal("0.00")
        fee_total = orders.aggregate(total=models.Sum("order__fee"))[
            "total"
        ] or Decimal("0.00")
        return (sell_total - buy_total) - fee_total

    def get_theoretical_profit(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Decimal:
        filters = models.Q(status=PositionStatus.CLOSED)

        if start_date:
            filters &= models.Q(opened_at__gte=start_date)
        if end_date:
            filters &= models.Q(closed_at__lte=end_date)
        positions = self.positions.filter(filters)
        profit_expression = models.Case(
            models.When(
                type=PositionType.LONG,
                then=models.ExpressionWrapper(
                    (models.F("close_price") - models.F("open_price"))
                    * models.F("amount"),
                    output_field=models.DecimalField(max_digits=30, decimal_places=18),
                ),
            ),
            models.When(
                type=PositionType.SHORT,
                then=models.ExpressionWrapper(
                    (models.F("open_price") - models.F("close_price"))
                    * models.F("amount"),
                    output_field=models.DecimalField(max_digits=30, decimal_places=18),
                ),
            ),
            default=Decimal("0.00"),
            output_field=models.DecimalField(max_digits=30, decimal_places=18),
        )
        result = positions.aggregate(total_profit=models.Sum(profit_expression))
        total_profit = result["total_profit"] or Decimal("0.00")
        return total_profit

    def get_avg_position_candles(self) -> Optional[float]:
        timeframe = Timeframe(self.timeframe)
        timeframe_td = timeframe.timedelta()
        if not self.closed_positions.exists():
            return None
        closed_positions = self.closed_positions.annotate(
            duration=models.ExpressionWrapper(
                models.F("closed_at") - models.F("opened_at"),
                output_field=models.DurationField(),
            )
        )
        avg_duration = closed_positions.aggregate(avg=models.Avg("duration"))["avg"]
        if avg_duration is None:
            return None
        return avg_duration / timeframe_td

    def get_current_balance(self) -> Decimal:
        return self.initial_balance + self.get_fact_profit()

    @property
    def current_balance(self) -> Decimal:
        return self.get_current_balance()

    def enable(self):
        self.status = TraderStatus.ENABLED
        self.save(update_fields=["status"])

    def disable(self):
        self.status = TraderStatus.DISABLED
        self.save(update_fields=["status"])

    def clear_all_data(self):
        self.signals.delete()
        self.orders.delete()
        self.positions.delete()
        self.states.delete()

    def clear_all_errors(self):
        self.errors = None
        self.save(
            update_fields=[
                "errors",
            ]
        )

    def load(self, trader: DomainTrader) -> None:
        states = self.states.select_related(
            "candle",
            "signal",
        ).order_by(
            "-timestamp",
        )[:100]
        trader.states = [state.instantiate() for state in states[::-1]]
        trader.positions = [
            pos.instantiate()
            for pos in self.opened_positions.select_related(
                "trader",
            ).order_by(
                "opened_at",
            )
        ]
        trader.positions_map = {id(pos): [] for pos in trader.positions}

    def sync_signals(self, trader: DomainTrader) -> None:
        if not trader.signals:
            return
        trader_signals = [
            TraderSignal(
                trader=self,
                timestamp=signal.timestamp,
                type=SignalType(signal.type),
                price=signal.price,
                data=signal.data,
            )
            for signal in trader.signals
        ]
        TraderSignal.objects.bulk_create(
            trader_signals,
            ignore_conflicts=True,
            unique_fields=[
                "trader",
                "timestamp",
                "type",
                "price",
            ],
        )

    def sync_positions(self, trader: DomainTrader) -> None:
        if not trader.positions:
            return
        trader_positions = [
            TraderPosition(
                trader=self,
                type=PositionType(pos.type),
                status=PositionStatus(pos.status),
                amount=pos.amount,
                open_price=pos.open_price,
                close_price=pos.close_price,
                stop_loss=pos.stop_loss,
                take_profit=pos.take_profit,
                opened_at=pos.opened_at,
                closed_at=pos.closed_at,
                recalculated_at=pos.recalculated_at,
                close_reason=(
                    PositionCloseReason(pos.close_reason) if pos.close_reason else None
                ),
                data=pos.data,
            )
            for pos in trader.positions
        ]
        TraderPosition.objects.bulk_create(
            trader_positions,
            update_conflicts=True,
            update_fields=[
                "status",
                "close_price",
                "stop_loss",
                "take_profit",
                "closed_at",
                "recalculated_at",
                "close_reason",
            ],
            unique_fields=[
                "trader",
                "opened_at",
                "type",
                "amount",
            ],
        )

    def sync_orders(self, trader: DomainTrader) -> None:
        if not trader.orders:
            return
        exchange_client_orders = [
            ExchangeClientOrder(
                exchange_client=self.exchange_client,
                trading_pair=self.trading_pair,
                exchange_order_id=order.exchange_order_id,
                side=OrderSide(order.side),
                status=OrderStatus(order.status),
                amount=order.amount,
                price=order.price,
                cost=order.cost,
                fee=order.fee,
                timestamp=order.timestamp,
            )
            for order in trader.orders
        ]
        ExchangeClientOrder.objects.bulk_create(
            exchange_client_orders,
            ignore_conflicts=True,
            update_fields=[
                "status",
            ],
            unique_fields=[
                "exchange_client",
                "trading_pair",
                "timestamp",
                "exchange_order_id",
            ],
        )
        position_map = {}
        for pos in trader.positions:
            orm_pos = self.positions.filter(
                opened_at=pos.opened_at,
                amount=pos.amount,
            ).first()
            if not trader.positions_map.get(id(pos)) or not orm_pos:
                self.errors += f"error_position with {pos.opened_at} {pos.amount}"
                continue
            for order_uuid in trader.positions_map[id(pos)]:
                position_map[order_uuid] = orm_pos
        client_orders = ExchangeClientOrder.objects.filter(
            exchange_client=self.exchange_client,
            trading_pair=self.trading_pair,
            exchange_order_id__in=[o.exchange_order_id for o in trader.orders],
        )
        trader_orders = [
            TraderOrder(
                trader=self,
                order=order,
                position=position_map[order.exchange_order_id],
            )
            for order in client_orders
        ]

        TraderOrder.objects.bulk_create(
            trader_orders,
            ignore_conflicts=True,
            update_fields=[
                "order",
                "position",
            ],
            unique_fields=[
                "trader",
                "order",
            ],
        )

    def sync_states(self, trader: DomainTrader) -> None:
        if not trader.states:
            return
        candles = self.candles.filter(
            timestamp__in=[state.timestamp for state in trader.states],
        )
        candle_map = {candle.timestamp: candle for candle in candles}
        signals = self.signals.filter(
            timestamp__in=[state.timestamp for state in trader.states],
        )
        signal_map = {signal.timestamp: signal for signal in signals}
        states = [
            TraderState(
                trader=self,
                timestamp=state.timestamp,
                candle=candle_map[state.timestamp],
                signal=signal_map[state.timestamp],
            )
            for state in trader.states
        ]
        TraderState.objects.bulk_create(
            states,
            ignore_conflicts=True,
            unique_fields=[
                "trader",
                "timestamp",
            ],
        )

    def sync_errors(self, trader: DomainTrader) -> None:
        if not trader.errors:
            return

        self.status = TraderStatus.ERROR
        self.errors = trader.errors
        self.last_error = trader.last_error
        self.save(
            update_fields=[
                "status",
                "errors",
                "last_error",
            ]
        )

    def sync(self, trader: DomainTrader) -> None:
        self.sync_signals(trader=trader)
        self.sync_positions(trader=trader)
        self.sync_orders(trader=trader)
        self.sync_states(trader=trader)
        self.sync_errors(trader=trader)

    def has_existing_signal(self, candle: Candle) -> bool:
        return self.signals.filter(timestamp=candle.timestamp).exists()

    @transaction.atomic
    def handle_candle(
        self,
        candle: Candle,
    ) -> None:
        if self.has_existing_signal(candle=candle):
            return

        trader = self.instantiate()
        self.load(trader=trader)

        async def handle_candle(
            trader: DomainTrader,
            candle: DomainCandle,
        ):
            async with trader:
                await trader.handle_candle(
                    candle=candle,
                )

        asyncio.run(
            handle_candle(
                trader=trader,
                candle=candle.instantiate(),
            )
        )
        self.sync(trader=trader)

    @transaction.atomic
    def check_opened_positions(
        self,
        candle: Candle,
    ) -> None:

        trader = self.instantiate()
        self.load(trader=trader)

        async def check_opened_positions(
            trader: DomainTrader,
            candle: DomainCandle,
        ):
            async with trader:
                await trader.check_opened_positions(
                    candle=candle,
                )

        asyncio.run(
            check_opened_positions(
                trader=trader,
                candle=candle.instantiate(),
            )
        )
        self.sync(trader=trader)

    def reboot(self):
        if self.status == TraderStatus.REBOOTING:
            return

        self.clear_all_data()
        self.clear_all_errors()
        self.last_reboot = timezone.now()
        self.status = TraderStatus.REBOOTING
        self.save(
            update_fields=[
                "status",
                "last_reboot",
            ]
        )

        trader = self.instantiate()
        trader.create_new_orders = False
        candles = self.candles.order_by("timestamp")

        async def reboot(
            trader: DomainTrader,
            candles: list[DomainCandle],
        ):
            async with trader:
                for candle in candles:
                    await trader.handle_candle(
                        candle=candle,
                    )
                await trader.close_all_opened_positions()

        asyncio.run(
            reboot(
                trader=trader,
                candles=[c.instantiate() for c in candles.iterator()],
            )
        )
        self.status = TraderStatus.ENABLED
        self.save(
            update_fields=[
                "status",
            ]
        )
        self.sync(trader=trader)

    @transaction.atomic
    def close_all_opened_positions(
        self,
    ) -> None:
        trader = self.instantiate()
        self.load(trader=trader)

        async def close_all_opened_positions(trader: DomainTrader):
            async with trader:
                await trader.close_all_opened_positions()

        asyncio.run(close_all_opened_positions(trader=trader))
        self.sync(trader=trader)

    def get_candle_at_time(self, dt: datetime = timezone.now()) -> Optional[Candle]:
        return (
            self.candles.filter(
                timestamp__lte=dt,
                timestamp__gt=dt - Timeframe(self.timeframe).timedelta(),
            )
            .order_by("-timestamp")
            .first()
        )


class TraderSignal(models.Model):
    trader = models.ForeignKey(
        Trader,
        on_delete=models.CASCADE,
        verbose_name="Трейдер",
    )
    timestamp = models.DateTimeField(
        verbose_name="Время",
        db_index=True,
    )
    type = models.CharField(
        max_length=10,
        choices=SignalType.choices,
        verbose_name="Тип",
    )
    price = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        verbose_name="Цена",
    )
    data = models.JSONField()

    class Meta:
        verbose_name = "Сигнал трейдера"
        verbose_name_plural = "Сигналы трейдера"
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "trader",
                    "timestamp",
                    "type",
                    "price",
                ],
                name="unique_signal",
            )
        ]

    def instantiate(self) -> DomainTraderSignal:
        return DomainTraderSignal(
            timestamp=self.timestamp,
            type=DomainSignalType(self.type),
            price=self.price,
            data=self.data,
        )


class TraderPosition(models.Model):
    trader = models.ForeignKey(
        Trader,
        on_delete=models.CASCADE,
        verbose_name="Трейдер",
    )
    type = models.CharField(
        max_length=10,
        choices=PositionType.choices,
        verbose_name="Тип",
    )
    status = models.CharField(
        max_length=10,
        choices=PositionStatus.choices,
        default=PositionStatus.OPENED,
        verbose_name="Статус",
    )
    amount = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        verbose_name="Количество",
    )
    open_price = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        null=True,
        blank=True,
        verbose_name="Цена открытия",
    )
    close_price = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        null=True,
        blank=True,
        verbose_name="Цена закрытия",
    )
    stop_loss = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        null=True,
        blank=True,
        verbose_name="Stop Loss",
    )
    take_profit = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        null=True,
        blank=True,
        verbose_name="Take Profit",
    )
    opened_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Время открытия",
        db_index=True,
    )
    closed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Время закрытия",
    )
    recalculated_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Время последнего перерасчета",
        help_text="Время последнего обновления значений в позиции.",
    )
    close_reason = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        choices=PositionCloseReason.choices,
        verbose_name="Причина закрытия",
        help_text="Причина закрытия позиции, если она была закрыта.",
    )
    data = models.JSONField()

    class Meta:
        verbose_name = "Позиция трейдера"
        verbose_name_plural = "Позиции трейдера"
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "trader",
                    "opened_at",
                    "type",
                    "amount",
                ],
                name="unique_position",
            )
        ]

    def instantiate(self) -> DomainTraderPosition:
        return DomainTraderPosition(
            type=DomainPositionType(self.type),
            status=DomainPositionStatus(self.status),
            amount=self.amount,
            open_price=self.open_price,
            close_price=self.close_price,
            stop_loss=self.stop_loss,
            take_profit=self.take_profit,
            opened_at=self.opened_at,
            closed_at=self.closed_at,
            recalculated_at=self.recalculated_at,
            data=self.data,
            close_reason=(
                DomainPositionCloseReason(self.close_reason)
                if self.close_reason
                else None
            ),
        )

    def __str__(self):
        position = self.instantiate()
        pnl = position.pnl
        pnl_str = f"{round(pnl, 2)}" if pnl is not None else "N/A"
        rr = position.rr
        rr_str = f"{round(rr, 2)}" if rr is not None else "N/A"
        return (
            f"{self.get_status_display()} | {self.get_type_display()} | "
            f"PNL:{pnl_str} | RR:{rr_str}"
        )

    @property
    def open_cost(self) -> Optional[Decimal]:
        """Open Cost."""
        return self.instantiate().open_cost

    @property
    def close_cost(self) -> Optional[Decimal]:
        """Close Cost."""
        return self.instantiate().close_cost

    @property
    def stop_loss_pct(self) -> Optional[Decimal]:
        """Stop Loss Percentage."""
        return self.instantiate().stop_loss_pct

    @property
    def take_profit_pct(self) -> Optional[Decimal]:
        """Take Profit Percentage."""
        return self.instantiate().take_profit_pct

    @property
    def pnl(self) -> Optional[Decimal]:
        """Profit and Loss."""
        return self.instantiate().pnl

    def pnl_pct(self) -> Optional[Decimal]:
        """Profit and Loss Percentage."""
        return self.instantiate().pnl_pct

    @property
    def rr(self) -> Optional[Decimal]:
        """Risk-Reward Ratio."""
        return self.instantiate().rr

    @property
    def is_closed(self) -> bool:
        return self.instantiate().is_closed

    def refresh(self) -> None:
        orders = self.trader.orders.filter(position=self)
        if not orders.exists():
            return

        buy_orders = orders.filter(order__side=OrderSide.BUY)
        sell_orders = orders.filter(order__side=OrderSide.SELL)

        open_orders = buy_orders if self.type == PositionType.LONG else sell_orders
        close_orders = sell_orders if self.type == PositionType.LONG else buy_orders

        self.amount = open_orders.aggregate(total=models.Sum("order__amount"))[
            "total"
        ] or Decimal("0.00")

        if open_orders.exists():
            agg = open_orders.aggregate(
                cost=models.Sum(models.F("order__price") * models.F("order__amount")),
                amount=models.Sum("order__amount"),
            )
            self.open_price = agg["cost"] / agg["amount"] if agg["amount"] > 0 else None

        if close_orders.exists():
            agg = close_orders.aggregate(
                cost=models.Sum(models.F("order__price") * models.F("order__amount")),
                amount=models.Sum("order__amount"),
            )
            self.close_price = (
                agg["cost"] / agg["amount"] if agg["amount"] > 0 else None
            )

        self.save(
            update_fields=["amount", "open_price", "close_price", "recalculated_at"]
        )


class TraderOrder(TimeStampedMixin, models.Model):
    trader = models.ForeignKey(
        Trader,
        on_delete=models.CASCADE,
        verbose_name="Трейдер",
    )
    order = models.OneToOneField(
        ExchangeClientOrder,
        on_delete=models.CASCADE,
        verbose_name="Ордер биржи",
    )
    position = models.ForeignKey(
        TraderPosition,
        on_delete=models.CASCADE,
        verbose_name="Позиция трейдера",
    )

    class Meta:
        verbose_name = "Ордер трейдера"
        verbose_name_plural = "Ордера трейдера"
        constraints = [
            models.UniqueConstraint(
                fields=["trader", "order", "position"],
                name="unique_trader_order",
            )
        ]

    def clean(self) -> None:
        super().clean()

        if self.position and self.position.trader.pk != self.trader.pk:
            raise ValidationError("Позиция должна принадлежать тому же трейдеру.")

    def __str__(self):
        return f"{self.trader} | {self.order.side} {self.order.amount} @ {self.order.price}"

    def instantiate(self) -> DomainExchangeClientOrder:
        return self.order.instantiate()

    # @property
    # def cost(self) -> Decimal:
    #     return self.order.cost


class TraderState(models.Model):
    trader = models.ForeignKey(Trader, on_delete=models.CASCADE)
    timestamp = models.DateTimeField()
    candle = models.ForeignKey(Candle, on_delete=models.CASCADE)
    signal = models.ForeignKey(TraderSignal, on_delete=models.CASCADE)

    class Meta:
        verbose_name = "История состояний трейдера"
        verbose_name_plural = "История состояний трейдеров"
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "trader",
                    "timestamp",
                ],
                name="unique_trader_state",
            )
        ]

    def instantiate(self) -> DomainTraderState:
        return DomainTraderState(
            timestamp=self.timestamp,
            candle=self.candle.instantiate(),
            signal=self.signal.instantiate(),
        )
