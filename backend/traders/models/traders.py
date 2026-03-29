import asyncio
import traceback
from collections import deque
from datetime import datetime, timedelta
from decimal import Decimal

import numpy as np
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.forms import ValidationError
from django.urls import reverse
from django.utils import timezone

from candle_sources.models import CandleSource
from core.utils.mixins import BaseErrorMixin, TimeStampedMixin
from exchange_clients.domain import AbstractExchangeClient
from exchange_clients.domain import ExchangeClientOrder as DomainExchangeClientOrder
from exchange_clients.models import ExchangeClient, ExchangeClientOrder
from exchange_clients.schemas import OrderSide, OrderStatus
from exchanges.domain import ExchangeCandle as DomainExchangeCandle
from exchanges.domain import Timeframe as DomainTimeframe
from exchanges.models import ExchangeCandle, ExchangeTradingPair, TradingPair
from exchanges.schemas import Timeframe
from telegram_bots.tasks import send_notification
from traders.domain import Trader as DomainTrader
from traders.domain import TraderError as DomainTraderError
from traders.domain import TraderPosition as DomainTraderPosition
from traders.domain import TraderStatus as DomainTraderStatus
from traders.domain.schemas import PositionCloseReason as DomainPositionCloseReason
from traders.domain.schemas import PositionStatus as DomainPositionStatus
from traders.domain.schemas import PositionType as DomainPositionType
from traders.domain.schemas import SignalType as DomainSignalType
from traders.domain.schemas import TraderSignal as DomainTraderSignal
from traders.schemas import (
    CandlesLookbackCount,
    PositionCloseReason,
    PositionStatus,
    PositionType,
    SignalType,
    TraderStatus,
)

from .risk_managers import RiskManager
from .strategies import Strategy


