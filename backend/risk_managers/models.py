from typing import Any, Dict, Tuple

from core.utils.common import get_all_init_args
from core.utils.mixins import ActiveManagerMixin, TimeStampedMixin
from core.utils.types import SignalType
from django.db import models
from risk_managers.domain import AbstractRiskManager, RiskManagerRegistry
from strategies.domain import SignalType as SignalTypeDTO


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

    def get_description(self) -> str:
        """
        Возвращает docstring (описание) выбранного risk-менеджера.
        """
        cls = self.get_class()
        return (cls.__doc__ or "").strip()

    def save(self, *args, **kwargs):
        if not self.arguments:
            cls = self.get_class()
            self.arguments = get_all_init_args(cls)
        super().save(*args, **kwargs)

    def can_trade(
        self,
        data: Dict[str, Any],
        signal: SignalType,
        price: float,
        balance: float,
        opened_positions: list,
        initial_balance: float = 0.0,
    ):
        risk_manager = self.instantiate()
        risk_manager.load_data(data)
        # new_data = risk_manager.dump_data()
        return risk_manager.can_trade(
            SignalTypeDTO(signal),
            price,
            balance,
            opened_positions,
            initial_balance,
        )

    def calculate_position_size(
        self, data: Dict[str, Any], signal: SignalType, price: float, balance: float
    ) -> Tuple[Dict[str, Any], float]:
        """
        Вычисляет размер позиции, исходя из допустимого риска и расстояния до стоп-лосса.

        :param price: Цена входа
        :param balance: Доступный баланс
        :return: Размер позиции (объем)
        """
        risk_manager = self.instantiate()
        risk_manager.load_data(data)
        position_size = risk_manager.calculate_position_size(
            signal=signal, price=price, balance=balance
        )
        new_data = risk_manager.dump_data()
        return {**data, **new_data}, position_size

    def get_stop_loss(
        self, data: Dict[str, Any], signal: SignalType, price: float
    ) -> Tuple[Dict[str, Any], float]:
        """
        Получает уровень стоп-лосса для текущей цены.

        :param price: Текущая цена актива
        :return: Уровень стоп-лосса
        """
        risk_manager = self.instantiate()
        risk_manager.load_data(data)
        stop_loss = risk_manager.get_stop_loss(signal=signal, price=price)
        new_data = risk_manager.dump_data()
        return {**data, **new_data}, stop_loss

    def get_take_profit(
        self, data: Dict[str, Any], signal: SignalType, price: float
    ) -> Tuple[Dict[str, Any], float]:
        """
        Получает уровень тейк-профита для текущей цены.

        :param price: Текущая цена актива
        :return: Уровень тейк-профита
        """
        risk_manager = self.instantiate()
        risk_manager.load_data(data)
        take_profit = risk_manager.get_take_profit(signal=signal, price=price)
        new_data = risk_manager.dump_data()
        return {**data, **new_data}, take_profit
