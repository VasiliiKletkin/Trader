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
        n_trials: int = 100,
    ):
        self.n_trials = n_trials

    def optimize(
        self,
        target_function: Callable,
        argument_ranges: Dict[str, tuple],
    ) -> OptimizationResult:
        """
        Оптимизирует параметры стратегии и риск-менеджера с помощью Optuna.
        """

        def objective(trial: optuna.Trial) -> float:
            params = {}
            for name, (min_val, max_val) in argument_ranges.items():
                if isinstance(min_val, int):
                    params[name] = trial.suggest_int(name, min_val, max_val)
                else:
                    params[name] = trial.suggest_float(name, min_val, max_val)

            value = target_function(params)
            return float(value)

        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=self.n_trials)

        return OptimizationResult(
            value=study.best_value,
            params=study.best_params,  # Плоский dict
        )


class GenerationOptimizationAlgorithm(AbstractOptimizationAlgorithm):
    def __init__(
        self,
        generations: int = 10,
        population_size: int = 100,
    ):
        self.generations = generations
        self.population_size = population_size

    def optimize(
        self,
        target_function: Callable,
        argument_ranges: Dict[str, tuple],  # Плоский dict
    ) -> OptimizationResult:
        creator.create("FitnessMax", base.Fitness, weights=(1.0,))
        creator.create("Individual", list, fitness=creator.FitnessMax)
        self.toolbox = base.Toolbox()

        argument_names = list(argument_ranges.keys())

        for name, (min_val, max_val) in argument_ranges.items():
            if (isinstance(min_val, int) and isinstance(max_val, int)) or (
                isinstance(min_val, float) and isinstance(max_val, float)
            ):
                self.toolbox.register(name, random.randint, min_val, max_val)
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
            profit = target_function(params)  # Передаем плоский dict
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

        # Лучший результат
        best_ind = max(population, key=lambda x: x.fitness.values)
        best_arguments = dict(zip(argument_names, best_ind))
        return OptimizationResult(
            theoretical_profit=best_ind.fitness.values[0],
            strategy_arguments={k: v for k, v in best_arguments.items() if k in argument_ranges},
            risk_manager_arguments={k: v for k, v in best_arguments.items() if k in argument_ranges},
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
        Запускает оптимизацию. Предполагаем уникальные ключи параметров между strategy и risk_manager.
        """
        # Объединяем все параметры в плоский dict (предполагаем уникальность ключей)
        argument_ranges = {**self.strategy.PARAM_CONSTRAINTS, **self.risk_manager.PARAM_CONSTRAINTS}

        return self.optimization_algorithm.optimize(
            target_function=self.get_trader_theoretical_profit,
            argument_ranges=argument_ranges,
        )

    def get_trader_theoretical_profit(self, params: Dict[str, any]) -> float:
        """
        Симулирует с новыми параметрами. Разделяет плоский dict на strategy и risk_manager по ключам.
        """
        try:
            # Разделяем параметры (предполагаем уникальность ключей)
            strategy_params = {k: v for k, v in params.items() if k in self.strategy.PARAM_CONSTRAINTS}
            risk_manager_params = {k: v for k, v in params.items() if k in self.risk_manager.PARAM_CONSTRAINTS}

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

        except Exception as e:
            print(f"Ошибка в симуляции с параметрами {params}: {e}")
            return float("-inf")
