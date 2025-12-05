import asyncio
import random
from decimal import Decimal
from typing import Any, Callable, Dict, Iterator

import optuna
from deap import base, creator, tools
from exchanges.domain import Candle as DomainCandle
from exchanges.domain import Timeframe, TradingPair
from risk_managers.domain import AbstractRiskManager
from strategies.domain import AbstractStrategy
from traders.domain import Trader

from .base import AbstractOptimizationAlgorithm
from .shemas import OptimizationResult, TraderOptimizationResult


class OptunaOptimizationAlgorithm(AbstractOptimizationAlgorithm):
    def __init__(
        self,
        n_trials: int = 500,
    ):
        self.n_trials = n_trials

    def optimize(
        self,
        target_function: Callable,
        params_constraints: Dict[str, tuple],
    ) -> OptimizationResult:
        """
        Оптимизирует параметры стратегии и риск-менеджера с помощью Optuna.
        """

        def objective(trial: optuna.Trial) -> float:
            params = {}
            for name, (min_val, max_val) in params_constraints.items():
                if isinstance(min_val, int) and isinstance(max_val, int):
                    params[name] = trial.suggest_int(name, min_val, max_val)
                elif isinstance(min_val, float) and isinstance(max_val, float):
                    params[name] = trial.suggest_float(name, min_val, max_val)
                else:
                    raise ValueError(f"Неподдерживаемый тип диапазона для {name}")
            value = target_function(params)
            return float(value)

        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=self.n_trials)

        return OptimizationResult(
            value=study.best_value,
            params=study.best_params,
        )


class GenerationOptimizationAlgorithm(AbstractOptimizationAlgorithm):
    def __init__(
        self,
        generations: int = 50,
        population_size: int = 100,
    ):
        self.generations = generations
        self.population_size = population_size
        creator.create("FitnessMax", base.Fitness, weights=(1.0,))
        creator.create("Individual", list, fitness=creator.FitnessMax)

    def optimize(
        self,
        target_function: Callable,
        params_constraints: Dict[str, tuple],
    ) -> OptimizationResult:
        self.toolbox = base.Toolbox()

        argument_names = list(params_constraints.keys())
        argument_ranges = params_constraints.copy()
        for name, (min_val, max_val) in params_constraints.items():
            if isinstance(min_val, int) and isinstance(max_val, int):
                self.toolbox.register(name, random.randint, min_val, max_val)
            elif isinstance(min_val, float) and isinstance(max_val, float):
                self.toolbox.register(name, random.uniform, min_val, max_val)
            else:
                raise ValueError(f"Неподдерживаемый тип диапазона для {name}")
        self.toolbox.register(
            "individual",
            tools.initCycle,
            creator.Individual,
            [self.toolbox.__getattribute__(name) for name in argument_names],
        )
        self.toolbox.register(
            "population",
            tools.initRepeat,
            list,
            self.toolbox.individual,
        )

        def evaluate(individual) -> tuple:
            """
            Оценивает параметры
            """
            params = dict(zip(argument_names, individual))
            profit = target_function(params)
            return (profit,)

        self.toolbox.register("evaluate", evaluate)
        self.toolbox.register("mate", tools.cxTwoPoint)
        self.toolbox.register(
            "mutate",
            (
                tools.mutUniformInt
                if all(isinstance(v[0], int) for v in argument_ranges.values())
                else tools.mutGaussian
            ),
            low=[argument_ranges[name][0] for name in argument_names],
            up=[argument_ranges[name][1] for name in argument_names],
            indpb=0.2,
        )
        self.toolbox.register("select", tools.selTournament, tournsize=3)

        population = self.toolbox.population(n=self.population_size)
        fitnesses = list(map(self.toolbox.evaluate, population))
        for ind, values in zip(population, fitnesses):
            ind.fitness.values = values

        # Основной цикл GA
        for _ in range(self.generations):
            offspring = self.toolbox.select(population, len(population))
            offspring = list(map(self.toolbox.clone, offspring))

            for child1, child2 in zip(offspring[::2], offspring[1::2]):
                self.toolbox.mate(child1, child2)
                del child1.fitness.values
                del child2.fitness.values

            for mutant in offspring:
                self.toolbox.mutate(mutant)
                del mutant.fitness.values

            invalid_ind = [ind for ind in offspring if not ind.fitness.valid]
            fitnesses = map(self.toolbox.evaluate, invalid_ind)
            for ind, fit in zip(invalid_ind, fitnesses):
                ind.fitness.values = fit

            population[:] = offspring

        best_ind = max(population, key=lambda x: x.fitness.values)
        best_arguments: Dict[str, Any] = dict(zip(argument_names, best_ind))
        return OptimizationResult(
            value=best_ind.fitness.values[0],
            params=best_arguments,
        )


class TraderOptimizer:
    def __init__(
        self,
        optimization_algorithm: AbstractOptimizationAlgorithm,
        candles_iterator: Iterator[DomainCandle],
        trading_pair: TradingPair,
        timeframe: Timeframe,
        strategy_class: type[AbstractStrategy],
        risk_manager_class: type[AbstractRiskManager],
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
        self.optimization_algorithm = optimization_algorithm
        self.trading_pair = trading_pair
        self.timeframe = timeframe
        self.strategy_class = strategy_class
        self.risk_manager_class = risk_manager_class
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
        self.check_drawdown = False

        self.candles = list(candles_iterator)

    def optimize(self) -> TraderOptimizationResult:
        """
        Запускает оптимизацию с префиксами для разделения.
        """
        params_constraints: Dict[str, tuple] = {}
        for name, constraint in self.strategy_class.PARAM_CONSTRAINTS.items():
            params_constraints[f"strategy_{name}"] = constraint
        for name, constraint in self.risk_manager_class.PARAM_CONSTRAINTS.items():
            params_constraints[f"risk_manager_{name}"] = constraint

        result: OptimizationResult = self.optimization_algorithm.optimize(
            target_function=self.get_trader_theoretical_profit,
            params_constraints=params_constraints,
        )

        return TraderOptimizationResult(
            theoretical_profit=result.value,
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
        )

    def get_trader_theoretical_profit(self, params: Dict[str, Any]) -> float:
        """
        Симулирует с новыми параметрами. Разделяет по префиксам.
        """
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

        trader = Trader(
            trading_pair=self.trading_pair,
            timeframe=self.timeframe,
            exchange_client=None,
            strategy=strategy,
            risk_manager=risk_manager,
            initial_balance=self.initial_balance,
            check_drawdown=self.check_drawdown,
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
        return float(trader.get_theoretical_profit())
