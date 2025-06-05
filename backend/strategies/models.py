import inspect
from django.db import models
from abc import ABC, abstractmethod


class StrategyRegistry:
    _registry = {}

    @classmethod
    def register(cls, strategy_cls):
        cls._registry[strategy_cls.__name__] = strategy_cls

    @classmethod
    def get_choices(cls):
        return [(name, name) for name in cls._registry]

    @classmethod
    def get_class(cls, name):
        try:
            return cls._registry[name]
        except KeyError:
            raise ValueError(f"Strategy '{name}' not found.")


class BaseStrategy(ABC):
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        if not inspect.isabstract(cls):
            StrategyRegistry.register(cls)

    @abstractmethod
    def run(self):
        pass


class RenkoStrategy(BaseStrategy):
    def __init__(self, brick_size: int):
        self.brick_size = brick_size

    def run(self):
        print(f"Running Renko with brick_size = {self.brick_size}")


class Strategy(models.Model):
    is_active = models.BooleanField(default=False)

    name = models.CharField(max_length=100)
    class_name = models.CharField(
        max_length=100,
        choices=StrategyRegistry.get_choices,
        default="RenkoStrategy",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    arguments = models.JSONField()

    def get_strategy_class(self):
        return StrategyRegistry.get_class(self.class_name)

    def instantiate(self, **kwargs):
        cls = self.get_strategy_class()
        return cls(**self.arguments, **kwargs)

    def __str__(self):
        return self.name
