from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from core.utils.mixins import ActiveManagerMixin, TimeStampedMixin
from core.utils.types import (OrderSide, OrderStatus, PositionStatus,
                              PositionType, SignalType, TraderStatus,
                              TradingPair)
from django.db import models
from django.db.models import Case, ExpressionWrapper, F, Q, Sum, When
from django.urls import reverse
from django.utils import timezone
from exchanges.domain.schemas import CandleDTO
from exchanges.models import (Candle, CandleSource, ExchangeClient,
                              ExchangeOrder)
from risk_managers.models import RiskManager
from strategies.models import Strategy


class Trader(TimeStampedMixin, ActiveManagerMixin, models.Model):
    status = models.CharField(
        choices=TraderStatus.choices, default=TraderStatus.DISABLED
    )
    candle_source = models.ForeignKey(
        CandleSource,
        on_delete=models.CASCADE,
        related_name="traders",
    )
    strategy = models.ForeignKey(
        Strategy,
        on_delete=models.CASCADE,
    )

    risk_manager = models.ForeignKey(
        RiskManager,
        on_delete=models.CASCADE,
    )

    initial_balance = models.DecimalField(
        verbose_name="Начальный баланс, USDT",
        max_digits=20,
        decimal_places=2,
        default=Decimal("100.00"),
    )

    last_reboot = models.DateTimeField(
        verbose_name="Последний перезапуск",
        null=True,
        blank=True,
    )

    data = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Трейдер"
        verbose_name_plural = "Трейдеры"
        constraints = [
            models.UniqueConstraint(
                fields=["candle_source", "strategy", "risk_manager", "initial_balance"],
                name="unique_trader_constraint",
            )
        ]

    def __str__(self):
        return f"{self.get_status_display()} | {self.candle_source} | {self.strategy}"

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

    def get_total_positions_count(self) -> int:
        return self.positions.count()

    def get_total_orders_count(self) -> int:
        return self.orders.count()

    @property
    def exchange_client(self) -> ExchangeClient:
        return self.candle_source.exchange_client

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

        return round(wins / total * 100, 2)

    def reboot(self):
        create_order = False
        candles = Candle.objects.filter(
            candle_source=self.candle_source,
        ).order_by("timestamp")

        self.data.clear()
        self.signals.delete()
        self.positions.delete()
        self.last_reboot = timezone.now()
        self.status = TraderStatus.REBOOTING
        self.save()

        all_signals: List[TraderSignal] = []
        all_positions: List[TraderPosition] = []
        opened_positions: List[TraderPosition] = []
        for candle in candles.iterator():
            self.data = self.update_data(candle)
            price = candle.close
            balance = self.get_balance()

            self.data = self.strategy.handle_candle(data=self.data, candle=candle)
            self.data, signal = self.strategy.get_signal(self.data)
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

            if not self.risk_manager.can_trade(
                data=self.data,
                signal=signal,
                price=price,
                balance=balance,
                initial_balance=self.initial_balance,
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

    def save(
        self,
        *args,
        force_insert=False,
        force_update=False,
        using=None,
        update_fields=None,
    ):
        if not self.is_active:
            self.status = TraderStatus.DISABLED
        super().save(
            *args,
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )

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
        self.data = self.update_data(candle)
        create_order = self.is_active

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
                opened_positions.append(position)
        if closed_positions:
            TraderPosition.objects.bulk_update(
                closed_positions,
                fields=["status", "close_price", "closed_at"],
            )
        if not self.risk_manager.can_trade(
            data=self.data,
            signal=signal,
            price=price,
            balance=balance,
            initial_balance=self.initial_balance,
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
        type = PositionType.LONG if signal == SignalType.BUY else PositionType.SHORT

        new_data, stop_loss = self.risk_manager.get_stop_loss(
            data=data,
            signal=signal,
            price=price,
        )
        new_data, take_profit = self.risk_manager.get_take_profit(
            data=new_data,
            signal=signal,
            price=price,
        )

        new_data, position_size = self.risk_manager.calculate_position_size(
            data=new_data,
            signal=signal,
            price=price,
            balance=balance,
        )

        if position_size <= 0:
            return {**data, **new_data}, None

        order = None
        if create_order:
            order: ExchangeOrder = self.create_market_order(
                trading_pair=TradingPair(self.candle_source.trading_pair),
                side=OrderSide.BUY if signal == SignalType.BUY else OrderSide.SELL,
                price=price,
                volume=position_size,
            )
        amount = order.amount if order else position_size
        open_price = order.price if order else price
        opened_at = order.timestamp if order else timezone.now()
        position = TraderPosition(
            trader=self,
            type=type,
            status=PositionStatus.OPENED,
            open_price=open_price,
            amount=amount,
            stop_loss=stop_loss,
            opened_at=timestamp or opened_at,
            take_profit=take_profit,
        )
        return {**data, **new_data}, position

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
                trading_pair=TradingPair(self.candle_source.trading_pair),
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

        buy_total = (
            orders.filter(side=OrderSide.BUY).aggregate(
                total=models.Sum(models.F("price") * models.F("amount"))
            )["total"]
            or 0.0
        )

        sell_total = (
            orders.filter(side=OrderSide.SELL).aggregate(
                total=models.Sum(models.F("price") * models.F("amount"))
            )["total"]
            or 0.0
        )

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
            default=0.0,
            output_field=models.DecimalField(max_digits=30, decimal_places=18),
        )

        result = positions.aggregate(total_profit=Sum(profit_expression))
        total_profit = result["total_profit"] or 0.0
        return total_profit

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
        return self.initial_balance or 0.0 + self.get_fact_profit(end_date=date)

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

    def handle_candle(self, candle: Candle) -> None:
        new_data = self.strategy.handle_candle(candle, self.data)
        if new_data != self.data:
            self.data = new_data
            self.save()

    def get_signal(self) -> SignalType:
        signal, new_data = self.strategy.get_signal(self.data)
        if new_data != self.data:
            self.data = new_data
            self.save()
        return signal

    def can_trade(
        self,
        signal: SignalType,
        price: Decimal,
        balance: Optional[Decimal],
        opened_positions: Optional[List],
    ) -> bool:
        return self.risk_manager.can_trade(
            signal=signal,
            price=price,
            balance=balance or self.get_balance(),
            opened_positions=opened_positions or self.get_opened_positions(),
        )


class TraderOrder(TimeStampedMixin, models.Model):
    trader = models.ForeignKey(
        Trader,
        on_delete=models.CASCADE,
    )
    order = models.OneToOneField(
        ExchangeOrder,
        on_delete=models.CASCADE,
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
    )
    timestamp = models.DateTimeField()
    type = models.CharField(
        max_length=10,
        choices=SignalType.choices,
    )
    price = models.DecimalField(
        max_digits=30,
        decimal_places=18,
    )

    class Meta:
        verbose_name = "Сигнал трейдера"
        verbose_name_plural = "Сигналы трейдера"


class TraderPosition(models.Model):
    trader = models.ForeignKey(
        Trader,
        on_delete=models.CASCADE,
    )
    type = models.CharField(
        max_length=10,
        choices=PositionType.choices,
    )
    status = models.CharField(
        max_length=10,
        choices=PositionStatus.choices,
        default=PositionStatus.OPENED,
    )
    amount = models.DecimalField(max_digits=30, decimal_places=18)

    open_price = models.DecimalField(
        max_digits=30, decimal_places=18, null=True, blank=True
    )
    close_price = models.DecimalField(
        max_digits=30, decimal_places=18, null=True, blank=True
    )
    stop_loss = models.DecimalField(
        max_digits=30, decimal_places=18, null=True, blank=True
    )
    take_profit = models.DecimalField(
        max_digits=30, decimal_places=18, null=True, blank=True
    )
    opened_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Позиция трейдера"
        verbose_name_plural = "Позиции трейдера"

    def __str__(self):
        return f"{self.get_status_display()} | {self.get_type_display()} | PNL:{self.pnl()} | RR:{self.rr()}"

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
            return 0

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
