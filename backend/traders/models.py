import asyncio
from collections import deque
from datetime import datetime
from decimal import Decimal
from itertools import zip_longest

import numpy as np
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.forms import ValidationError
from django.urls import reverse
from django.utils import timezone

from candle_sources.domain import ProviderCandle as DomainProviderCandle
from candle_sources.models import CandleSource
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
from exchange_clients.domain import AbstractExchangeClient
from exchange_clients.domain import ExchangeClientOrder as DomainExchangeClientOrder
from exchange_clients.models import ExchangeClient, ExchangeClientOrder
from exchanges.domain import ExchangeCandle as DomainExchangeCandle
from exchanges.domain import Timeframe as DomainTimeframe
from exchanges.models import ExchangeCandle, ExchangeTradingPair, TradingPair
from risk_managers.domain import PositionCloseReason as DomainPositionCloseReason
from risk_managers.domain import PositionStatus as DomainPositionStatus
from risk_managers.domain import PositionType as DomainPositionType
from risk_managers.models import RiskManager
from strategies.domain import ArbitrageTraderSignal as DomainArbitrageTraderSignal
from strategies.domain import SignalType as DomainSignalType
from strategies.domain import TraderSignal as DomainTraderSignal
from strategies.models import ArbitrageStrategy, Strategy
from telegram_bots.tasks import send_notification
from traders.domain import ArbitrageTrader as DomainArbitrageTrader
from traders.domain import ArbitrageTraderError as DomainArbitrageTraderError
from traders.domain import ArbitrageTraderPosition as DomainArbitrageTraderPosition
from traders.domain import Trader as DomainTrader
from traders.domain import TraderError as DomainTraderError
from traders.domain import TraderPosition as DomainTraderPosition
from traders.domain import TraderStatus as DomainTraderStatus


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
    candle_source = models.ForeignKey(
        CandleSource,
        on_delete=models.CASCADE,
        verbose_name="Источник свечей",
        limit_choices_to={"is_active": True},
        help_text="Выберите источник свечей для трейдера.",
    )
    exchange_client = models.ForeignKey(
        ExchangeClient,
        on_delete=models.CASCADE,
        verbose_name="Клиент биржи",
        limit_choices_to={"is_active": True},
        help_text="Выберите клиента биржи, который будет использовать трейдер.",
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
    use_fixed_balance = models.BooleanField(
        default=True,
        verbose_name="Использовать фиксированный баланс",
        help_text="Если выбрано, трейдер будет использовать фиксированный баланс, игнорируя заработанные/проебанные деньги.",
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
        verbose_name="Проверять просадку",
        help_text="Если выбрано, трейдер будет проверять максимальную просадку.",
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
        help_text="Дата и время последнего перезапуска трейдера.",
    )

    class Meta:
        verbose_name = "Трейдер"
        verbose_name_plural = "Трейдеры"
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "candle_source",
                    "exchange_client",
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

    @property
    def timeframe(self) -> Timeframe:
        """Возвращает timeframe трейдера."""
        return Timeframe(self.candle_source.timeframe)

    @property
    def trading_pair(self) -> TradingPair | ExchangeTradingPair:
        """Возвращает торговую пару трейдера."""
        exchange_trading_pair = ExchangeTradingPair.objects.filter(
            exchange=self.exchange_client.exchange,
            trading_pair=self.candle_source.trading_pair,
        ).first()
        return self.candle_source.trading_pair or exchange_trading_pair

    def instantiate(
        self,
        domain_exchange_client: AbstractExchangeClient | None = None,
    ) -> DomainTrader:
        return DomainTrader(
            trading_pair=self.trading_pair.instantiate(),
            timeframe=DomainTimeframe(self.timeframe),
            exchange_client=(
                domain_exchange_client or self.exchange_client.instantiate()
            ),
            strategy=self.strategy.instantiate(),
            risk_manager=self.risk_manager.instantiate(),
            use_fixed_balance=self.use_fixed_balance,
            initial_balance=self.initial_balance,
            balance=self.get_balance(),
            check_drawdown=self.check_drawdown,
            max_drawdown_pct=self.max_drawdown_pct,
            max_positions_count=self.max_positions_count,
            trail_stop_enabled=self.trail_stop_enabled,
            create_new_orders=self.create_new_orders,
            close_position_by_stop_loss=self.close_position_by_stop_loss,
            close_position_by_take_profit=self.close_position_by_take_profit,
            close_position_by_strategy=self.close_position_by_strategy,
            close_position_by_opposite_signal=self.close_position_by_opposite_signal,
            status=DomainTraderStatus(self.status),
        )

    def get_last_candles(self, count: int):
        """Получить последние N свечей для трейдера."""
        return self.candle_source.get_last_candles(count)

    def get_opened_positions(self) -> models.QuerySet["TraderPosition"]:
        return self.positions.filter(status=PositionStatus.OPENED)

    def get_closed_positions(self) -> models.QuerySet["TraderPosition"]:
        return self.positions.filter(status=PositionStatus.CLOSED)

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
    def opened_positions(self) -> models.QuerySet["TraderPosition"]:
        return self.get_opened_positions()

    @property
    def closed_positions(self) -> models.QuerySet["TraderPosition"]:
        return self.get_closed_positions()

    def get_total_positions_count(self) -> int:
        return self.positions.count()

    def get_total_positions_count_with_orders(self) -> int:
        return self.positions.filter(traderorder__isnull=False).distinct().count()

    def get_total_orders_count(self) -> int:
        return self.orders.count()

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
        wins = positions.filter(
            models.Q(type=PositionType.LONG, close_price__gt=models.F("open_price"))
            | models.Q(type=PositionType.SHORT, close_price__lt=models.F("open_price"))
        ).count()
        return wins / total

    def get_fact_pnl(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> Decimal:
        positions = self.positions.filter(status=PositionStatus.CLOSED)
        if start_date:
            positions = positions.filter(closed_at__gte=start_date)
        if end_date:
            positions = positions.filter(closed_at__lt=end_date)

        orders = TraderOrder.objects.filter(position__in=positions)
        result = orders.aggregate(
            gross_pnl=models.Sum(
                models.Case(
                    models.When(
                        order__side=OrderSide.SELL,
                        then=models.F("order__price") * models.F("order__amount"),
                    ),
                    models.When(
                        order__side=OrderSide.BUY,
                        then=-models.F("order__price") * models.F("order__amount"),
                    ),
                    default=Decimal("0.00"),
                    output_field=models.DecimalField(max_digits=30, decimal_places=18),
                )
            ),
            fee=models.Sum("order__fee"),
            pnl=models.functions.Coalesce(
                models.F("gross_pnl") - models.F("fee"), Decimal("0.00")
            ),
        )
        return result["pnl"]

    def get_theoretical_pnl(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> Decimal:
        positions = self.positions.filter(status=PositionStatus.CLOSED)
        if start_date:
            positions = positions.filter(closed_at__gte=start_date)
        if end_date:
            positions = positions.filter(closed_at__lt=end_date)
        result = positions.aggregate(
            gross_pnl=models.Sum(
                models.Case(
                    models.When(
                        type=PositionType.LONG,
                        then=models.ExpressionWrapper(
                            (models.F("close_price") - models.F("open_price"))
                            * models.F("amount"),
                            output_field=models.DecimalField(
                                max_digits=30, decimal_places=18
                            ),
                        ),
                    ),
                    models.When(
                        type=PositionType.SHORT,
                        then=models.ExpressionWrapper(
                            (models.F("open_price") - models.F("close_price"))
                            * models.F("amount"),
                            output_field=models.DecimalField(
                                max_digits=30, decimal_places=18
                            ),
                        ),
                    ),
                    default=Decimal("0.00"),
                    output_field=models.DecimalField(max_digits=30, decimal_places=18),
                )
            ),
            fee=models.Sum("total_fee"),
            pnl=models.functions.Coalesce(
                models.F("gross_pnl") - models.F("fee"), Decimal("0.00")
            ),
        )
        return result["pnl"]

    def get_avg_candles_per_position(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> float | None:
        timeframe_td = self.timeframe.timedelta()

        closed_positions = self.closed_positions
        if start_date:
            closed_positions = closed_positions.filter(closed_at__gte=start_date)
        if end_date:
            closed_positions = closed_positions.filter(closed_at__lt=end_date)

        if not closed_positions.exists():
            return None

        closed_positions = closed_positions.annotate(
            duration=models.ExpressionWrapper(
                models.F("closed_at") - models.F("opened_at"),
                output_field=models.DurationField(),
            )
        )
        avg_duration = closed_positions.aggregate(avg=models.Avg("duration"))["avg"]
        if avg_duration is None:
            return None
        return avg_duration / timeframe_td

    def get_balance(self, date: datetime | None = None) -> Decimal:
        if self.use_fixed_balance:
            return self.initial_balance
        return self.initial_balance + self.get_fact_pnl(end_date=date)

    def get_pnl_r2(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> float:
        """
        Возвращает R² (коэффициент детерминации) для cumulative PnL закрытых позиций.
        R² рассчитывается по линейной регрессии cumulative PnL по времени закрытия позиции.
        """
        closed_positions = self.closed_positions.order_by("closed_at")
        if start_date:
            closed_positions = closed_positions.filter(closed_at__gte=start_date)
        if end_date:
            closed_positions = closed_positions.filter(closed_at__lt=end_date)

        closed_positions = list(closed_positions.values("closed_at", "pnl"))
        if len(closed_positions) < 2:
            return 0.0

        cumulative_pnl = 0.0
        x = []
        y = []
        for pos in closed_positions:
            cumulative_pnl += float(pos["pnl"])
            x.append(pos["closed_at"].timestamp())
            y.append(cumulative_pnl)

        x = np.array(x)
        y = np.array(y)
        coeffs = np.polyfit(x, y, 1)
        slope, intercept = coeffs
        y_pred = slope * x + intercept
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = np.sum((y - np.mean(y)) ** 2)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0.0
        return r_squared

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
        self.clear_all_errors()

    def clear_all_errors(self):
        TraderError.objects.filter(trader=self).delete()

    def load(self, trader: DomainTrader) -> None:
        trader.signals = deque(
            reversed(
                [
                    signal.instantiate()
                    for signal in self.signals.select_related(
                        "candle",
                    ).order_by("-timestamp")[:1000]
                ]
            )
        )
        trader.positions = [
            pos.instantiate()
            for pos in self.opened_positions.select_related(
                "trader",
            ).order_by(
                "opened_at",
            )
        ]

    def sync_signals(self, trader: DomainTrader) -> None:
        if not trader.signals:
            return

        new_signals = [signal for signal in trader.signals if not signal.id]

        if not new_signals:
            return

        trader_signals = []
        for signal in new_signals:
            trader_signals.append(
                TraderSignal(
                    trader=self,
                    timestamp=signal.timestamp,
                    price=signal.price,
                    type=SignalType(signal.type),
                    data=signal.data,
                    candle_id=(
                        signal.candle.first_candle.id
                        if signal.candle and signal.candle.first_candle
                        else None
                    ),
                )
            )

        TraderSignal.objects.bulk_create(trader_signals)

    def sync_positions(self, trader: DomainTrader) -> None:
        if not trader.positions:
            return
        positions = [
            TraderPosition(
                trader=self,
                type=PositionType(position.type),
                status=PositionStatus(position.status),
                amount=position.amount,
                open_price=position.open_price,
                close_price=position.close_price,
                stop_loss=position.stop_loss,
                take_profit=position.take_profit,
                opened_at=position.opened_at,
                closed_at=position.closed_at,
                close_reason=(
                    PositionCloseReason(position.close_reason)
                    if position.close_reason
                    else None
                ),
                total_fee=position.total_fee,
            )
            for position in trader.positions
        ]

        TraderPosition.objects.bulk_create(
            positions,
            update_conflicts=True,
            update_fields=[
                "status",
                "open_price",
                "close_price",
                "stop_loss",
                "take_profit",
                "closed_at",
                "recalculated_at",
                "close_reason",
                "total_fee",
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
                status=OrderStatus(order.status),
                exchange_order_id=order.exchange_order_id,
                trading_pair=self.trading_pair,
                side=OrderSide(order.side),
                timestamp=order.timestamp,
                amount=order.amount,
                price=order.price,
                cost=order.cost,
                fee=order.fee,
            )
            for order in trader.orders
        ]
        ExchangeClientOrder.objects.bulk_create(
            exchange_client_orders,
        )
        client_orders = ExchangeClientOrder.objects.filter(
            exchange_client=self.exchange_client,
            trading_pair=self.trading_pair,
            exchange_order_id__in=[o.exchange_order_id for o in trader.orders],
        )

        # Оптимизация: загружаем все позиции одним запросом
        position_keys = [
            (pos.opened_at, pos.amount, PositionType(pos.type))
            for pos in trader.positions
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

        position_map = {}
        for pos in trader.positions:
            key = (pos.opened_at, pos.amount, PositionType(pos.type))
            orm_pos = orm_positions_map.get(key)
            for order in pos.orders:
                position_map[order.exchange_order_id] = orm_pos
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
            unique_fields=[
                "trader",
                "order",
                "position",
            ],
        )

    def sync_errors(self, trader: DomainTrader) -> None:
        new_errors = [error for error in trader.errors if not error.id]
        if not new_errors:
            return

        error_messages = "\n".join(
            f"{error.timestamp}: {error.type}: {error.message}" for error in new_errors
        )
        send_notification.delay(
            message=f"Трейдер {self.pk} столкнулся с ошибками:\n{error_messages}"
        )

        TraderError.objects.bulk_create(
            [
                TraderError(
                    trader=self,
                    message=error.message,
                    traceback=error.traceback or "",
                    type=error.type or "",
                )
                for error in new_errors
            ]
        )

        self.status = TraderStatus.ERROR
        self.save(update_fields=["status"])

    def sync(self, trader: DomainTrader) -> None:
        self.sync_signals(trader=trader)
        self.sync_positions(trader=trader)
        self.sync_orders(trader=trader)
        self.sync_errors(trader=trader)

    def has_existing_signal(self, candle: ExchangeCandle) -> bool:
        return self.signals.filter(timestamp=candle.timestamp).exists()

    def handle_candle(
        self,
        candle: ExchangeCandle,
    ) -> None:
        if self.has_existing_signal(candle=candle):
            return

        trader = self.instantiate()
        self.load(trader=trader)

        async def handle_candle(
            trader: DomainTrader,
            candle: DomainExchangeCandle,
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

    def check_opened_positions(
        self,
        candle: ExchangeCandle,
    ) -> None:
        trader = self.instantiate()
        self.load(trader=trader)

        async def check_opened_positions(
            trader: DomainTrader,
            candle: DomainExchangeCandle,
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
        end_date = timezone.now()
        start_date = end_date - timezone.timedelta(days=365)
        if self.status == TraderStatus.REBOOTING:
            return

        try:
            self.clear_all_data()
            self.last_reboot = timezone.now()
            self.status = TraderStatus.REBOOTING
            self.save(update_fields=["status", "last_reboot"])

            trader = self.instantiate()
            candle_iterator = self.candle_source.get_candle_iterator(
                start=start_date,
                end=end_date,
            )

            asyncio.run(trader.reboot(candle_iterator=candle_iterator))
            self.sync(trader=trader)
        except Exception as e:
            self.status = TraderStatus.ERROR
            TraderError.objects.create(
                trader=self,
                message=f"Ошибка при перезапуске трейдера: {e!s}",
                type=type(e).__name__,
            )
        else:
            self.status = TraderStatus.PAUSED
        finally:
            self.save(update_fields=["status", "last_reboot"])

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

    # def get_candle_at_time(self, dt: datetime = timezone.now()) -> Optional[Candle]:
    #     return (
    #         self.candles.filter(
    #             timestamp__lte=dt,
    #             timestamp__gt=dt - Timeframe(self.timeframe).timedelta(),
    #         )
    #         .order_by("-timestamp")
    #         .first()
    #     )

    def clean(self):
        super().clean()
        if Trader.objects.filter(exchange_client=self.exchange_client).count() > 50:
            raise ValidationError("Нельзя более 50 трейдеров для одного клиента.")


class TraderError(TimeStampedMixin, models.Model):
    """Ошибки трейдера."""

    trader = models.ForeignKey(
        Trader,
        on_delete=models.CASCADE,
        related_name="errors",
        verbose_name="Трейдер",
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
        verbose_name = "Ошибка трейдера"
        verbose_name_plural = "Ошибки трейдера"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["trader", "-created_at"],
                name="trader_error_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.trader.pk} | {self.type or 'Error'} | {self.created_at}"

    def instantiate(self) -> DomainTraderError:
        """Возвращает domain модель TraderError."""
        return DomainTraderError(
            id=self.pk,
            timestamp=self.created_at,
            message=self.message,
            type=self.type,
            traceback=self.traceback,
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

    candle = models.ForeignKey(
        ExchangeCandle,
        on_delete=models.CASCADE,
        related_name="signals",
        verbose_name="Свеча",
        null=True,
        blank=True,
        help_text="Свеча сигнала",
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
                ],
                name="unique_trader_signal",
            )
        ]
        indexes = [
            models.Index(
                fields=["trader", "-timestamp"],
                name="trader_signal_trader_ts_idx",
            ),
            models.Index(
                fields=["candle"],
                name="trader_signal_candle_idx",
            ),
            models.Index(
                fields=["trader", "type", "-timestamp"],
                name="trader_signal_type_idx",
            ),
        ]

    def __str__(self):
        return f"{self.trader} | {self.type} | {self.timestamp}"

    def get_candle_instantiate(self) -> DomainProviderCandle:
        """Восстанавливает domain candle из candle."""
        candle = self.candle.instantiate() if self.candle else None
        return DomainProviderCandle(
            id=candle.id if candle else None,
            timestamp=candle.timestamp if candle else None,
            open=candle.open if candle else None,
            high=candle.high if candle else None,
            low=candle.low if candle else None,
            close=candle.close if candle else None,
            volume=candle.volume if candle else None,
            first_candle=candle,
            second_candle=None,
        )

    def instantiate(self) -> DomainTraderSignal:
        return DomainTraderSignal(
            id=self.pk,
            timestamp=self.timestamp,
            candle=self.get_candle_instantiate(),
            type=DomainSignalType(self.type),
            data=self.data,
        )


class TraderPosition(TimeStampedMixin, models.Model):
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
        blank=True,
        default="",
        choices=PositionCloseReason.choices,
        verbose_name="Причина закрытия",
        help_text="Причина закрытия позиции, если она была закрыта.",
    )
    total_fee = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        default=Decimal("0.00"),
        verbose_name="Общая комиссия",
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
                name="unique_position",
            )
        ]
        indexes = [
            # Critical: get_opened_positions / get_closed_positions queries
            models.Index(
                fields=["trader", "status", "opened_at"],
                name="trader_pos_trader_status_idx",
            ),
            # For closed positions analytics (win_rate, pnl_r2, etc.)
            models.Index(
                fields=["trader", "status", "closed_at"],
                name="trader_pos_closed_at_idx",
            ),
            # For filtering by position type
            models.Index(
                fields=["trader", "type", "status"],
                name="trader_pos_type_status_idx",
            ),
            # For time-range queries with status
            models.Index(
                fields=["status", "closed_at"],
                name="trader_pos_status_closed_idx",
            ),
        ]

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

    def instantiate(self) -> DomainTraderPosition:
        return DomainTraderPosition(
            id=self.pk,
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
            close_reason=(
                DomainPositionCloseReason(self.close_reason)
                if self.close_reason
                else None
            ),
            total_fee=self.total_fee,
        )

    @property
    def open_cost(self) -> Decimal | None:
        """Open Cost."""
        return self.instantiate().open_cost

    @property
    def close_cost(self) -> Decimal | None:
        """Close Cost."""
        return self.instantiate().close_cost

    @property
    def stop_loss_pct(self) -> Decimal | None:
        """Stop Loss Percentage."""
        return self.instantiate().stop_loss_pct

    @property
    def take_profit_pct(self) -> Decimal | None:
        """Take Profit Percentage."""
        return self.instantiate().take_profit_pct

    @property
    def pnl(self) -> Decimal | None:
        """Profit and Loss."""
        return self.instantiate().pnl

    def pnl_pct(self) -> Decimal | None:
        """Profit and Loss Percentage."""
        return self.instantiate().pnl_pct

    @property
    def rr(self) -> Decimal | None:
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
            update_fields=[
                "amount",
                "open_price",
                "close_price",
                "recalculated_at",
            ]
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
                fields=[
                    "trader",
                    "order",
                    "position",
                ],
                name="unique_trader_order",
            )
        ]

    def __str__(self):
        return f"{self.trader} | {self.order.side} {self.order.amount} @ {self.order.price}"

    def clean(self) -> None:
        super().clean()

        if self.position and self.position.trader.pk != self.trader.pk:
            raise ValidationError("Позиция должна принадлежать тому же трейдеру.")

    def instantiate(self) -> DomainExchangeClientOrder:
        return self.order.instantiate()


class ArbitrageTrader(TimeStampedMixin, models.Model):
    """Арбитражный трейдер с двумя клиентами бирж."""

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
    first_candle_source = models.ForeignKey(
        CandleSource,
        on_delete=models.CASCADE,
        related_name="arbitrage_first_traders",
        verbose_name="Первый источник свечей",
        limit_choices_to={"is_active": True},
        help_text="Первый источник свечей для арбитражного трейдера.",
    )
    second_candle_source = models.ForeignKey(
        CandleSource,
        on_delete=models.CASCADE,
        related_name="arbitrage_second_traders",
        verbose_name="Второй источник свечей",
        limit_choices_to={"is_active": True},
        help_text="Второй источник свечей для арбитражного трейдера.",
    )
    first_exchange_client = models.ForeignKey(
        ExchangeClient,
        on_delete=models.CASCADE,
        related_name="arbitrage_first_traders",
        verbose_name="Первый клиент биржи",
        limit_choices_to={"is_active": True},
        help_text="Первый клиент биржи для арбитражного трейдера.",
    )
    second_exchange_client = models.ForeignKey(
        ExchangeClient,
        on_delete=models.CASCADE,
        related_name="arbitrage_second_traders",
        verbose_name="Второй клиент биржи",
        limit_choices_to={"is_active": True},
        help_text="Второй клиент биржи для арбитражного трейдера.",
    )
    strategy = models.ForeignKey(
        ArbitrageStrategy,
        on_delete=models.CASCADE,
        verbose_name="Арбитражная стратегия",
        limit_choices_to={"is_active": True},
        help_text="Выберите арбитражную стратегию, которую будет использовать трейдер.",
    )
    risk_manager = models.ForeignKey(
        RiskManager,
        on_delete=models.CASCADE,
        verbose_name="Риск-менеджер",
        limit_choices_to={"is_active": True},
        help_text="Выберите риск-менеджер, который будет использовать трейдер.",
    )
    use_fixed_balance = models.BooleanField(
        default=True,
        verbose_name="Использовать фиксированный баланс",
        help_text="Если выбрано, трейдер будет использовать фиксированный баланс.",
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
        verbose_name="Проверять просадку",
        help_text="Если выбрано, трейдер будет проверять максимальную просадку.",
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
        help_text="Если выбрано, трейдер будет создавать новые ордера.",
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
        help_text="Если выбрано, трейдер будет закрывать позицию при противоположном сигнале.",
    )
    close_position_by_strategy = models.BooleanField(
        default=True,
        verbose_name="Закрывать позиции по сигналу стратегии",
        help_text="Если выбрано, трейдер будет закрывать позицию при сигнале от стратегии.",
    )
    last_reboot = models.DateTimeField(
        verbose_name="Последний перезапуск",
        null=True,
        blank=True,
        help_text="Дата и время последнего перезапуска трейдера.",
    )

    class Meta:
        verbose_name = "Арбитражный трейдер"
        verbose_name_plural = "Арбитражные трейдеры"

    def __str__(self) -> str:
        return (
            f"{self.get_status_display()} | {self.pk} | "
            f"{self.first_exchange_client} <-> {self.second_exchange_client} | "
            f"{self.strategy}"
        )

    @property
    def timeframe(self) -> Timeframe:
        """Возвращает timeframe трейдера."""
        return Timeframe(self.first_candle_source.timeframe)

    @property
    def trading_pair(self) -> TradingPair | ExchangeTradingPair:
        """Возвращает торговую пару трейдера."""
        return self.first_candle_source.trading_pair

    def clean(self) -> None:
        super().clean()
        if self.first_exchange_client.pk == self.second_exchange_client.pk:
            raise ValidationError("Первый и второй клиенты биржи должны быть разными.")
        if self.first_exchange_client.exchange == self.second_exchange_client.exchange:
            raise ValidationError("Клиенты должны быть на разных биржах.")

    def get_opened_positions(self) -> models.QuerySet["ArbitrageTraderPosition"]:
        """Возвращает открытые позиции."""
        return self.positions.filter(status=PositionStatus.OPENED)

    def get_closed_positions(self) -> models.QuerySet["ArbitrageTraderPosition"]:
        """Возвращает закрытые позиции."""
        return self.positions.filter(status=PositionStatus.CLOSED)

    @property
    def opened_positions(self) -> models.QuerySet["ArbitrageTraderPosition"]:
        """Свойство для доступа к открытым позициям."""
        return self.get_opened_positions()

    @property
    def closed_positions(self) -> models.QuerySet["ArbitrageTraderPosition"]:
        """Свойство для доступа к закрытым позициям."""
        return self.get_closed_positions()

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

        orders = ArbitrageTraderOrder.objects.filter(position__in=positions)

        # Суммируем PnL по первым ордерам
        first_pnl = orders.aggregate(
            gross_pnl=models.Sum(
                models.Case(
                    models.When(
                        first_order__side=OrderSide.SELL,
                        then=models.F("first_order__price")
                        * models.F("first_order__amount"),
                    ),
                    models.When(
                        first_order__side=OrderSide.BUY,
                        then=-models.F("first_order__price")
                        * models.F("first_order__amount"),
                    ),
                    default=Decimal("0.00"),
                    output_field=models.DecimalField(max_digits=30, decimal_places=18),
                )
            ),
            fee=models.Sum("first_order__fee"),
        )

        # Суммируем PnL по вторым ордерам
        second_pnl = orders.aggregate(
            gross_pnl=models.Sum(
                models.Case(
                    models.When(
                        second_order__side=OrderSide.SELL,
                        then=models.F("second_order__price")
                        * models.F("second_order__amount"),
                    ),
                    models.When(
                        second_order__side=OrderSide.BUY,
                        then=-models.F("second_order__price")
                        * models.F("second_order__amount"),
                    ),
                    default=Decimal("0.00"),
                    output_field=models.DecimalField(max_digits=30, decimal_places=18),
                )
            ),
            fee=models.Sum("second_order__fee"),
        )

        gross_pnl = (first_pnl["gross_pnl"] or Decimal("0.00")) + (
            second_pnl["gross_pnl"] or Decimal("0.00")
        )
        total_fee = (first_pnl["fee"] or Decimal("0.00")) + (
            second_pnl["fee"] or Decimal("0.00")
        )
        return gross_pnl - total_fee

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

        result = positions.aggregate(
            gross_pnl=models.Sum(
                models.Case(
                    models.When(
                        type=PositionType.LONG,
                        then=models.ExpressionWrapper(
                            (models.F("close_price") - models.F("open_price"))
                            * models.F("amount"),
                            output_field=models.DecimalField(
                                max_digits=30, decimal_places=18
                            ),
                        ),
                    ),
                    models.When(
                        type=PositionType.SHORT,
                        then=models.ExpressionWrapper(
                            (models.F("open_price") - models.F("close_price"))
                            * models.F("amount"),
                            output_field=models.DecimalField(
                                max_digits=30, decimal_places=18
                            ),
                        ),
                    ),
                    default=Decimal("0.00"),
                    output_field=models.DecimalField(max_digits=30, decimal_places=18),
                )
            ),
            fee=models.Sum("total_fee"),
            pnl=models.functions.Coalesce(
                models.F("gross_pnl") - models.F("fee"), Decimal("0.00")
            ),
        )
        return result["pnl"] or Decimal("0.00")

    def load(self, trader: DomainArbitrageTrader) -> None:
        """Загружает состояние domain трейдера из базы данных."""
        trader.signals = deque(
            reversed(
                [
                    signal.instantiate()
                    for signal in self.signals.select_related(
                        "first_candle",
                        "second_candle",
                    ).order_by("-timestamp")[:1000]
                ]
            )
        )
        trader.positions = [
            pos.instantiate()
            for pos in self.opened_positions.select_related(
                "trader",
            ).order_by(
                "opened_at",
            )
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
                    first_price=signal.first_price,
                    second_price=signal.second_price,
                    first_type=SignalType(signal.first_type),
                    second_type=SignalType(signal.second_type),
                    data=signal.data,
                    first_candle_id=(
                        signal.candle.first_candle.id
                        if signal.candle.first_candle
                        else None
                    ),
                    second_candle_id=(
                        signal.candle.second_candle.id
                        if signal.candle and signal.candle.second_candle
                        else None
                    ),
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
                type=PositionType(position.type),
                first_type=PositionType(position.first_type),
                second_type=PositionType(position.second_type),
                status=PositionStatus(position.status),
                amount=position.amount,
                first_open_price=position.first_open_price,
                first_close_price=position.first_close_price,
                second_open_price=position.second_open_price,
                second_close_price=position.second_close_price,
                opened_at=position.opened_at,
                closed_at=position.closed_at,
                close_reason=(
                    PositionCloseReason(position.close_reason)
                    if position.close_reason
                    else None
                ),
                total_fee=position.total_fee,
            )
            for position in trader.positions
        ]

        ArbitrageTraderPosition.objects.bulk_create(
            positions,
            update_conflicts=True,
            update_fields=[
                "status",
                "first_type",
                "second_type",
                "first_open_price",
                "first_close_price",
                "second_open_price",
                "second_close_price",
                "closed_at",
                "close_reason",
                "total_fee",
            ],
            unique_fields=[
                "trader",
                "opened_at",
                "type",
                "amount",
            ],
        )

    def clear_all_data(self) -> None:
        """Очищает все данные трейдера: сигналы, позиции, ордера и ошибки."""
        self.signals.all().delete()
        self.positions.all().delete()
        self.orders.all().delete()
        self.errors.all().delete()

    def clear_all_errors(self) -> None:
        """Удаляет все ошибки арбитражного трейдера."""
        self.errors.all().delete()

    def sync_orders(self, trader: DomainArbitrageTrader) -> None:
        """Сохраняет ордера в базу данных."""
        if not trader.orders:
            return

        # Создаем ExchangeClientOrder для обоих exchange_client
        first_exchange_client_orders = []
        second_exchange_client_orders = []

        for first_order, second_order, _ in trader.orders:
            first_exchange_client_orders.append(
                ExchangeClientOrder(
                    exchange_client=self.first_exchange_client,
                    status=OrderStatus(first_order.status),
                    exchange_order_id=first_order.exchange_order_id,
                    trading_pair=self.trading_pair,
                    side=OrderSide(first_order.side),
                    timestamp=first_order.timestamp,
                    amount=first_order.amount,
                    price=first_order.price,
                    cost=first_order.cost,
                    fee=first_order.fee,
                )
            )
            second_exchange_client_orders.append(
                ExchangeClientOrder(
                    exchange_client=self.second_exchange_client,
                    status=OrderStatus(second_order.status),
                    exchange_order_id=second_order.exchange_order_id,
                    trading_pair=self.trading_pair,
                    side=OrderSide(second_order.side),
                    timestamp=second_order.timestamp,
                    amount=second_order.amount,
                    price=second_order.price,
                    cost=second_order.cost,
                    fee=second_order.fee,
                )
            )

        ExchangeClientOrder.objects.bulk_create(first_exchange_client_orders)
        ExchangeClientOrder.objects.bulk_create(second_exchange_client_orders)

        # Получаем созданные ордера
        first_client_orders = ExchangeClientOrder.objects.filter(
            exchange_client=self.first_exchange_client,
            trading_pair=self.trading_pair,
            exchange_order_id__in=[o[0].exchange_order_id for o in trader.orders],
        )
        second_client_orders = ExchangeClientOrder.objects.filter(
            exchange_client=self.second_exchange_client,
            trading_pair=self.trading_pair,
            exchange_order_id__in=[o[1].exchange_order_id for o in trader.orders],
        )

        # Создаем map для быстрого поиска
        first_orders_map = {o.exchange_order_id: o for o in first_client_orders}
        second_orders_map = {o.exchange_order_id: o for o in second_client_orders}

        # Получаем позиции
        position_keys = [
            (pos.opened_at, pos.amount, PositionType(pos.type))
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
        for first_order, second_order, position in trader.orders:
            key = (position.opened_at, position.amount, PositionType(position.type))
            orm_pos = orm_positions_map.get(key)

            if orm_pos:
                first_order_obj = first_orders_map.get(first_order.exchange_order_id)
                second_order_obj = second_orders_map.get(second_order.exchange_order_id)

                if first_order_obj and second_order_obj:
                    trader_orders.append(
                        ArbitrageTraderOrder(
                            trader=self,
                            first_order=first_order_obj,
                            second_order=second_order_obj,
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

        self.status = TraderStatus.ERROR
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
        """Возвращает итератор свечей для арбитражного трейдера."""
        first_candles = self.first_candle_source.get_candle_iterator(
            start=start, end=end
        )
        second_candles = self.second_candle_source.get_candle_iterator(
            start=start, end=end
        )
        for first_candle, second_candle in zip_longest(first_candles, second_candles):
            if first_candle.timestamp != second_candle.timestamp:
                ArbitrageTraderError.objects.create(
                    trader=self,
                    message=(
                        f"Рассинхронизация свечей: first={first_candle.timestamp}, "
                        f"second={second_candle.timestamp}"
                    ),
                    type="CandleDesyncError",
                )
                self.status = TraderStatus.ERROR
                self.save(update_fields=["status"])
                return
            yield first_candle, second_candle

    def reboot(self) -> None:
        """Перезапускает арбитражного трейдера на исторических данных."""
        end_date = timezone.now()
        start_date = end_date - timezone.timedelta(days=365)

        if self.status == TraderStatus.REBOOTING:
            return

        try:
            self.clear_all_data()
            self.last_reboot = timezone.now()
            self.status = TraderStatus.REBOOTING
            self.save(update_fields=["status", "last_reboot"])

            trader = self.instantiate()
            candle_iterator = self.get_candle_iterator(
                start=start_date,
                end=end_date,
            )

            asyncio.run(trader.reboot(candle_iterator=candle_iterator))
            self.sync(trader=trader)
        except Exception as e:
            self.status = TraderStatus.ERROR
            ArbitrageTraderError.objects.create(
                trader=self,
                message=f"Ошибка при перезапуске трейдера: {e!s}",
                type=type(e).__name__,
            )
        else:
            self.status = TraderStatus.PAUSED
        finally:
            self.save(update_fields=["status", "last_reboot"])

    def instantiate(
        self,
        domain_first_exchange_client: AbstractExchangeClient | None = None,
        domain_second_exchange_client: AbstractExchangeClient | None = None,
    ) -> DomainArbitrageTrader:
        """Создает domain объект ArbitrageTrader из ORM модели."""
        return DomainArbitrageTrader(
            trading_pair=self.trading_pair.instantiate(),
            timeframe=DomainTimeframe(self.timeframe),
            first_exchange_client=(
                domain_first_exchange_client or self.first_exchange_client.instantiate()
            ),
            second_exchange_client=(
                domain_second_exchange_client
                or self.second_exchange_client.instantiate()
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
        verbose_name = "Ошибка арбитражного трейдера"
        verbose_name_plural = "Ошибки арбитражного трейдера"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["trader", "-created_at"],
                name="arb_trader_error_idx",
            ),
        ]

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
        verbose_name="Время",
        db_index=True,
    )
    first_price = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        verbose_name="Цена (первая биржа)",
    )
    second_price = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        verbose_name="Цена (вторая биржа)",
    )
    first_type = models.CharField(
        max_length=10,
        choices=SignalType.choices,
        verbose_name="Тип (первая биржа)",
    )
    second_type = models.CharField(
        max_length=10,
        choices=SignalType.choices,
        verbose_name="Тип (вторая биржа)",
    )
    first_candle = models.ForeignKey(
        ExchangeCandle,
        on_delete=models.CASCADE,
        related_name="arbitrage_first_signals",
        verbose_name="Первая свеча",
        null=True,
        blank=True,
        help_text="Первая свеча сигнала",
    )
    second_candle = models.ForeignKey(
        ExchangeCandle,
        on_delete=models.CASCADE,
        related_name="arbitrage_second_signals",
        verbose_name="Вторая свеча",
        null=True,
        blank=True,
        help_text="Вторая свеча для арбитражного сигнала",
    )

    data = models.JSONField()

    class Meta:
        verbose_name = "Сигнал арбитражного трейдера"
        verbose_name_plural = "Сигналы арбитражного трейдера"
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "trader",
                    "timestamp",
                    "first_type",
                    "second_type",
                ],
                name="unique_arb_trader_signal",
            )
        ]
        indexes = [
            models.Index(
                fields=["trader", "-timestamp"],
                name="arb_trader_signal_ts_idx",
            ),
            models.Index(
                fields=["first_candle", "second_candle"],
                name="arb_trader_signal_candles_idx",
            ),
            models.Index(
                fields=["trader", "first_type", "-timestamp"],
                name="arb_trader_signal_type_idx",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.trader.pk} | {self.get_first_type_display()}/{self.get_second_type_display()} | "
            f"{self.timestamp}"
        )

    def get_candle_instantiate(self) -> DomainProviderCandle:
        """Восстанавливает domain candle из first_candle и second_candle."""
        first_candle = self.first_candle.instantiate() if self.first_candle else None
        second_candle = self.second_candle.instantiate() if self.second_candle else None
        return DomainProviderCandle(
            id=first_candle.id if first_candle else None,
            timestamp=first_candle.timestamp if first_candle else None,
            open=first_candle.open if first_candle else None,
            high=first_candle.high if first_candle else None,
            low=first_candle.low if first_candle else None,
            close=first_candle.close if first_candle else None,
            volume=first_candle.volume if first_candle else None,
            first_candle=first_candle,
            second_candle=second_candle,
        )

    def instantiate(self) -> DomainArbitrageTraderSignal:
        """Возвращает domain модель ArbitrageTraderSignal."""
        return DomainArbitrageTraderSignal(
            id=self.pk,
            timestamp=self.timestamp,
            first_type=DomainSignalType(self.first_type),
            second_type=DomainSignalType(self.second_type),
            first_price=self.first_price,
            second_price=self.second_price,
            candle=self.get_candle_instantiate(),
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
        choices=PositionType.choices,
        verbose_name="Тип",
    )
    first_type = models.CharField(
        max_length=10,
        choices=PositionType.choices,
        verbose_name="Тип (первая биржа)",
    )
    second_type = models.CharField(
        max_length=10,
        choices=PositionType.choices,
        verbose_name="Тип (вторая биржа)",
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
    first_open_price = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        null=True,
        blank=True,
        verbose_name="Цена открытия (первая биржа)",
    )
    first_close_price = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        null=True,
        blank=True,
        verbose_name="Цена закрытия (первая биржа)",
    )
    second_open_price = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        null=True,
        blank=True,
        verbose_name="Цена открытия (вторая биржа)",
    )
    second_close_price = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        null=True,
        blank=True,
        verbose_name="Цена закрытия (вторая биржа)",
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
    close_reason = models.CharField(
        max_length=20,
        blank=True,
        default="",
        choices=PositionCloseReason.choices,
        verbose_name="Причина закрытия",
        help_text="Причина закрытия позиции, если она была закрыта.",
    )
    total_fee = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        default=Decimal("0.00"),
        verbose_name="Общая комиссия",
    )

    class Meta:
        verbose_name = "Позиция арбитражного трейдера"
        verbose_name_plural = "Позиции арбитражного трейдера"
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
        indexes = [
            models.Index(
                fields=["trader", "status", "opened_at"],
                name="arb_trader_pos_status_idx",
            ),
            models.Index(
                fields=["trader", "status", "closed_at"],
                name="arb_trader_pos_closed_idx",
            ),
            models.Index(
                fields=["trader", "type", "status"],
                name="arb_trader_pos_type_idx",
            ),
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
            first_type=DomainPositionType(self.first_type),
            second_type=DomainPositionType(self.second_type),
            status=DomainPositionStatus(self.status),
            amount=self.amount,
            first_open_price=self.first_open_price,
            first_close_price=self.first_close_price,
            second_open_price=self.second_open_price,
            second_close_price=self.second_close_price,
            opened_at=self.opened_at,
            closed_at=self.closed_at,
            close_reason=(
                DomainPositionCloseReason(self.close_reason)
                if self.close_reason
                else None
            ),
            total_fee=self.total_fee,
        )

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
    first_order = models.OneToOneField(
        ExchangeClientOrder,
        on_delete=models.CASCADE,
        related_name="arbitrage_first_orders",
        verbose_name="Первый ордер",
    )
    second_order = models.OneToOneField(
        ExchangeClientOrder,
        on_delete=models.CASCADE,
        related_name="arbitrage_second_orders",
        verbose_name="Второй ордер",
    )
    position = models.ForeignKey(
        ArbitrageTraderPosition,
        on_delete=models.CASCADE,
        verbose_name="Позиция трейдера",
    )

    class Meta:
        verbose_name = "Ордер арбитражного трейдера"
        verbose_name_plural = "Ордера арбитражного трейдера"
        constraints = [
            models.UniqueConstraint(
                fields=["trader", "first_order", "second_order", "position"],
                name="unique_arbitrage_trader_order",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.trader} | "
            f"First: {self.first_order.side} {self.first_order.amount} @ {self.first_order.price} | "
            f"Second: {self.second_order.side} {self.second_order.amount} @ {self.second_order.price}"
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
        return (self.first_order.instantiate(), self.second_order.instantiate())
