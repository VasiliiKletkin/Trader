import traceback
from datetime import datetime
from decimal import Decimal, InvalidOperation
from functools import cached_property
from typing import Any, Dict, List, Optional, Tuple
from risk_managers.domain.schemas import (
    PositionStatus as DomainPositionStatus,
    PositionType as DomainPositionType,
)
from risk_managers.domain import (
    TraderPosition as DomainTraderPosition,
)
from .domain.traders import Trader as DomainTrader
from strategies.domain.schemas import TraderSignal as DomainTraderSignal
from core.utils.mixins import TimeStampedMixin
from core.utils.types import (
    OrderSide,
    OrderStatus,
    PositionStatus,
    PositionType,
    SignalType,
    Timeframe,
    TraderStatus,
)
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import (
    Avg,
    Case,
    DurationField,
    ExpressionWrapper,
    F,
    Q,
    Sum,
    When,
)
from django.urls import reverse
from django.utils import timezone
from exchanges.domain.schemas import Candle as CandleDTO
from exchanges.models import Candle, ExchangeClient, ExchangeOrder, TradingPair
from risk_managers.domain.schemas import TraderPosition
from risk_managers.models import RiskManager
from strategies.models import Strategy
from traders.domain.traders import Trader


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
    max_positions_count = models.PositiveIntegerField(
        verbose_name="Макс. количество позиций",
        default=1,
        help_text="Максимальное количество одновременно открытых позиций.",
    )
    trail_stop_enabled = models.BooleanField(
        default=False,
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
    data = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Внутренние данные",
        help_text="Внутренние данные трейдера, которые могут использоваться стратегией "
        "или риск-менеджером для принятия решений.",
    )
    errors = models.TextField(null=True, blank=True)

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
                    "trail_stop_enabled",
                ],
                name="unique_trader_constraint",
            )
        ]

    def __str__(self):
        return f"{self.get_status_display()} | {self.pk} | {self.exchange_client} | {self.strategy}"

    def get_absolute_url(self):
        return reverse("trader_detail", kwargs={"pk": self.pk})

    def instantiate(self) -> DomainTrader:
        candles = [
            candle.instantiate() for candle in self.candles.order_by("timestamp")[:100]
        ]
        signals = [
            signal.instantiate() for signal in self.signals.order_by("timestamp")[:100]
        ]
        orders = [
            order.instantiate() for order in self.orders.order_by("timestamp")[:100]
        ]
        positions = [pos.instantiate() for pos in self.opened_positions.all()]
        return DomainTrader(
            exchange_client=self.exchange_client.instantiate(),
            trading_pair=self.trading_pair,
            timeframe=self.timeframe,
            strategy=self.strategy.instantiate(),
            risk_manager=self.risk_manager.instantiate(),
            initial_balance=self.initial_balance,
            max_drawdown_pct=self.max_drawdown_pct,
            max_positions_count=self.max_positions_count,
            trail_stop_enabled=self.trail_stop_enabled,
            current_balance=self.current_balance,
            candles=candles,
            signals=signals,
            orders=orders,
            positions=positions,
        )

    @property
    def orders(self) -> models.QuerySet[ExchangeOrder]:
        return ExchangeOrder.objects.filter(traderorder__trader=self)

    @property
    def signals(self) -> models.QuerySet["TraderSignal"]:
        return TraderSignal.objects.filter(trader=self)

    @property
    def positions(self) -> models.QuerySet["TraderPosition"]:
        return TraderPosition.objects.filter(trader=self)

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
        orders = self.orders.filter(status__in=[OrderStatus.CLOSED, OrderStatus.OPENED])

        if start_date:
            orders = orders.filter(timestamp__gte=start_date)
        if end_date:
            orders = orders.filter(timestamp__lte=end_date)
        buy_total = orders.filter(side=OrderSide.BUY).aggregate(
            total=models.Sum(models.F("price") * models.F("amount"))
        )["total"] or Decimal("0.00")
        sell_total = orders.filter(side=OrderSide.SELL).aggregate(
            total=models.Sum(models.F("price") * models.F("amount"))
        )["total"] or Decimal("0.00")
        return sell_total - buy_total

    def get_theoretical_profit(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Decimal:
        filters = Q(status=PositionStatus.CLOSED)

        if start_date:
            filters &= Q(opened_at__gte=start_date)
        if end_date:
            filters &= Q(closed_at__lte=end_date)
        positions = self.positions.filter(filters)
        profit_expression = Case(
            When(
                type=PositionType.LONG,
                then=ExpressionWrapper(
                    (F("close_price") - F("open_price")) * F("amount"),
                    output_field=models.DecimalField(max_digits=30, decimal_places=18),
                ),
            ),
            When(
                type=PositionType.SHORT,
                then=ExpressionWrapper(
                    (F("open_price") - F("close_price")) * F("amount"),
                    output_field=models.DecimalField(max_digits=30, decimal_places=18),
                ),
            ),
            default=Decimal("0.00"),
            output_field=models.DecimalField(max_digits=30, decimal_places=18),
        )
        result = positions.aggregate(total_profit=Sum(profit_expression))
        total_profit = result["total_profit"] or Decimal("0.00")
        return total_profit

    def get_avg_position_candles(self) -> Optional[float]:
        timeframe = Timeframe(self.timeframe)
        timeframe_td = timeframe.timedelta()
        if not self.closed_positions.exists():
            return None
        closed_positions = self.closed_positions.annotate(
            duration=ExpressionWrapper(
                F("closed_at") - F("opened_at"), output_field=DurationField()
            )
        )
        avg_duration = closed_positions.aggregate(avg=Avg("duration"))["avg"]
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

    def sync_orders(self, trader: DomainTrader) -> None:
        if trader.orders:
            orders = ExchangeOrder.objects.bulk_create(
                [
                    ExchangeOrder(
                        exchange_client=self.exchange_client,
                        trading_pair=self.trading_pair,
                        timeframe=self.timeframe,
                        side=OrderSide(order.side),
                        status=OrderStatus(order.status),
                        amount=order.amount,
                        price=order.price,
                        timestamp=order.timestamp,
                    )
                    for order in trader.orders
                ],
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
            TraderOrder.objects.bulk_create(
                [TraderOrder(trader=self, order=order) for order in orders]
            )

    def sync_signals(self, trader: DomainTrader) -> None:
        TraderSignal.objects.bulk_create(
            [
                TraderSignal(
                    trader=self,
                    timestamp=signal.timestamp,
                    type=SignalType(signal.type),
                    price=signal.price,
                )
                for signal in trader.signals
            ],
            ignore_conflicts=True,
        )

    def sync_positions(self, trader: DomainTrader) -> None:
        if trader.positions:
            objs = [
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
                    updated_at=pos.updated_at,
                )
                for pos in trader.positions
            ]
            TraderPosition.objects.bulk_create(
                objs,
                update_conflicts=True,
                update_fields=[
                    "status",
                    "close_price",
                    "stop_loss",
                    "take_profit",
                    "closed_at",
                    "updated_at",
                ],
                unique_fields=["trader", "opened_at", "type", "amount"],
            )

    def handle_candle(
        self,
        candle: Candle,
        create_order: bool = True,
    ) -> None:
        if self.signals.filter(timestamp=candle.timestamp).exists():
            return
        trader = self.instantiate()
        trader.load_data(data=self.data)
        trader.handle_candle(
            candle=CandleDTO(
                dt_unix=candle.dt_unix,
                open=candle.open,
                high=candle.high,
                low=candle.low,
                close=candle.close,
                volume=candle.volume,
            ),
            create_order=create_order,
        )
        self.sync_signals(trader=trader)
        self.sync_orders(trader=trader)
        self.sync_positions(trader=trader)
        self.data = trader.dump_data()

    def check_opened_positions(
        self,
        candle: Candle,
        create_order: bool = True,
    ) -> None:
        positions = self.opened_positions.filter(
            opened_at__lte=candle.timestamp,
        )
        if not positions.exists():
            return

        trader = self.instantiate()
        trader.load_data(data=self.data)
        trader.check_opened_positions(
            candle=CandleDTO(
                dt_unix=candle.dt_unix,
                open=candle.open,
                high=candle.high,
                low=candle.low,
                close=candle.close,
                volume=candle.volume,
            ),
            create_order=create_order,
        )
        self.sync_orders(trader=trader)
        self.sync_positions(trader=trader)

    def reboot(self):
        if self.status == TraderStatus.REBOOTING:
            return

        self.signals.all().delete()
        self.positions.all().delete()
        self.data.clear()
        self.errors = None
        self.last_reboot = timezone.now()
        self.status = TraderStatus.REBOOTING
        self.save(update_fields=["status", "last_reboot", "data", "errors"])

        create_order = False

        try:
            trader = self.instantiate()
            trader.candles = []
            trader.orders = []
            trader.signals = []
            trader.positions = []

            trader.load_data(data=self.data)
            for candle in self.candles.order_by("timestamp").iterator():
                candle_dto = CandleDTO(
                    dt_unix=candle.dt_unix,
                    open=candle.open,
                    high=candle.high,
                    low=candle.low,
                    close=candle.close,
                    volume=candle.volume,
                )
                trader.handle_candle(
                    candle=candle_dto,
                    create_order=create_order,
                )
            self.sync_signals(trader=trader)
            self.sync_positions(trader=trader)
            self.data = trader.dump_data()
        except Exception:
            self.status = TraderStatus.ERROR
            self.errors = traceback.format_exc()
            self.signals.all().delete()
            self.positions.all().delete()
            self.data.clear()
        else:
            self.status = TraderStatus.ENABLED
        finally:
            self.save(update_fields=["status", "data", "errors"])


class TraderOrder(TimeStampedMixin, models.Model):
    trader = models.ForeignKey(
        Trader,
        on_delete=models.CASCADE,
        verbose_name="Трейдер",
    )
    order = models.OneToOneField(
        ExchangeOrder,
        on_delete=models.CASCADE,
        verbose_name="Ордер биржи",
    )

    class Meta:
        verbose_name = "Ордер трейдера"
        verbose_name_plural = "Ордера трейдера"

    def __str__(self):
        return f"{self.trader} | {self.order.side} {self.order.amount} @ {self.order.price}"


class TraderSignal(models.Model):
    trader = models.ForeignKey(
        Trader,
        on_delete=models.CASCADE,
        verbose_name="Трейдер",
    )
    timestamp = models.DateTimeField(
        verbose_name="Время",
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
                name="unique_signal_constraint",
            )
        ]

    def instantiate(self) -> DomainTraderSignal:
        return DomainTraderSignal(
            trader=self.trader,
            timestamp=self.timestamp,
            type=SignalType(self.type),
            price=self.price,
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
        verbose_name="Объем",
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
    )
    closed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Время закрытия",
    )
    updated_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Время последнего обновления",
        help_text="Время последнего обновления позиции. "
        "Используется для отслеживания изменений в позиции.",
    )

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
                name="unique_position_constraint",
            )
        ]

    def instantiate(self) -> TraderPosition:
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
            updated_at=self.updated_at,
        )

    def __str__(self):
        position = self.instantiate()
        pnl = position.pnl
        pnl_str = f"{round(pnl, 2)}" if pnl else "N/A"
        rr = position.rr
        rr_str = f"{round(rr, 2)}" if rr else "N/A"
        return (
            f"{self.get_status_display()} | {self.get_type_display()} | "
            f"PNL:{pnl_str} | RR:{rr_str}"
        )

    @property
    def open_value(self) -> Optional[Decimal]:
        return self.instantiate().open_value

    @property
    def close_value(self) -> Optional[Decimal]:
        return self.instantiate().close_value

    @property
    def stop_loss_pct(self) -> Optional[Decimal]:
        return self.instantiate().stop_loss_pct

    @property
    def take_profit_pct(self) -> Optional[Decimal]:
        return self.instantiate().take_profit_pct

    @property
    def pnl(self) -> Optional[Decimal]:
        return self.instantiate().pnl

    @property
    def rr(self) -> Optional[Decimal]:
        return self.instantiate().rr

    def should_be_closed(
        self,
        signal: SignalType | None,
        price: Decimal | None,
    ) -> bool:
        return self.instantiate().should_be_closed(signal=signal, price=price)
