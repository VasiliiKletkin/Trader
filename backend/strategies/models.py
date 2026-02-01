from core.utils.common import get_all_init_args
from core.utils.mixins import ActiveManagerMixin, TimeStampedMixin
from django.db import models
from strategies.domain import (
    StrategyRegistry,
    AbstractStrategy,
    ArbitrageStrategyRegistry,
    AbstractArbitrageStrategy,
)


class Strategy(ActiveManagerMixin, TimeStampedMixin, models.Model):
    name = models.CharField(
        max_length=100,
        verbose_name="Название стратегии",
        unique=True,
    )
    class_name = models.CharField(
        max_length=100,
        choices=StrategyRegistry.get_choices,
        verbose_name="Класс стратегии",
    )
    arguments = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Параметры (аргументы)",
    )
    close_position_by_opposite_signal = models.BooleanField(
        default=True,
        verbose_name="Закрывать при противоположном сигнале",
        help_text="Закрывать позицию при получении противоположного сигнала.",
    )
    close_position_by_strategy = models.BooleanField(
        default=True,
        verbose_name="Закрывать по сигналу стратегии",
        help_text="Закрывать позицию при получении сигнала от стратегии.",
    )
    close_position_by_stop_loss = models.BooleanField(
        default=True,
        verbose_name="Закрывать по Stop Loss",
        help_text="Закрывать позицию при достижении Stop Loss.",
    )
    close_position_by_take_profit = models.BooleanField(
        default=True,
        verbose_name="Закрывать по Take Profit",
        help_text="Закрывать позицию при достижении Take Profit.",
    )

    class Meta:
        verbose_name = "Стратегия"
        verbose_name_plural = "Стратегии"

    def __str__(self):
        return f"{self.name} ({self.class_name})"

    def save(self, *args, **kwargs):
        if not self.arguments:
            cls = self.get_class()
            self.arguments = get_all_init_args(cls)
        super().save(*args, **kwargs)

    def get_class(self) -> AbstractStrategy:
        return StrategyRegistry.get_class(self.class_name)

    def get_description(self) -> str:
        """
        Возвращает docstring (описание) выбранной стратегии.
        """
        cls = self.get_class()
        return (cls.__doc__ or "").strip()

    def instantiate(self) -> AbstractStrategy:
        cls = self.get_class()
        return cls(
            **self.arguments,
            close_position_by_opposite_signal=self.close_position_by_opposite_signal,
            close_position_by_strategy=self.close_position_by_strategy,
            close_position_by_stop_loss=self.close_position_by_stop_loss,
            close_position_by_take_profit=self.close_position_by_take_profit,
        )


class ArbitrageStrategy(ActiveManagerMixin, TimeStampedMixin, models.Model):
    name = models.CharField(
        max_length=100,
        verbose_name="Название стратегии",
        unique=True,
    )
    class_name = models.CharField(
        max_length=100,
        choices=ArbitrageStrategyRegistry.get_choices,
        verbose_name="Класс стратегии",
    )
    arguments = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Параметры (аргументы)",
    )

    class Meta:
        verbose_name = "Арбитражная стратегия"
        verbose_name_plural = "Арбитражные стратегии"

    def __str__(self):
        return f"{self.name} ({self.class_name})"

    def save(self, *args, **kwargs):
        if not self.arguments:
            cls = self.get_class()
            self.arguments = get_all_init_args(cls)
        super().save(*args, **kwargs)

    def get_class(self) -> AbstractArbitrageStrategy:
        return ArbitrageStrategyRegistry.get_class(self.class_name)

    def get_description(self) -> str:
        """
        Возвращает docstring (описание) выбранного risk-менеджера.
        """
        cls = self.get_class()
        return (cls.__doc__ or "").strip()

    def instantiate(self, **kwargs) -> AbstractStrategy:
        cls = self.get_class()
        return cls(**self.arguments, **kwargs)
