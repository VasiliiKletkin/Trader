import asyncio
from typing import Dict, Any, Iterator
import optuna
from .traders import Trader
from exchanges.domain import Candle as DomainCandle


class TraderOptimizer:
    def __init__(self, trader: Trader, candles_iterator: Iterator[DomainCandle]):
        self.trader = trader
        self.candles = list(candles_iterator)

    def optimize(self, n_trials: int = 5) -> Dict[str, Any]:
        """
        Оптимизирует параметры стратегии с помощью Optuna (байесовская оптимизация).
        """
        argument_ranges = self.trader.strategy.PARAM_CONSTRAINTS

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
        return study.best_params

    def get_trader_profit(
        self,
        arguments: Dict[str, Any],
        candles_iterator: Iterator[DomainCandle],
    ) -> float:
        """
        Симулирует с новыми параметрами стратегии на переданных candles_iterator.
        """
        strategy = self.trader.strategy.__class__(**arguments)
        trader = Trader(
            trading_pair=self.trader.trading_pair,
            timeframe=self.trader.timeframe,
            exchange_client=self.trader.exchange_client,
            strategy=strategy,
            risk_manager=self.trader.risk_manager,
            initial_balance=self.trader.initial_balance,
            max_drawdown_pct=self.trader.max_drawdown_pct,
            max_positions_count=self.trader.max_positions_count,
            current_balance=self.trader.current_balance,
            trail_stop_enabled=self.trader.trail_stop_enabled,
            create_new_orders=self.trader.create_new_orders,
            close_position_by_take_profit=self.trader.close_position_by_take_profit,
            close_position_by_stop_loss=self.trader.close_position_by_stop_loss,
            close_position_by_strategy=self.trader.close_position_by_strategy,
            close_position_by_opposite_signal=self.trader.close_position_by_opposite_signal,
        )

        asyncio.run(trader.reboot(candles_iterator=candles_iterator))
        profit = sum((pos.pnl for pos in trader.positions))
        return profit