class Trader(TimeStampedMixin, models.Model):
    favorite = models.BooleanField(
        default=False,
        verbose_name="Избранный",
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
    )
    exchange_client = models.ForeignKey(
        ExchangeClient,
        on_delete=models.CASCADE,
        related_name="traders",
        verbose_name="Клиент биржи",
        limit_choices_to={"is_active": True},
    )
    strategy = models.ForeignKey(
        Strategy,
        on_delete=models.CASCADE,
        verbose_name="Стратегия",
        limit_choices_to={"is_active": True},
    )
    risk_manager = models.ForeignKey(
        RiskManager,
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
        choices=CandlesLookbackCount.choices,
        default=CandlesLookbackCount.COUNT_1000,
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
    last_reboot = models.DateTimeField(  # type: ignore[misc]
        verbose_name="Последний перезапуск",
        null=True,
        blank=True,
    )

    # --- Meta, str, url ---

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

    # --- Свойства ---

    @property
    def is_ready(self) -> bool:
        return all(
            [
                self.candle_source.is_ready,
                self.exchange_client.is_ready,
                self.strategy.is_ready,
                self.risk_manager.is_ready,
            ]
        )

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

    # --- Валидация ---

    def clean(self):
        super().clean()
        ec = self.exchange_client
        total = (
            ec.traders.count()
            + ec.arbitrage_left_traders.count()
            + ec.arbitrage_right_traders.count()
        )
        if total > 50:
            raise ValidationError("Нельзя более 50 трейдеров для одного клиента.")
        if self.candle_source.exchange_client.exchange != self.exchange_client.exchange:
            raise ValidationError(
                "Биржа источника свечей должна совпадать с биржей клиента."
            )

    # --- Запросы позиций и ордеров ---

    def get_opened_positions(self) -> models.QuerySet["TraderPosition"]:
        return self.positions.filter(status=PositionStatus.OPENED)

    def get_closed_positions(self) -> models.QuerySet["TraderPosition"]:
        return self.positions.filter(status=PositionStatus.CLOSED)

    @property
    def opened_positions(self) -> models.QuerySet["TraderPosition"]:
        return self.get_opened_positions()

    @property
    def closed_positions(self) -> models.QuerySet["TraderPosition"]:
        return self.get_closed_positions()

    def get_total_positions_count(self) -> int:
        return self.positions.count()

    def get_total_positions_count_with_orders(self) -> int:
        return self.positions.filter(orders__isnull=False).distinct().count()

    def get_total_orders_count(self) -> int:
        return self.orders.count()

    # --- Запросы свечей ---

    def get_candles(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ):
        """Получить свечи за диапазон дат."""
        return self.candle_source.get_candles(start, end)

    def get_candle_iterator(
        self, start: datetime | None = None, end: datetime | None = None
    ):
        """Возвращает итератор domain свечей для трейдера."""
        for candle in self.candle_source.get_candle_iterator(start=start, end=end):
            yield candle.instantiate()

    def get_last_candle(self) -> ExchangeCandle | None:
        """Получить последнюю свечу для трейдера."""
        return self.candle_source.get_last_candle()

    def get_last_candles(self, count: int = 1000):
        """Получить последние N свечей для трейдера."""
        return self.candle_source.get_last_candles(count=count)

    # --- PnL аннотации и статистика ---

    @staticmethod
    def theoretical_pnl_annotation():
        """SQL-аннотация для теоретического PnL позиции."""
        sign = models.Case(
            models.When(type=PositionType.LONG, then=models.Value(1)),
            models.When(type=PositionType.SHORT, then=models.Value(-1)),
            default=models.Value(0),
            output_field=models.SmallIntegerField(),
        )
        return sign * (models.F("close_price") - models.F("open_price")) * models.F(
            "amount"
        ) - models.F("total_fee")

    @staticmethod
    def fact_pnl_annotation():
        """SQL-аннотация для фактического PnL по ордерам."""
        sign = models.Case(
            models.When(order__side=OrderSide.SELL, then=models.Value(1)),
            models.When(order__side=OrderSide.BUY, then=models.Value(-1)),
            default=models.Value(0),
            output_field=models.SmallIntegerField(),
        )
        return sign * models.F("order__price") * models.F("order__amount") - models.F(
            "order__fee"
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

        wins = (
            positions.annotate(computed_pnl=self.theoretical_pnl_annotation())
            .filter(computed_pnl__gt=0)
            .count()
        )
        return wins / total

    def get_fact_pnl(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> Decimal:
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
        positions = self.closed_positions
        if start_date:
            positions = positions.filter(closed_at__gte=start_date)
        if end_date:
            positions = positions.filter(closed_at__lt=end_date)

        result = positions.aggregate(
            pnl=models.Sum(self.theoretical_pnl_annotation()),
        )
        return result["pnl"] or Decimal("0.00")

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

    def instantiate(
        self,
        domain_exchange_client: AbstractExchangeClient | None = None,
    ) -> DomainTrader:
        return DomainTrader(
            trading_pair=self.trading_pair.instantiate(
                exchange=self.exchange_client.exchange
            ),
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
            candles_lookback_count=self.candles_lookback_count,
            trail_stop_enabled=self.trail_stop_enabled,
            create_new_orders=self.create_new_orders,
            close_position_by_stop_loss=self.close_position_by_stop_loss,
            close_position_by_take_profit=self.close_position_by_take_profit,
            close_position_by_strategy=self.close_position_by_strategy,
            close_position_by_opposite_signal=self.close_position_by_opposite_signal,
            status=DomainTraderStatus(self.status),
        )

    def load(self, trader: DomainTrader) -> None:
        candles = self.get_last_candles(count=self.candles_lookback_count)
        trader.candles = deque(
            (candle.instantiate() for candle in candles),
            maxlen=self.candles_lookback_count,
        )
        trader.positions = [
            pos.instantiate() for pos in self.opened_positions.order_by("opened_at")
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
                    data=signal.model_dump(mode="json")["data"],
                    candle_id=signal.candle.id,
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
                    else ""
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
                "amount",
                "type",
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
                trading_pair=self.trading_pair,  # type: ignore[misc]
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
            trading_pair=self.trading_pair,  # type: ignore[misc]
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

    # --- Управление состоянием ---

    def enable(self):
        self.status = TraderStatus.ENABLED
        self.save(update_fields=["status"])

    def disable(self):
        self.status = TraderStatus.DISABLED
        self.save(update_fields=["status"])

    def clear_all_data(self):
        self.signals.all().delete()
        self.orders.all().delete()
        self.positions.all().delete()
        self.errors.all().delete()

    def clear_all_errors(self):
        self.errors.all().delete()

    # --- Торговый цикл ---

    def has_existing_signal(self, timestamp: datetime) -> bool:
        return self.signals.filter(timestamp__gte=timestamp).exists()

    def handle_candle(
        self,
        candle: ExchangeCandle,
    ) -> None:
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

    def reboot(self):
        end_date = timezone.now()
        start_date = end_date - timedelta(days=365)
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

            async def _reboot(
                trader: DomainTrader,
                candle_iterator,
            ):
                async with trader:
                    await trader.reboot(
                        candle_iterator=candle_iterator,
                    )

            asyncio.run(
                _reboot(
                    trader=trader,
                    candle_iterator=candle_iterator,
                )
            )
            self.sync(trader=trader)
        except Exception as e:
            self.status = TraderStatus.ERROR
            self.errors.create(
                message=f"Ошибка при перезапуске трейдера: {e!s}",
                type=type(e).__name__,
                traceback=traceback.format_exc(),
            )
        except BaseException:
            self.status = TraderStatus.ERROR
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


class TraderError(BaseErrorMixin, TimeStampedMixin, models.Model):
    """Ошибки трейдера."""

    trader = models.ForeignKey(
        Trader,
        on_delete=models.CASCADE,
        related_name="errors",
        verbose_name="Трейдер",
    )

    class Meta:
        verbose_name = "Ошибка трейдера"
        verbose_name_plural = "Ошибки трейдера"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return super().__str__()

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
        related_name="signals",
        verbose_name="Трейдер",
    )
    timestamp = models.DateTimeField(
        verbose_name="Время сигнала",
    )
    type = models.CharField(
        max_length=10,
        choices=SignalType.choices,
        verbose_name="Тип сигнала",
    )

    candle = models.ForeignKey(
        ExchangeCandle,
        on_delete=models.CASCADE,
        related_name="signals",
        verbose_name="Свеча сигнала",
    )

    price = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        verbose_name="Цена сигнала",
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

    def __str__(self):
        return f"{self.trader} | {self.type} | {self.timestamp}"

    def instantiate(self) -> DomainTraderSignal:
        return DomainTraderSignal(
            id=self.pk,
            timestamp=self.timestamp,
            price=self.price,
            candle=self.candle.instantiate(),
            type=DomainSignalType(self.type),
            data=self.data,
        )


class TraderPosition(TimeStampedMixin, models.Model):
    trader = models.ForeignKey(
        Trader,
        on_delete=models.CASCADE,
        related_name="positions",
        verbose_name="Трейдер",
    )
    type = models.CharField(
        max_length=10,
        choices=PositionType.choices,
        verbose_name="Тип позиции",
    )
    status = models.CharField(
        max_length=10,
        choices=PositionStatus.choices,
        default=PositionStatus.OPENED,
        verbose_name="Статус позиции",
    )
    amount = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        verbose_name="Количество актива",
    )
    open_price = models.DecimalField(  # type: ignore[misc]
        max_digits=30,
        decimal_places=18,
        null=True,
        blank=True,
        verbose_name="Цена открытия",
    )
    close_price = models.DecimalField(  # type: ignore[misc]
        max_digits=30,
        decimal_places=18,
        null=True,
        blank=True,
        verbose_name="Цена закрытия",
    )
    stop_loss = models.DecimalField(  # type: ignore[misc]
        max_digits=30,
        decimal_places=18,
        null=True,
        blank=True,
        verbose_name="Stop Loss",
    )
    take_profit = models.DecimalField(  # type: ignore[misc]
        max_digits=30,
        decimal_places=18,
        null=True,
        blank=True,
        verbose_name="Take Profit",
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
    recalculated_at = models.DateTimeField(  # type: ignore[misc]
        null=True,
        blank=True,
        verbose_name="Время перерасчёта",
    )
    close_reason = models.CharField(
        max_length=20,
        blank=True,
        default="",
        choices=PositionCloseReason.choices,
        verbose_name="Причина закрытия",
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
                    "amount",
                    "type",
                ],
                name="unique_position",
            )
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

    @property
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
        related_name="orders",
        verbose_name="Трейдер",
    )
    order = models.OneToOneField(
        ExchangeClientOrder,
        on_delete=models.CASCADE,
        related_name="trader_order",
        verbose_name="Ордер биржи",
    )
    position = models.ForeignKey(
        TraderPosition,
        on_delete=models.CASCADE,
        related_name="orders",
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
