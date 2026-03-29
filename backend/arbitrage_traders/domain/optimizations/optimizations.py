from __future__ import annotations

import asyncio
import math
from collections.abc import Callable, Iterator
from datetime import datetime
from decimal import Decimal
from typing import Any

from exchanges.domain import Timeframe, TradingPair

from ..risk_managers.base import AbstractArbitrageRiskManager
from ..schemas import (
    ArbitrageCandle,
    ArbitrageTraderOptimizationResult,
    OptimizationResult,
    TraderStatus,
)
from ..strategies.base import AbstractArbitrageStrategy
from ..traders.traders import ArbitrageTrader
from .base import AbstractOptimizationAlgorithm


class ArbitrageTraderOptimizer:
    def __init__(
        self,
        optimization_algorithm: AbstractOptimizationAlgorithm,
        get_candle_iterator: Callable[[], Iterator[ArbitrageCandle]],
        left_trading_pair: TradingPair,
        right_trading_pair: TradingPair,
        timeframe: Timeframe,
        strategy_class: type[AbstractArbitrageStrategy],
        risk_manager_class: type[AbstractArbitrageRiskManager],
        initial_balance: Decimal,
        max_positions_count: int,
        close_position_by_strategy: bool = True,
        close_position_by_opposite_signal: bool = True,
        roi_weight: Decimal = Decimal("0.4"),
        r2_weight: Decimal = Decimal("0.3"),
        sharpe_weight: Decimal = Decimal("0.2"),
        win_rate_weight: Decimal = Decimal("0.1"),
    ):
        self.optimization_algorithm = optimization_algorithm
        self.get_candle_iterator = get_candle_iterator
        self.left_trading_pair = left_trading_pair
        self.right_trading_pair = right_trading_pair
        self.timeframe = timeframe
        self.strategy_class = strategy_class
        self.risk_manager_class = risk_manager_class
        self.initial_balance = initial_balance
        self.max_positions_count = max_positions_count
        self.close_position_by_strategy = close_position_by_strategy
        self.close_position_by_opposite_signal = close_position_by_opposite_signal
        self.roi_weight = roi_weight
        self.r2_weight = r2_weight
        self.sharpe_weight = sharpe_weight
        self.win_rate_weight = win_rate_weight

        total_weight = roi_weight + r2_weight + sharpe_weight + win_rate_weight
        if total_weight > Decimal("1.0"):
            raise ValueError(
                f"Сумма весов должна быть не больше 1.0, но получено {total_weight}"
            )

    def optimize(self) -> ArbitrageTraderOptimizationResult:
        """Запускает оптимизацию с префиксами для разделения параметров."""
        dt_start = datetime.now()
        params_constraints: dict[str, tuple] = {}
        for name, constraint in self.strategy_class.PARAM_CONSTRAINTS.items():  # type: ignore[attr-defined]
            params_constraints[f"strategy_{name}"] = constraint
        for name, constraint in self.risk_manager_class.PARAM_CONSTRAINTS.items():  # type: ignore[attr-defined]
            params_constraints[f"risk_manager_{name}"] = constraint

        result: OptimizationResult = self.optimization_algorithm.optimize(
            score_function=self.get_score,
            params_constraints=params_constraints,
        )
        trader = self.get_trader(params=result.params)
        asyncio.run(trader.reboot(candle_iterator=self.get_candle_iterator()))

        return ArbitrageTraderOptimizationResult(
            pnl=trader.get_pnl(),
            win_rate=trader.get_win_rate(),
            avg_candles_per_position=trader.get_avg_candles_per_position(),
            pnl_r2=trader.get_pnl_r2(),
            roi=trader.get_roi(),
            sharpe=trader.get_sharpe_ratio(),
            total_positions=trader.get_total_positions(),
            strategy_arguments={
                k.replace("strategy_", ""): v
                for k, v in result.params.items()
                if k.startswith("strategy_")
            },
            risk_manager_arguments={
                k.replace("risk_manager_", ""): v
                for k, v in result.params.items()
                if k.startswith("risk_manager_")
            },
            duration=datetime.now() - dt_start,
        )

    def get_trader(self, params: dict[str, Any]) -> ArbitrageTrader:
        """Создает арбитражного трейдера с заданными параметрами."""
        strategy_params = {
            k.replace("strategy_", ""): v
            for k, v in params.items()
            if k.startswith("strategy_")
        }
        risk_manager_params = {
            k.replace("risk_manager_", ""): v
            for k, v in params.items()
            if k.startswith("risk_manager_")
        }

        strategy = self.strategy_class(**strategy_params)
        risk_manager = self.risk_manager_class(**risk_manager_params)

        return ArbitrageTrader(
            left_trading_pair=self.left_trading_pair,
            right_trading_pair=self.right_trading_pair,
            timeframe=self.timeframe,
            left_exchange_client=None,
            right_exchange_client=None,
            strategy=strategy,
            risk_manager=risk_manager,
            use_fixed_balance=True,
            initial_balance=self.initial_balance,
            balance=self.initial_balance,
            check_drawdown=False,
            max_drawdown_pct=Decimal("0.0"),
            max_positions_count=self.max_positions_count,
            create_new_orders=False,
            close_position_by_strategy=self.close_position_by_strategy,
            close_position_by_opposite_signal=self.close_position_by_opposite_signal,
            status=TraderStatus.REBOOTING,
        )

    @staticmethod
    def normalize_sigmoid(value: Decimal) -> Decimal:
        """Нормализует значение с помощью sigmoid функции в диапазон [0, 1]."""
        exp_value = Decimal(math.exp(-value))
        return Decimal(1) / (Decimal(1) + exp_value)

    def get_score(self, params: dict[str, Any]) -> Decimal:
        """Симулирует с новыми параметрами и возвращает оценку."""
        trader = self.get_trader(params=params)
        candle_iterator = self.get_candle_iterator()
        asyncio.run(trader.reboot(candle_iterator=candle_iterator))

        roi = trader.get_roi()
        r2 = trader.get_pnl_r2()
        sharpe = trader.get_sharpe_ratio()
        win_rate = trader.get_win_rate()

        normalized_roi = self.normalize_sigmoid(roi)
        normalized_sharpe = self.normalize_sigmoid(sharpe)
        return (
            self.roi_weight * normalized_roi
            + self.r2_weight * r2
            + self.sharpe_weight * normalized_sharpe
            + self.win_rate_weight * win_rate
        )
