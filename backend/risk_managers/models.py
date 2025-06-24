import inspect
from typing import Any, List
from core.utils.types import SignalType
from strategies.domain.strategies.base import SignalType as SignalTypeDTO
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

    class Meta:
        verbose_name = "Риск-менеджер"
        verbose_name_plural = "Риск-менеджеры"

    def get_class(self) -> AbstractRiskManager:
        return RiskManagerRegistry.get_class(self.class_name)

    def instantiate(self, **kwargs) -> AbstractRiskManager:
        cls = self.get_class()
        return cls(**self.arguments, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.class_name})"

    def save(self, *args, **kwargs):
        if not self.arguments:
            cls = self.get_class()
            sig = inspect.signature(cls.__init__)
            self.arguments = {
                k: v.default
                for k, v in sig.parameters.items()
                if k != "self" and v.default is not inspect.Parameter.empty
            }
        super().save(*args, **kwargs)

    def can_trade(
        self,
        signal: SignalType,
        price: float,
        balance: float,
        opened_positions: list,
        **kwargs: Any,
    ):
        risk_manager = self.instantiate(**kwargs)
        return risk_manager.can_trade(
            SignalTypeDTO(signal), price, balance, opened_positions
        )

    def calculate_position_size(
        self,
        price: float,
        balance: float,
    ) -> float:
        """
        Вычисляет размер позиции, исходя из допустимого риска и расстояния до стоп-лосса.

        :param price: Цена входа
        :param balance: Доступный баланс
        :return: Размер позиции (объем)
        """
        risk_manager = self.instantiate()
        return risk_manager.calculate_position_size(price, balance)

    def get_stop_loss(self, price: float) -> float:
        """
        Получает уровень стоп-лосса для текущей цены.

        :param price: Текущая цена актива
        :return: Уровень стоп-лосса
        """
        risk_manager = self.instantiate()
        return risk_manager.get_stop_loss(price)

    def get_take_profit(self, price: float) -> float:
        """
        Получает уровень тейк-профита для текущей цены.

        :param price: Текущая цена актива
        :return: Уровень тейк-профита
        """
        risk_manager = self.instantiate()
        return risk_manager.get_take_profit(price)
