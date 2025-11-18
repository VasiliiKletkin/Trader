import asyncio
from decimal import Decimal
from typing import Any, Dict, Iterator

import optuna
from exchanges.domain import Candle as DomainCandle
from exchanges.domain import Timeframe, TradingPair
from risk_managers.domain import AbstractRiskManager
from strategies.domain import AbstractStrategy
from traders.domain import Trader

from .shemas import OptimizerResult


class Optimizer:
    def __init__(
        self,
        candles_iterator: Iterator[DomainCandle],
        trading_pair: TradingPair,
        timeframe: Timeframe,
        strategy: AbstractStrategy,
        risk_manager: AbstractRiskManager,
        initial_balance: Decimal,
        max_drawdown_pct: Decimal,
        max_positions_count: int,
        current_balance: Decimal,
        trail_stop_enabled: bool = False,
        close_position_by_take_profit: bool = True,
        close_position_by_stop_loss: bool = True,
        close_position_by_strategy: bool = True,
        close_position_by_opposite_signal: bool = True,
    ):
        self.trading_pair = trading_pair
        self.timeframe = timeframe
        self.strategy = strategy
        self.risk_manager = risk_manager
        self.initial_balance = initial_balance
        self.max_drawdown_pct = max_drawdown_pct
        self.max_positions_count = max_positions_count
        self.trail_stop_enabled = trail_stop_enabled
        self.create_new_orders = True
        self.close_position_by_opposite_signal = close_position_by_opposite_signal
        self.close_position_by_strategy = close_position_by_strategy
        self.close_position_by_take_profit = close_position_by_take_profit
        self.close_position_by_stop_loss = close_position_by_stop_loss
        self.current_balance = current_balance

        self.candles = list(candles_iterator)

    def optimize(self, n_trials: int = 5) -> OptimizerResult:
        """
        Оптимизирует параметры стратегии с помощью Optuna (байесовская оптимизация).
        """
        argument_ranges = self.strategy.PARAM_CONSTRAINTS

        def objective(trial):
            arguments = {}
            for name, (min_val, max_val) in argument_ranges.items():
                if isinstance(min_val, int):
                    arguments[name] = trial.suggest_int(name, min_val, max_val)
                else:
                    arguments[name] = trial.suggest_float(name, min_val, max_val)

            profit = self.get_trader_profit(arguments, iter(self.candles))
            return float(profit)

        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=n_trials, show_progress_bar=True)

        return OptimizerResult(
            theoretical_profit=study.best_value,
            strategy_arguments=study.best_params,
        )

    def get_trader_profit(
        self,
        arguments: Dict[str, Any],
    ) -> float:
        """
        Симулирует с новыми параметрами стратегии на переданных candles_iterator.
        """
        strategy = self.strategy.__class__(**arguments)
        trader = Trader(
            trading_pair=self.trading_pair,
            timeframe=self.timeframe,
            exchange_client=None,
            strategy=strategy,
            risk_manager=self.risk_manager,
            initial_balance=self.initial_balance,
            max_drawdown_pct=self.max_drawdown_pct,
            max_positions_count=self.max_positions_count,
            current_balance=self.current_balance,
            trail_stop_enabled=self.trail_stop_enabled,
            create_new_orders=self.create_new_orders,
            close_position_by_take_profit=self.close_position_by_take_profit,
            close_position_by_stop_loss=self.close_position_by_stop_loss,
            close_position_by_strategy=self.close_position_by_strategy,
            close_position_by_opposite_signal=self.close_position_by_opposite_signal,
        )

        asyncio.run(trader.reboot(candles_iterator=iter(self.candles)))
        return trader.get_theoretical_profit()
