import random
from collections.abc import Callable
from typing import Any

import optuna
from deap import base, creator, tools

from ..schemas import OptimizationResult
from .base import AbstractOptimizationAlgorithm, ArbitrageOptimizerRegistry


@ArbitrageOptimizerRegistry.register
class OptunaOptimizationAlgorithm(AbstractOptimizationAlgorithm):
    def __init__(
        self,
        n_trials: int = 500,
    ):
        self.n_trials = n_trials

    def optimize(
        self,
        score_function: Callable,
        params_constraints: dict[str, tuple],
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
                    params[name] = trial.suggest_float(
                        name, min_val, max_val, step=0.001
                    )  # type: ignore[assignment]
                else:
                    raise ValueError(f"Неподдерживаемый тип диапазона для {name}")
            value = score_function(params)
            return float(value)

        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=self.n_trials)
        best_params = {
            k: round(v, 3) if isinstance(v, float) else v
            for k, v in study.best_params.items()
        }
        return OptimizationResult(
            value=study.best_value,
            params=best_params,
        )


@ArbitrageOptimizerRegistry.register
class GenerationOptimizationAlgorithm(AbstractOptimizationAlgorithm):
    def __init__(
        self,
        generations: int = 50,
        population_size: int = 100,
    ):
        self.generations = generations
        self.population_size = population_size
        if not hasattr(creator, "FitnessMax"):
            creator.create("FitnessMax", base.Fitness, weights=(1.0,))
        if not hasattr(creator, "Individual"):
            creator.create("Individual", list, fitness=creator.FitnessMax)

    def optimize(
        self,
        score_function: Callable,
        params_constraints: dict[str, tuple],
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
            profit = score_function(params)
            return (float(profit),)

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
            fitnesses = list(map(self.toolbox.evaluate, invalid_ind))
            for ind, fit in zip(invalid_ind, fitnesses):
                ind.fitness.values = fit

            population[:] = offspring

        best_ind = max(population, key=lambda x: x.fitness.values)
        best_arguments: dict[str, Any] = {
            k: round(v, 3) if isinstance(v, float) else v
            for k, v in zip(argument_names, best_ind)
        }
        return OptimizationResult(
            value=best_ind.fitness.values[0],
            params=best_arguments,
        )
