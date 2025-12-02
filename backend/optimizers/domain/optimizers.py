import asyncio
import random
from decimal import Decimal
from typing import Callable, Dict, Iterator

import optuna
from deap import base, creator, tools
from exchanges.domain import Candle as DomainCandle
from exchanges.domain import Timeframe, TradingPair
from risk_managers.domain import AbstractRiskManager
from strategies.domain import AbstractStrategy
from traders.domain import Trader

from .base import AbstractOptimizationAlgorithm
from .shemas import OptimizationResult


class OptunaOptimizationAlgorithm(AbstractOptimizationAlgorithm):
    def __init__(
        self,
        n_trials: int = 500,
    ):
        self.n_trials = n_trials

    def optimize(
        self,
        target_function: Callable,
        strategy_arguments_constraints: Dict[str, tuple],
        risk_manager_arguments_constraints: Dict[str, tuple],
    ) -> OptimizationResult:
        """
        Оптимизирует параметры стратегии и риск-менеджера с помощью Optuna.
        """

        def objective(trial: optuna.Trial) -> float:
            params = {}
            # Стратегия с префиксом
            for name, (min_val, max_val) in strategy_arguments_constraints.items():
                prefixed = f"strategy_{name}"
                if isinstance(min_val, int):
                    params[prefixed] = trial.suggest_int(prefixed, min_val, max_val)
                else:
                    params[prefixed] = trial.suggest_float(prefixed, min_val, max_val)
            # Риск-менеджер с префиксом
            for name, (min_val, max_val) in risk_manager_arguments_constraints.items():
                prefixed = f"risk_manager_{name}"
                if isinstance(min_val, int):
                    params[prefixed] = trial.suggest_int(prefixed, min_val, max_val)
                else:
                    params[prefixed] = trial.suggest_float(prefixed, min_val, max_val)

            value = target_function(params)
            return float(value)

        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=self.n_trials)

        strategy_arguments = {
            k.replace("strategy_", ""): v
            for k, v in study.best_params.items()
            if k.startswith("strategy_")
        }
        risk_manager_arguments = {
            k.replace("risk_manager_", ""): v
            for k, v in study.best_params.items()
            if k.startswith("risk_manager_")
        }

        return OptimizationResult(
            theoretical_profit=study.best_value,
            strategy_arguments=strategy_arguments,
            risk_manager_arguments=risk_manager_arguments,
        )


class GenerationOptimizationAlgorithm(AbstractOptimizationAlgorithm):
    def __init__(
        self,
        generations: int = 50,
        population_size: int = 100,
    ):
        self.generations = generations
        self.population_size = population_size

    def optimize(
        self,
        target_function: Callable,
        strategy_arguments_constraints: Dict[str, tuple],
        risk_manager_arguments_constraints: Dict[str, tuple],
    ) -> OptimizationResult:
        creator.create("FitnessMax", base.Fitness, weights=(1.0,))
        creator.create("Individual", list, fitness=creator.FitnessMax)
        self.toolbox = base.Toolbox()

        argument_ranges = {}
        argument_names = []
        for name, constraints in strategy_arguments_constraints.items():
            prefixed = f"strategy_{name}"
            argument_ranges[prefixed] = constraints
            argument_names.append(prefixed)
        for name, constraints in risk_manager_arguments_constraints.items():
            prefixed = f"risk_manager_{name}"
            argument_ranges[prefixed] = constraints
            argument_names.append(prefixed)

        for name, (min_val, max_val) in argument_ranges.items():
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
        best_arguments: Dict["str", any] = dict(zip(argument_names, best_ind))
        return OptimizationResult(
            theoretical_profit=best_ind.fitness.values[0],
            strategy_arguments={
                k.replace("strategy_", ""): v
                for k, v in best_arguments.items()
                if k.startswith("strategy_")
            },
            risk_manager_arguments={
                k.replace("risk_manager_", ""): v
                for k, v in best_arguments.items()
                if k.startswith("risk_manager_")
            },
        )


class Optimizer:
    def __init__(
        self,
        optimization_algorithm: AbstractOptimizationAlgorithm,
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
        self.optimization_algorithm = optimization_algorithm
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
        self.check_drawdown = False

        self.candles = list(candles_iterator)

    def optimize(self) -> OptimizationResult:
        """
        Запускает оптимизацию с префиксами для разделения.
        """
        return self.optimization_algorithm.optimize(
            target_function=self.get_trader_theoretical_profit,
            strategy_arguments_constraints=self.strategy.PARAM_CONSTRAINTS,
            risk_manager_arguments_constraints=self.risk_manager.PARAM_CONSTRAINTS,
        )

    def get_trader_theoretical_profit(self, params: Dict[str, any]) -> float:
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

        strategy = self.strategy.__class__(**strategy_params)
        risk_manager = self.risk_manager.__class__(**risk_manager_params)

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
