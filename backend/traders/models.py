from datetime import datetime
from decimal import Decimal, InvalidOperation
from functools import cached_property
from typing import Any, Dict, List, Optional, Tuple
from django.core.validators import MinValueValidator, MaxValueValidator
from loguru import logger
from backend.risk_managers.domain.schemas import PositionDTO
from backend.traders.domain.traders import Trader as TraderDomain


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
from exchanges.domain.schemas import CandleDTO
from exchanges.models import Candle, ExchangeClient, ExchangeOrder, TradingPair
from risk_managers.models import RiskManager
from strategies.models import Strategy


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

    def instantiate(self, **kwargs) -> "TraderDomain":
        strategy = self.strategy.instantiate()
        risk_manager = self.risk_manager.instantiate()
        exchange_client = self.exchange_client.instantiate()

        return TraderDomain(
            exchange_client=exchange_client,
            trading_pair=self.trading_pair,
            timeframe=Timeframe(self.timeframe),
            strategy=strategy,
            risk_manager=risk_manager,
            initial_balance=self.initial_balance,
            max_drawdown_pct=self.max_drawdown_pct,
            max_positions_count=self.max_positions_count,
            trail_stop_enabled=self.trail_stop_enabled,
            data=self.data,
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
        """Рассчитывает winrate (процент прибыльных сделок) трейдера."""
        closed_positions = self.get_closed_positions()
        total = closed_positions.count()
        if total == 0:
            return 0.0

        wins = closed_positions.filter(
            models.Q(type=PositionType.LONG, close_price__gt=models.F("open_price"))
            | models.Q(type=PositionType.SHORT, close_price__lt=models.F("open_price"))
        ).count()

        return wins / total * 100

    def get_fact_profit(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Decimal:
        """
        Вычисляет реализованную прибыль (PnL) трейдера за указанный период.

        Прибыль рассчитывается как разница между суммарной выручкой от закрытых
        сделок на продажу и суммарными затратами на закрытые сделки на покупку.
        Эта функция учитывает только ордеры, которые были открыты и закрыты в указанный период.

        Args:
            start_date (Optional[datetime]): Начальная дата периода, если указана.
            end_date (Optional[datetime]): Конечная дата периода, если указана.

        Returns:
            Decimal: Общая реализованная прибыль за указанный период.
        """
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

        profit = sell_total - buy_total
        return profit

    def get_theoretical_profit(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Decimal:
        """
        Вычисляет реализованную прибыль (PnL) трейдера за указанный период.

        Прибыль рассчитывается как разница между суммарной выручкой от итогов позиций
        на продажу и суммарными затратами на закрытые позиции на покупку.
        Эта функция учитывает только позиции, которые были открыты и закрыты в указанный период.

        Args:
            start_date (Optional[datetime]): Начальная дата периода, если указана.
            end_date (Optional[datetime]): Конечная дата периода, если указана.

        Returns:
            Decimal: Общая реализованная прибыль за указанный период.
            Значение может быть как положительным, так и отрицательным.
        """

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
        """
        Возвращает среднее время жизни одной закрытой позиции (в секундах) через ORM.
        """
        timeframe = Timeframe(self.timeframe)
        timeframe_td = timeframe.timedelta()
        closed_positions = self.get_closed_positions()
        if not closed_positions.exists():
            return None

        closed_positions = closed_positions.annotate(
            duration=ExpressionWrapper(
                F("closed_at") - F("opened_at"), output_field=DurationField()
            )
        )
        avg_duration = closed_positions.aggregate(avg=Avg("duration"))["avg"]
        if avg_duration is None:
            return None
        return avg_duration / timeframe_td

    def get_balance(self) -> Decimal:
        """
        Возвращает текущий виртуальный баланс трейдера, исходя из стартового капитала
        и реализованной прибыли за указанный период.

        Баланс = начальный капитал + реализованная прибыль за дату

        Args:
            date (Optional[datetime]): Дата.

        Returns:
            Decimal: Расчётный виртуальный баланс трейдера.
        """
        return self.initial_balance + self.get_fact_profit()

    @cached_property
    def balance(self) -> Decimal:
        """
        Возвращает текущий виртуальный баланс трейдера.
        Используется для получения баланса в шаблонах и API.
        """
        return self.get_balance()

    def clean_trader_data(self):
        """
        Очищает внутренние данные трейдера, включая сигналы и позиции.
        Вызывается при перезапуске трейдера.
        """
        self.data.clear()
        self.signals.all().delete()
        self.positions.all().delete()
        self.save(update_fields=["data"])

    def enable(self):
        """
        Активирует трейдера, устанавливая статус ENABLED.
        Вызывается при запуске трейдера.
        """
        self.status = TraderStatus.ENABLED
        self.save(update_fields=["status"])

    def disable(self):
        """
        Деактивирует трейдера, устанавливая статус DISABLED.
        Вызывается при остановке трейдера.
        """
        self.status = TraderStatus.DISABLED
        self.save(update_fields=["status"])

    # def update_data(self, candle: Candle) -> None:
    #     """
    #     Обновляет состояние трейдера на основе новой свечи.
    #     Вызывается при получении новой свечи из источника данных.
    #     """
    #     self.data.setdefault("candles", [])

    #     dto = CandleDTO(
    #         dt_unix=candle.dt_unix,
    #         open=candle.open,
    #         high=candle.high,
    #         low=candle.low,
    #         close=candle.close,
    #         volume=candle.volume,
    #     )

    #     self.data["candles"].append(dto.model_dump(mode="json"))

    #     self.data["candles"] = self.data["candles"][-50:]

    #     return self.data

    def check_opened_position(
        self,
        candle: Candle,
        create_order: bool = True,
    ) -> None:
        if self.signals.filter(
            timestamp=candle.timestamp,
        ).exists():
            logger.warning(
                f"Signal for trader {self.pk} at {candle.timestamp} already exists."
            )
            return
        trader = self.instantiate()
        trader.load_data(self.data)
        trader.check_opened_position(
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

    def check_opened_positions(
        self,
        candle: Candle,
        create_order: bool = True,
    ) -> None:
        """
        Контролирует открытые позиции.
        Вызывается периодически для проверки и обновления позиций. Для любого момента времени
        может быть вызвано обновление позиций, чтобы проверить, нужно ли их закрыть
        или обновить стоп-лосс/тейк-профит.
        """
        positions = self.opened_positions.filter(
            opened_at__lte=candle.timestamp,
        )
        if not positions.exists():
            return

        trader = self.instantiate()
        trader.load_data(self.data)
        updated_positions = trader.check_opened_positions(
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

        if updated_positions:
            TraderPosition.objects.bulk_update(
                updated_positions,
                fields=[
                    "stop_loss",
                    "take_profit",
                    "updated_at",
                    "status",
                    "close_price",
                    "closed_at",
                ],
            )

    def reboot(self):
        if self.status == TraderStatus.REBOOTING:
            return

        candles = self.candles.order_by("timestamp")

        self.clean_trader_data()
        self.last_reboot = timezone.now()
        self.status = TraderStatus.REBOOTING
        self.save(update_fields=["last_reboot", "status"])

        try:
            for candle in candles.iterator():
                self.process(candle, create_order=False)
        except Exception:
            self.status = TraderStatus.ERROR
        else:
            self.status = TraderStatus.ENABLED
        finally:
            self.save(update_fields=["status"])

    def get_opened_positions(self) -> models.QuerySet["TraderPosition"]:
        """
        Возвращает все открытые позиции трейдера.
        """
        return TraderPosition.objects.filter(trader=self, status=PositionStatus.OPENED)

    @cached_property
    def opened_positions(self) -> models.QuerySet["TraderPosition"]:
        """
        Возвращает все открытые позиции трейдера.
        Используется для получения открытых позиций в шаблонах и API.
        """
        return self.get_opened_positions()

    def get_closed_positions(self) -> models.QuerySet["TraderPosition"]:
        """
        Возвращает все закрытые позиции трейдера.
        """
        return TraderPosition.objects.filter(trader=self, status=PositionStatus.CLOSED)

    def create_market_order(
        self,
        trading_pair: TradingPair,
        side: OrderSide,
        amount: Decimal,
        price: Optional[Decimal] = None,
        params: Optional[dict] = None,
    ) -> ExchangeOrder:
        """
        Создаёт и сохраняет ордер в истории ордеров трейдера.

        Args:
            side: Тип ордера, должен быть 'buy' или 'sell'.
            price: Цена ордера.
            volume: Объём ордера.
        Returns:
            Созданный объект OrderHistory.
        """
        created_order = self.exchange_client.create_market_order(
            trading_pair=trading_pair,
            side=side,
            amount=amount,
            price=price,
            params=params,
        )

        TraderOrder.objects.create(
            exchange_order=created_order,
            trader=self,
        )
        return created_order


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
    trader = models.ForeignKey(Trader, on_delete=models.CASCADE, verbose_name="Трейдер")
    timestamp = models.DateTimeField(verbose_name="Время")
    type = models.CharField(
        max_length=10, choices=SignalType.choices, verbose_name="Тип"
    )
    price = models.DecimalField(max_digits=30, decimal_places=18, verbose_name="Цена")

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


class TraderPosition(models.Model):
    trader = models.ForeignKey(Trader, on_delete=models.CASCADE, verbose_name="Трейдер")
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

    def __str__(self):
        pnl = self.pnl()
        pnl_str = f"{round(pnl, 2)}" if pnl is not None else "N/A"
        rr = self.rr()
        rr_str = f"{round(rr, 2)}" if rr is not None else "N/A"
        return f"{self.get_status_display()} | {self.get_type_display()} | PNL:{pnl_str} | RR:{rr_str}"

    @property
    def open_value(self) -> Optional[Decimal]:
        if self.open_price:
            return self.open_price * self.amount

    @property
    def close_value(self) -> Optional[Decimal]:
        if self.close_price:
            return self.amount * self.close_price

    @property
    def stop_loss_pct(self) -> Optional[Decimal]:
        if self.stop_loss is None or self.open_price is None:
            return None

        if self.type == PositionType.LONG:
            return (self.stop_loss - self.open_price) / self.open_price * 100
        elif self.type == PositionType.SHORT:
            return (self.open_price - self.stop_loss) / self.open_price * 100
        return None

    @property
    def take_profit_pct(self) -> Optional[Decimal]:
        if self.take_profit is None or self.open_price is None:
            return None

        if self.type == PositionType.LONG:
            return (self.take_profit - self.open_price) / self.open_price * 100
        elif self.type == PositionType.SHORT:
            return (self.open_price - self.take_profit) / self.open_price * 100
        return None

    def pnl(self) -> Optional[Decimal]:
        """
        Возвращает реализованный PnL (если позиция закрыта).
        """
        if self.status != PositionStatus.CLOSED or self.close_price is None:
            return None

        if self.type == PositionType.LONG:
            return (self.close_price - self.open_price) * self.amount
        if self.type == PositionType.SHORT:
            return (self.open_price - self.close_price) * self.amount

    def rr(self) -> Optional[Decimal]:
        """
        Возвращает отношение потенциальной прибыли к риску (Reward/Risk ratio).
        Не зависит от типа позиции (LONG/SHORT), всегда положительное число.
        Безопасен к делению на 0 и отсутствию данных.

        :return: Decimal или None, если рассчитать невозможно
        """
        risk = None
        reward = None
        if self.open_price is None:
            return None
        if self.stop_loss is not None:
            risk = abs(self.open_price - self.stop_loss)
        if self.take_profit is not None:
            reward = abs(self.take_profit - self.open_price)
        if risk is None or reward is None or risk == 0:
            return None
        try:
            return reward / risk
        except (ZeroDivisionError, InvalidOperation):
            return None

    def should_be_closed(
        self,
        signal: SignalType | None,
        price: Decimal | None,
    ) -> bool:
        """
        Определяет, нужно ли закрывать позицию по текущему сигналу и цене.

        Логика:
        - Если пришёл противоположный сигнал (например, позиция LONG, сигнал SELL) — закрываем.
        - Если цена достигла стоп-лосса или тейк-профита — закрываем.
        - Иначе — оставляем открытую.

        :param signal: Текущий торговый сигнал
        :return: True, если позицию нужно закрыть, иначе False
        """
        if self.status != PositionStatus.OPENED:
            return False

        if signal:
            # Противоположний сигнал
            if (self.type == PositionType.LONG and signal == SignalType.SELL) or (
                self.type == PositionType.SHORT and signal == SignalType.BUY
            ):
                return True

        if price:
            # Стоп-лосс
            if self.stop_loss is not None:
                if (self.type == PositionType.LONG and price <= self.stop_loss) or (
                    self.type == PositionType.SHORT and price >= self.stop_loss
                ):
                    return True

            # Тейк-профит
            if self.take_profit is not None:
                if (self.type == PositionType.LONG and price >= self.take_profit) or (
                    self.type == PositionType.SHORT and price <= self.take_profit
                ):
                    return True

        return False
