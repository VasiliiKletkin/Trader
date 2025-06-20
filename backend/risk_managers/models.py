from typing import List
from core.utils.types import SignalType
from strategies.domain.strategies.base import SignalType as SignalTypeValueObj
from core.utils.mixins import ActiveManagerMixin, TimeStampedMixin
from django.db import models
from risk_managers.domain.risk_managers.base import (
    AbstractRiskManager,
    RiskManagerRegistry,
)


class RiskManager(ActiveManagerMixin, TimeStampedMixin, models.Model):
    name = models.CharField(max_length=100)
    class_name = models.CharField(
        max_length=100,
        choices=RiskManagerRegistry.get_choices,
    )

    arguments = models.JSONField(default=dict, blank=True)

    def get_class(self) -> AbstractRiskManager:
        return RiskManagerRegistry.get_class(self.class_name)

    def instantiate(self, **kwargs) -> AbstractRiskManager:
        cls = self.get_class()
        return cls(**self.arguments, **kwargs)

    def can_trade(
        self, signal: SignalType, price: float, balance: float, opened_positions: list
    ):
        risk_manager = self.instantiate()
        return risk_manager.can_trade(
            SignalTypeValueObj(signal), price, balance, opened_positions
        )

    def calculate_position_size(
        self,
        price: float,
        stop_loss: float,
        balance: float,
    ) -> float:
        """
        Вычисляет размер позиции, исходя из допустимого риска и расстояния до стоп-лосса.

        :param price: Цена входа
        :param stop_loss: Цена стоп-лосса
        :param balance: Доступный баланс
        :return: Размер позиции (объем)
        """
        risk_amount = balance * self.risk_per_trade

        # Расстояние до стоп-лосса в абсолютных значениях
        sl_distance = abs(price - stop_loss)

        if sl_distance == 0:
            return 0.0  # Защита от деления на 0

        position_size = risk_amount / sl_distance
        return round(position_size, 6)

    # def handle_candle(self, candle: Candle, data: Optional[dict] = None) -> None:
    #     new_data = self.strategy.handle_candle(candle, data or self.data)
    #     if new_data != self.data:
    #         self.data = new_data
    #         self.save()
