import asyncio
from collections import deque
from datetime import datetime
from decimal import Decimal
from typing import Optional

import numpy as np
from candle_providers.models import CandleProvider
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
from django.db import models
from django.forms import ValidationError
from django.urls import reverse
from django.utils import timezone
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
from strategies.domain import SignalType as DomainSignalType
from strategies.domain import TraderSignal as DomainTraderSignal
from strategies.models import Strategy
from telegram_bots.tasks import send_notification
from traders.domain import Trader as DomainTrader
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
    candle_provider = models.ForeignKey(
        CandleProvider,
        on_delete=models.CASCADE,
        verbose_name="Провайдер свечей",
        limit_choices_to={"is_active": True},
        help_text="Выберите провайдер свечей (может быть exchange или arbitrage).",
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

    @property
    def timeframe(self) -> Timeframe:
        """Возвращает timeframe трейдера."""
        return Timeframe(self.candle_provider.timeframe)

    @property
    def trading_pair(self) -> TradingPair | ExchangeTradingPair:
        """Возвращает торговую пару трейдера."""
        exchange_trading_pair = ExchangeTradingPair.objects.filter(
            exchange=self.exchange_client.exchange,
            trading_pair=self.candle_provider.trading_pair,
        ).first()
        return self.candle_provider.trading_pair or exchange_trading_pair

    class Meta:
        verbose_name = "Трейдер"
        verbose_name_plural = "Трейдеры"
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "candle_provider",
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

    def instantiate(
        self,
        domain_exchange_client: Optional[AbstractExchangeClient] = None,
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
        return self.candle_provider.instantiate().get_last_candles(count)

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
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
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
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
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
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
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
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Optional[float]:
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

    def get_balance(self, date: Optional[datetime] = None) -> Decimal:
        if self.use_fixed_balance:
            return self.initial_balance
        return self.initial_balance + self.get_fact_pnl(end_date=date)

    def get_pnl_r2(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
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
        self.errors = None
        self.save(update_fields=["errors"])

    def load(self, trader: DomainTrader) -> None:
        trader.signals = deque(
            reversed(
                list(
                    signal.instantiate()
                    for signal in self.signals.select_related(
                        "primary_candle",
                        "secondary_candle",
                    ).order_by("-timestamp")[:1000]
                )
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
                    primary_candle_id=(
                        signal.candle.primary_candle.id
                        if signal.candle.primary_candle
                        else None
                    ),
                    secondary_candle_id=(
                        signal.candle.secondary_candle.id
                        if signal.candle and signal.candle.secondary_candle
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
        new_errors = trader.errors.strip() if trader.errors else ""
        if not new_errors:
            return
        send_notification.delay(
            message=f"Трейдер {self.pk} столкнулся с ошибками:\n{new_errors}"
        )
        self.errors = f"{self.errors}\n{new_errors}" if self.errors else new_errors
        self.last_error = trader.last_error
        self.status = TraderStatus.ERROR
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
            candle_provider = self.candle_provider.instantiate()
            candle_iterator = candle_provider.get_candle_iterator(
                start=start_date,
                end=end_date,
            )

            asyncio.run(trader.reboot(candle_iterator=candle_iterator))
            self.sync(trader=trader)
        except Exception as e:
            self.status = TraderStatus.ERROR
            self.errors = f"{self.errors}\nОшибка при перезапуске трейдера: {str(e)}"
            self.last_error = timezone.now()
        else:
            self.status = TraderStatus.PAUSED
        finally:
            self.save(update_fields=["status", "last_reboot", "errors", "last_error"])

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

    primary_candle = models.ForeignKey(
        ExchangeCandle,
        on_delete=models.CASCADE,
        related_name="primary_signals",
        verbose_name="Основная свеча",
        null=True,
        blank=True,
        help_text="Основная свеча сигнала (всегда присутствует)",
    )
    secondary_candle = models.ForeignKey(
        ExchangeCandle,
        on_delete=models.CASCADE,
        related_name="secondary_signals",
        verbose_name="Вторичная свеча",
        null=True,
        blank=True,
        help_text="Вторичная свеча (только для арбитражных сигналов)",
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
                fields=["primary_candle", "secondary_candle"],
                name="trader_signal_candles_idx",
            ),
            models.Index(
                fields=["trader", "type", "-timestamp"],
                name="trader_signal_type_idx",
            ),
        ]

    def get_candle_instantiate(self) -> DomainExchangeCandle:
        """Восстанавливает domain candle из primary_candle и secondary_candle."""
        domain_candle_provider = self.trader.candle_provider.instantiate()
        primary_domain = self.primary_candle.instantiate()
        if self.secondary_candle:
            secondary_domain = self.secondary_candle.instantiate()
            return domain_candle_provider.get_candle(primary_domain, secondary_domain)
        return domain_candle_provider.get_candle(primary_domain)

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
        null=True,
        blank=True,
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

    def clean(self) -> None:
        super().clean()

        if self.position and self.position.trader.pk != self.trader.pk:
            raise ValidationError("Позиция должна принадлежать тому же трейдеру.")

    def __str__(self):
        return f"{self.trader} | {self.order.side} {self.order.amount} @ {self.order.price}"

    def instantiate(self) -> DomainExchangeClientOrder:
        return self.order.instantiate()


class ArbitrageTrader(TimeStampedMixin, models.Model):
    """Арбитражный трейдер, связывающий два обычных трейдера на разных биржах."""

    first_trader = models.ForeignKey(
        Trader,
        on_delete=models.CASCADE,
        related_name="arbitrage_first_trader",
        verbose_name="Первый трейдер",
    )
    second_trader = models.ForeignKey(
        Trader,
        on_delete=models.CASCADE,
        related_name="arbitrage_second_trader",
        verbose_name="Второй трейдер",
    )

    class Meta:
        verbose_name = "Арбитражный трейдер"
        verbose_name_plural = "Арбитражные трейдеры"

    def clean(self) -> None:
        super().clean()
        if self.first_trader.pk == self.second_trader.pk:
            raise ValidationError("Первый и второй трейдеры должны быть разными.")
        if (
            self.first_trader.exchange_client.exchange
            == self.second_trader.exchange_client.exchange
        ):
            raise ValidationError("Трейдеры должны быть на разных биржах.")
        if self.first_trader.trading_pair != self.second_trader.trading_pair:
            raise ValidationError(
                "Трейдеры должны торговать одной и той же торговой парой."
            )
        if self.first_trader.timeframe != self.second_trader.timeframe:
            raise ValidationError("Трейдеры должны использовать одинаковый таймфрейм.")
        if self.first_trader.candle_provider != self.second_trader.candle_provider:
            raise ValidationError(
                "Трейдеры должны использовать один и тот же провайдер свечей."
            )

    def __str__(self):
        return f"Арбитраж: {self.first_trader} <-> {self.second_trader}"
