from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple
from django.core.validators import MinValueValidator, MaxValueValidator

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
        return f"{self.get_status_display()} | {self.exchange_client} | {self.strategy}"

    def get_absolute_url(self):
        return reverse("trader_detail", kwargs={"pk": self.pk})

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
        qs = self.get_closed_positions()
        if not qs.exists():
            return None

        qs = qs.annotate(
            duration=ExpressionWrapper(
                F("closed_at") - F("opened_at"), output_field=DurationField()
            )
        )
        avg_duration = qs.aggregate(avg=Avg("duration"))["avg"]
        if avg_duration is None:
            return None
        return avg_duration / timeframe_td

    def get_balance(self, date: Optional[datetime] = None) -> Decimal:
        """
        Возвращает текущий виртуальный баланс трейдера, исходя из стартового капитала
        и реализованной прибыли за указанный период.

        Баланс = начальный капитал + реализованная прибыль за дату

        Args:
            date (Optional[datetime]): Дата.

        Returns:
            Decimal: Расчётный виртуальный баланс трейдера.
        """
        return self.initial_balance + self.get_fact_profit(end_date=date)

    def reboot(self):
        if self.status == TraderStatus.REBOOTING:
            return

        candles = self.candles.order_by("timestamp")

        self.data.clear()
        self.signals.delete()
        self.positions.delete()
        self.last_reboot = timezone.now()
        self.status = TraderStatus.REBOOTING
        self.save()
        create_order = False

        all_signals: List[TraderSignal] = []
        all_positions: List[TraderPosition] = []
        opened_positions: List[TraderPosition] = []

        for candle in candles.iterator():
            self.data = self.update_data(candle)
            price = candle.close
            balance = self.get_balance()

            self.data = self.strategy.handle_candle(data=self.data, candle=candle)
            self.data, signal = self.strategy.get_signal(data=self.data)
            if signal in (SignalType.BUY, SignalType.SELL):
                all_signals.append(
                    TraderSignal(
                        trader=self,
                        timestamp=candle.timestamp,
                        type=signal,
                        price=candle.close,
                    )
                )
            for position in opened_positions:
                if position.should_be_closed(signal=signal, price=price):
                    self.data, closed_position = self.close_position(
                        data=self.data,
                        position=position,
                        price=price,
                        create_order=create_order,
                        timestamp=candle.timestamp,
                    )
                    opened_positions.remove(closed_position)
                else:
                    if self.trail_stop_enabled:
                        self.data, updated_position = self.update_position(
                            data=self.data,
                            position=position,
                            price=price,
                            timestamp=candle.timestamp,
                        )

            if not self.can_open_position(
                signal=signal,
                price=price,
                balance=balance,
                opened_positions=opened_positions,
            ):
                continue

            self.data, opened_position = self.open_position(
                data=self.data,
                signal=signal,
                price=price,
                balance=balance,
                create_order=create_order,
                timestamp=candle.timestamp,
            )
            if opened_position:
                opened_positions.append(opened_position)
                all_positions.append(opened_position)

        if all_positions:
            TraderPosition.objects.bulk_create(all_positions)
        if all_signals:
            TraderSignal.objects.bulk_create(all_signals)
        self.status = TraderStatus.ENABLED
        self.save()

    def can_open_position(
        self,
        signal: SignalType,
        price: Decimal,
        balance: Decimal,
        opened_positions: list,
    ) -> bool:
        if signal not in {SignalType.BUY, SignalType.SELL}:
            return False
        if not self.check_drawdown_limit(balance, self.initial_balance):
            return False
        if not self.check_max_positions(opened_positions):
            return False
        return True

    def check_max_positions(
        self,
        opened_positions: List[Any],
    ) -> bool:
        return len(opened_positions) < self.max_positions_count

    def check_drawdown_limit(self, balance: Decimal, initial_balance: Decimal) -> bool:
        try:
            allowed_min_balance = initial_balance * (
                1 - Decimal(str(self.max_drawdown_pct)) / Decimal("100")
            )
            result = balance >= allowed_min_balance
            return result
        except (InvalidOperation, TypeError):
            return False

    def enable(self):
        """
        Активирует трейдера, устанавливая статус ENABLED.
        Вызывается при запуске трейдера.
        """
        self.status = TraderStatus.ENABLED
        self.save()

    def disable(self):
        """
        Деактивирует трейдера, устанавливая статус DISABLED.
        Вызывается при остановке трейдера.
        """
        self.status = TraderStatus.DISABLED
        self.save()

    def update_data(self, candle: Candle) -> None:
        """
        Обновляет состояние трейдера на основе новой свечи.
        Вызывается при получении новой свечи из источника данных.
        """
        self.data.setdefault("candles", [])

        dto = CandleDTO(
            dt_unix=candle.dt_unix,
            open=candle.open,
            high=candle.high,
            low=candle.low,
            close=candle.close,
            volume=candle.volume,
        )

        self.data["candles"].append(dto.model_dump(mode="json"))

        self.data["candles"] = self.data["candles"][-50:]

        return self.data

    def trade(self, candle: Candle) -> None:
        if self.status != TraderStatus.ENABLED:
            return
        self.data = self.update_data(candle)
        create_order = True

        price = candle.close
        balance = self.get_balance()

        self.data = self.strategy.handle_candle(data=self.data, candle=candle)
        self.data, signal = self.strategy.get_signal(self.data)
        if signal in {SignalType.BUY, SignalType.SELL}:
            TraderSignal.objects.create(
                trader=self,
                timestamp=candle.timestamp,
                type=signal,
                price=candle.close,
            )
        opened_positions = list()
        closed_positions = list()
        for position in self.get_opened_positions():
            if position.should_be_closed(signal=signal, price=price):
                self.data, closed_position = self.close_position(
                    data=self.data,
                    position=position,
                    price=price,
                    create_order=create_order,
                )
                closed_positions.append(closed_position)
            else:
                if self.trail_stop_enabled:
                    self.data, updated_position = self.update_position(
                        data=self.data,
                        position=position,
                        price=price,
                    )
                opened_positions.append(position)

        if closed_positions:
            TraderPosition.objects.bulk_update(
                closed_positions,
                fields=["status", "close_price", "closed_at"],
            )
        if opened_positions:
            TraderPosition.objects.bulk_update(
                opened_positions,
                fields=["stop_loss", "take_profit", "updated_at"],
            )
        if not self.can_open_position(
            signal=signal,
            price=price,
            balance=balance,
            opened_positions=opened_positions,
        ):
            return

        self.data, opened_position = self.open_position(
            data=self.data,
            signal=signal,
            price=price,
            balance=balance,
            create_order=create_order,
        )
        opened_position.save()
        self.save()

    def open_position(
        self,
        data: Dict[str, Any],
        signal: SignalType,
        price: Decimal,
        balance: Decimal,
        create_order: bool = True,
        timestamp: Optional[datetime] = None,
    ) -> Tuple[Dict[str, Any], "TraderPosition"]:
        """
        Открывает позицию на основе сигнала и текущей цены.
        """
        position_type = (
            PositionType.LONG if signal == SignalType.BUY else PositionType.SHORT
        )

        data, stop_loss = self.risk_manager.get_stop_loss(
            data=data,
            position_type=position_type,
            price=price,
        )
        data, take_profit = self.risk_manager.get_take_profit(
            data=data,
            position_type=position_type,
            price=price,
        )

        data, position_size = self.risk_manager.calculate_position_size(
            data=data,
            position_type=position_type,
            price=price,
            balance=balance,
        )

        if position_size <= 0:
            return data, None

        order = None
        if create_order:
            order: ExchangeOrder = self.create_market_order(
                trading_pair=self.trading_pair,
                side=(
                    OrderSide.BUY
                    if position_type == PositionType.LONG
                    else OrderSide.SELL
                ),
                price=price,
                amount=position_size,
            )
        amount = order.amount if order else position_size
        open_price = order.price if order else price
        opened_at = order.timestamp if order else timezone.now()
        position = TraderPosition(
            trader=self,
            type=position_type,
            status=PositionStatus.OPENED,
            open_price=open_price,
            amount=amount,
            stop_loss=stop_loss,
            opened_at=timestamp or opened_at,
            take_profit=take_profit,
        )
        return data, position

    def close_position(
        self,
        data: Dict[str, Any],
        position: "TraderPosition",
        price: Decimal,
        create_order: bool = True,
        timestamp: Optional[datetime] = None,
    ) -> "TraderPosition":
        """Закрывает указанную позицию по текущей цене."""
        order = None
        if create_order:
            order = self.create_market_order(
                trading_pair=self.trading_pair,
                side=(
                    OrderSide.SELL
                    if position.type == PositionType.LONG
                    else OrderSide.BUY
                ),
                amount=position.amount,
                price=price,
            )
        closed_at = order.timestamp if order else timezone.now()
        close_price = order.price if order else price
        position.status = PositionStatus.CLOSED
        position.closed_at = timestamp or closed_at
        position.close_price = close_price
        return data, position

    def update_position(
        self,
        data: Dict[str, Any],
        position: "TraderPosition",
        price: Decimal,
        timestamp: Optional[datetime] = None,
    ) -> "TraderPosition":
        """
        Обновляет позицию трейдера, если она уже открыта.
        Вызывается при получении новой свечи из источника данных.
        """
        # position_type = (
        #     PositionType.LONG
        #     if position.type == PositionType.SHORT
        #     else PositionType.SHORT
        # )

        data, new_stop_loss = self.risk_manager.get_stop_loss(
            data=data,
            position_type=position.type,
            price=price,
        )

        # Обновляем stop_loss только если новое значение лучше
        # (ближе к цене входа)
        if new_stop_loss is not None:
            if position.stop_loss is None:
                position.stop_loss = new_stop_loss
            else:
                # Для LONG позиций: новый stop_loss должен быть выше текущего
                # Для SHORT позиций: новый stop_loss должен быть ниже текущего
                if (
                    position.type == PositionType.LONG
                    and new_stop_loss > position.stop_loss
                ):
                    position.stop_loss = new_stop_loss
                elif (
                    position.type == PositionType.SHORT
                    and new_stop_loss < position.stop_loss
                ):
                    position.stop_loss = new_stop_loss

        data, new_take_profit = self.risk_manager.get_take_profit(
            data=data,
            position_type=position.type,
            price=price,
        )

        # Обновляем take_profit только если новое значение лучше
        # (дальше от цены входа)
        if new_take_profit is not None:
            if position.take_profit is None:
                position.take_profit = new_take_profit
            else:
                # Для LONG позиций: новый take_profit должен быть выше
                # Для SHORT позиций: новый take_profit должен быть ниже
                if (
                    position.type == PositionType.LONG
                    and new_take_profit > position.take_profit
                ):
                    position.take_profit = new_take_profit
                elif (
                    position.type == PositionType.SHORT
                    and new_take_profit < position.take_profit
                ):
                    position.take_profit = new_take_profit

        position.updated_at = timestamp or timezone.now()
        return data, position

    def get_opened_positions(self) -> models.QuerySet["TraderPosition"]:
        """
        Возвращает все открытые позиции трейдера.
        """
        return TraderPosition.objects.filter(trader=self, status=PositionStatus.OPENED)

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

    def should_be_closed(self, signal: SignalType, price: Decimal) -> bool:
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

        # Противоположний сигнал
        if (self.type == PositionType.LONG and signal == SignalType.SELL) or (
            self.type == PositionType.SHORT and signal == SignalType.BUY
        ):
            return True

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
