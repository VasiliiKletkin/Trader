# CLAUDE.md

Руководство для Claude Code (claude.ai/code) по работе с кодовой базой проекта.

## Обзор проекта

Система криптовалютной торговли на Django + Celery. Поддерживает обычную и арбитражную торговлю на нескольких биржах. Архитектура — Domain-Driven Design: ORM-модели отвечают за персистентность, доменные классы — за асинхронную бизнес-логику.

**Язык:** русский используется в `verbose_name` админки, комментариях и сообщениях коммитов.

**Стек:**
- Python 3.12, Django 5.2+, Celery 5.5+, Redis 6.2+, PostgreSQL 14+
- ccxt (биржевое API), pandas-ta (технический анализ), Pydantic 2.11+ (валидация)
- aiogram 3.22+ (Telegram-бот), Optuna + DEAP (оптимизация)
- loguru (логирование), gunicorn (WSGI), Flower (мониторинг Celery)

## Команды

Все команды выполняются из директории `backend/`. Зависимости управляются через Poetry.

```bash
# Установка зависимостей
cd backend && poetry install

# Запуск тестов (SQLite + eager Celery, настроено в pyproject.toml)
cd backend && poetry run pytest
cd backend && poetry run pytest traders/tests/test_traders.py  # один файл
cd backend && poetry run pytest -k "test_handle_candle"         # один тест

# Линтинг и форматирование (ruff заменяет flake8/isort/black)
cd backend && poetry run ruff check .
cd backend && poetry run ruff check --fix .
cd backend && poetry run ruff format .

# Проверка типов
cd backend && poetry run mypy .

# Сканирование безопасности
cd backend && poetry run bandit -r . -s B101,B107,B110,B311 -x tests,migrations

# Django
cd backend && python manage.py makemigrations
cd backend && python manage.py migrate
cd backend && python manage.py shell

# Docker
docker-compose up                    # все сервисы
docker-compose up --build            # пересборка
docker-compose exec backend python manage.py shell
```

### Makefile-цели (из корня проекта)

Makefile подключает `.env` через `include .env`, поэтому все переменные окружения доступны автоматически. Для Django shell достаточно: `make dshell`.

| Цель | Описание |
|------|----------|
| `dstrt` | Миграции + сбор статики |
| `dupbuild` | docker-compose up --build |
| `dup` | docker-compose up |
| `dstop` | docker-compose stop |
| `dmigr` | makemigrations + migrate |
| `duser` | Создать суперпользователя |
| `dshell` | Django shell |
| `dcreatedb` / `ddeletedb` | Создать / удалить базу PostgreSQL |
| `dcreatedump` / `dloaddump` | Дамп / восстановление базы |

### Pre-commit хуки

Запускаются автоматически: ruff (lint + format + fix), bandit, django-upgrade (target 5.1), trailing-whitespace, end-of-file-fixer, проверка YAML/TOML/JSON, детекция приватных ключей и debug-стейтментов, poetry check.

## Архитектура

### Структура проекта

```
Trader/
├── .github/workflows/       # CI/CD (ci.yml, cd-staging.yml, cd-production.yml)
├── docker-compose.yml        # 10 сервисов (postgres, redis, backend, beat, 5 workers, flower)
├── Makefile                  # Docker-команды
├── postgres/data/            # Том PostgreSQL
├── redis/data/               # Том Redis
└── backend/
    ├── pyproject.toml        # Зависимости, конфиг ruff/mypy/pytest
    ├── Dockerfile            # Python 3.12-slim, Poetry 2.1.2, user appuser
    ├── entrypoint.sh         # Docker entrypoint
    ├── conftest.py           # Глобальные pytest-фикстуры
    ├── manage.py
    ├── core/                 # Настройки Django, Celery, утилиты
    ├── exchanges/            # Биржи, торговые пары, свечи
    ├── exchange_clients/     # API-клиенты бирж, балансы, ордера
    ├── candle_sources/       # Источники свечей
    ├── traders/              # Основной торговый движок
    ├── arbitrage_traders/    # Арбитражная торговля
    └── telegram_bots/       # Telegram-уведомления
```

### Структура каждого Django-приложения

```
app/
├── models/                # ORM-модели (или models.py)
│   ├── traders.py         # Персистентность, DB-запросы, instantiate()/sync()
│   ├── strategies.py      # Стратегии (Registry-паттерн)
│   └── risk_managers.py   # Риск-менеджеры (Registry-паттерн)
├── domain/
│   ├── traders/
│   │   └── base.py        # Доменные классы (async бизнес-логика)
│   ├── strategies/
│   │   ├── base.py        # Абстрактная стратегия
│   │   └── *.py           # Конкретные реализации
│   ├── risk_managers/
│   │   ├── base.py        # Абстрактный риск-менеджер + миксины
│   │   └── *.py           # Конкретные комбинации миксинов
│   ├── optimizations/     # Алгоритмы оптимизации
│   └── schemas.py         # Pydantic-модели, перечисления
├── tasks/                 # Celery-задачи (или tasks.py)
├── admin/                 # Django Admin (или admin.py)
├── charts/                # Графики (equity curve, сигналы, точность)
└── tests/
    ├── conftest.py        # Фикстуры приложения
    ├── models/            # Тесты моделей
    ├── domain/            # Тесты доменной логики
    └── tasks/             # Тесты задач
```

## Domain-Driven Design

### Паттерн ORM ↔ Domain

ORM и доменный слой связаны двумя методами на ORM-моделях:

```python
# ORM → Domain: создаёт доменный объект из ORM-модели
domain_trader = trader_orm.instantiate()

# Domain → ORM: сохраняет состояние домена обратно в БД
trader_orm.sync(domain_trader)
```

Доменные классы используют `async/await` для взаимодействия с биржевым API. Celery-задачи связывают sync/async через `asyncio.run()`.

### Паттерн Registry

Стратегии, риск-менеджеры и клиенты бирж регистрируются через `core.utils.registry.Registry`.

```python
# Регистрация (автоматическая через __init_subclass__)
class MovingAverageCrossoverStrategy(AbstractStrategy):
    ...  # автоматически регистрируется в StrategyRegistry

# В ORM-модели хранятся:
# - class_name (CharField) — имя зарегистрированного класса
# - arguments (JSONField) — параметры для конструктора

# Разрешение в runtime:
cls = StrategyRegistry.get_class("MovingAverageCrossoverStrategy")
instance = cls(**arguments)
```

**Все реестры:**

| Реестр | Базовый класс | Где используется |
|--------|--------------|-----------------|
| `StrategyRegistry` | `AbstractStrategy` | `traders.models.Strategy` |
| `RiskManagerRegistry` | `AbstractRiskManager` | `traders.models.RiskManager` |
| `OptimizerRegistry` | `AbstractOptimizationAlgorithm` | `traders.models.TraderOptimizationAlgorithm` |
| `TraderRegistry` | `AbstractTrader` | `traders.models.Trader` |
| `ExchangeClientRegistry` | `AbstractExchangeClient` | `exchange_clients.models.ExchangeClient` |
| `CandleSourceRegistry` | `AbstractCandleSource` | `candle_sources.models.CandleSource` |
| `ArbitrageStrategyRegistry` | `AbstractArbitrageStrategy` | `arbitrage_traders.models.ArbitrageStrategy` |
| `ArbitrageRiskManagerRegistry` | `AbstractArbitrageRiskManager` | `arbitrage_traders.models.ArbitrageRiskManager` |
| `ArbitrageOptimizerRegistry` | — | `arbitrage_traders.models.TraderOptimizationAlgorithm` |

### Параметрическая система стратегий

Каждый доменный класс декларирует `PARAM_CONSTRAINTS: dict[str, tuple[min, max]]` — диапазоны допустимых значений параметров. Оптимизатор читает ограничения и генерирует комбинации параметров.

```python
class MovingAverageCrossoverStrategy(AbstractStrategy):
    PARAM_CONSTRAINTS = {
        "fast_period": (10, 80),
        "slow_period": (50, 250),
    }
```

### Конвейер обработки сигналов

```
Свеча → Strategy.get_signal() → TraderSignal (BUY/SELL/WAIT)
         ↓
      Trader.can_open_position() — проверка лимитов, баланса, drawdown
         ↓
      RiskManager.calculate_position_size() — размер позиции
      RiskManager.get_stop_loss() / get_take_profit()
         ↓
      Trader.open_position() → TraderPosition
         ↓
      Trader.handle_opened_positions() — обход открытых позиций
         ↓
      Strategy.position_should_be_closed() → PositionCloseReason | None
         ↓
      Trader.close_position() → обновление позиции, PnL
```

## Django-приложения

### exchanges — Биржи и свечи

**Модели:**
- `Exchange` — определение биржи (name, class_name, candle_fetch_limit=999)
- `TradingPair` — торговая пара (name, symbol, min_amount, max_amount, fee_percent)
- `ExchangeTradingPair` — привязка пары к бирже (unique: exchange + trading_pair)
- `Candle` — абстрактная модель OHLCV (open, high, low, close, volume, timestamp)
- `ExchangeCandle` — свеча с биржи (unique: exchange + timeframe + trading_pair + timestamp)

### exchange_clients — API-клиенты

**Модели:**
- `ExchangeClientProxy` — конфигурация прокси (protocol, host, port, auth; check_obj() для тестирования)
- `ExchangeClient` — учётные данные API (api_key, api_secret, demo, proxy; unique: api_key + api_secret)
- `ExchangeClientBalance` — снимок баланса (currency, free, used, total, debt)
- `ExchangeClientOrder` — исполненный ордер (exchange_order_id, status, type, side, price, amount, cost, fee)

**Доменные реализации:**
- `ByBitExchangeClient` — через ccxt.async_support.bybit, поддержка demo-режима и прокси

### candle_sources — Источники свечей

**Модели:**
- `CandleSource` — связывает exchange_client + trading_pair + timeframe (unique constraint)
- `CandleSourceError` — ошибки при загрузке свечей

**Ключевые методы:**
- `fetch_candles()` — async загрузка с биржи
- `sync_candles()` — загрузка + сохранение в БД
- `get_candles(start, end)` — запрос за диапазон
- `get_last_candles(count)` — последние N свечей

### traders — Торговый движок

**Модели:**
- `Trader` — ядро: candle_source, exchange_client, strategy, risk_manager + параметры торговли
- `Strategy` — стратегия (class_name + arguments, Registry)
- `RiskManager` — риск-менеджер (class_name + arguments, Registry)
- `TraderSignal` — сгенерированный сигнал (trader, candle, type, price, data)
- `TraderPosition` — позиция (type, status, amount, open/close price, SL/TP, close_reason)
- `TraderOrder` — связь позиции и биржевого ордера
- `TraderError` — ошибки трейдера
- `TraderOptimizationAlgorithm` — алгоритм оптимизации (Registry)
- `TraderOptimizer` — конфигурация оптимизации с весами метрик

**Настройки трейдера:**
- `use_fixed_balance` / `initial_balance` — фиксированный баланс vs реальный
- `check_drawdown` / `max_drawdown_pct` — контроль просадки
- `create_new_orders` — создавать реальные ордера на бирже
- `max_positions_count` — лимит одновременных позиций
- `close_position_by_opposite_signal` — закрытие по обратному сигналу
- `close_position_by_strategy` — закрытие по логике стратегии
- `close_position_by_stop_loss` / `close_position_by_take_profit` — SL/TP
- `trail_stop_enabled` — трейлинг стоп

**Графики (charts/):**
- equity_curve — кривая доходности
- position_signal_chart — график позиций и сигналов
- accuracy_chart — точность

### arbitrage_traders — Арбитраж

**Ключевые отличия от traders:**
- `ArbitrageTrader` — два exchange_client (left/right) и два candle_source (left/right)
- clean() валидирует что клиенты на разных биржах
- Нет SL/TP и trail_stop — только закрытие по сигналу/стратегии
- `SimpleArbitrageStrategy` — торговля на спреде между биржами (open_threshold, close_threshold)

### telegram_bots — Уведомления

- `TelegramBot` — конфигурация бота (name, token)
- `TelegramChat` — подписка чата (bot, chat_id, name)
- `send_notification(message)` — отправка через aiogram

## Стратегии торговли

### Обычные стратегии (9 реализаций)

| Стратегия | Описание | Параметры |
|-----------|----------|-----------|
| `RenkoStrategy` | Ренко-кирпичи | threshold_up, threshold_down, count_bricks |
| `MoneyFlowIndexStrategy` | Money Flow Index (MFI) | period, overbought, oversold, median |
| `CounterMoneyFlowIndexStrategy` | Инверсный MFI | period, overbought, oversold, median |
| `StochasticStrategy` | Стохастик | k_period, d_period, overbought, oversold, median |
| `CounterStochasticStrategy` | Стохастик на пересечениях | k_period, d_period, overbought, oversold, median |
| `DonchianCrossoverStrategy` | Каналы Дончиана | fast_period, slow_period |
| `MovingAverageCrossoverStrategy` | Пересечение MA | fast_period, slow_period |
| `GridTradingStrategy` | Сеточная торговля (ATR) | narrow_grid, wide_grid, period |
| `MeanReversionChannelStrategy` | Возврат к среднему | period, sigma_mult, threshold |

### Арбитражные стратегии

| Стратегия | Описание | Параметры |
|-----------|----------|-----------|
| `SimpleArbitrageStrategy` | Спред между биржами | open_threshold, close_threshold |

## Риск-менеджеры

### Система миксинов

Риск-менеджеры собираются через множественное наследование из трёх типов миксинов:

**Stop Loss:**
- `StopLossPercentMixin` — SL = цена ± процент
- `StopLossExtremumMixin` — SL = мин/макс последних N свечей

**Take Profit:**
- `TakeProfitPercentMixin` — TP = цена ± процент
- `TakeProfitRiskRewardMixin` — TP = цена ± (расстояние_риска × reward_risk)

**Position Size:**
- `PositionSizeAllInMixin` — весь баланс
- `PositionSizeByRiskMixin` — размер по риску (balance × risk_pct / stop_distance)
- `PositionSizeLimitMixin` — ограничение максимального размера

### Конкретные комбинации (8 штук)

| Класс | SL | TP | Size |
|-------|----|----|------|
| `SLPercentTPPercentPSAllInRiskManager` | Процент | Процент | Весь баланс |
| `SLPercentTPPercentPSByRiskRiskManager` | Процент | Процент | По риску |
| `SLPercentTPRiskRewardPSAllInRiskManager` | Процент | R:R | Весь баланс |
| `SLPercentTPRiskRewardPSByRiskRiskManager` | Процент | R:R | По риску |
| `SLExtremumTPPercentPSAllInRiskManager` | Экстремум | Процент | Весь баланс |
| `SLExtremumTPPercentPSByRiskRiskManager` | Экстремум | Процент | По риску |
| `SLExtremumTPRiskRewardPSAllInRiskManager` | Экстремум | R:R | Весь баланс |
| `SLExtremumTPRiskRewardPSByRiskRiskManager` | Экстремум | R:R | По риску |

### Арбитражные риск-менеджеры

- `PSAllInArbitrageRiskManager` — весь баланс
- `PSPercentArbitrageRiskManager` — процент от баланса

## Оптимизация параметров

### Алгоритмы

| Алгоритм | Библиотека | Параметры |
|----------|------------|-----------|
| `OptunaOptimizationAlgorithm` | Optuna | n_trials (default: 500) |
| `GenerationOptimizationAlgorithm` | DEAP | generations (50), population_size (100) |

### Мульти-метричное скоринг

`TraderOptimizer` оценивает результат по взвешенной сумме нормализованных метрик:
- ROI (roi_weight)
- R² кривой PnL (r2_weight)
- Profit Factor (profit_factor_weight)
- Sharpe Ratio (sharpe_ratio_weight)
- Max Drawdown (max_drawdown_weight)
- Win Rate (win_rate_weight)
- Количество сделок (trades_count_weight)

Нормализация — через sigmoid. Результат: `TraderOptimizationResult` с лучшими параметрами и метриками.

## Celery

### Очереди и воркеры

| Воркер | Очередь | Autoscale | Назначение |
|--------|---------|-----------|------------|
| worker_sources_fetch | `sources_fetch_last_candles_for_exchange_client` | 5-1 | Загрузка свечей |
| worker_traders_process | `traders_process_for_exchange_client` | 5-1 | Обработка трейдеров |
| worker_trader_reboot | `trader_reboot` | — | Бэктестинг (reboot) |
| worker_optimizer_optimize | `optimizer_optimize` | — | Оптимизация параметров |
| worker | default | — | Общие задачи |

### Beat-расписание

| Задача | Расписание |
|--------|-----------|
| `sources_fetch_last_candles` | Каждую минуту |
| `exchange_clients_fetch_balances` | Каждый час |
| `traders_daily_report` | Ежедневно в 10:00 |

### Конвейер задач

```
Beat (каждую минуту)
  → sources_fetch_last_candles (fanout по exchange_client)
    → fetch + sync свечей для каждого CandleSource
      → traders_process_for_exchange_client (для каждого активного трейдера)
        → handle_candle → сигналы → позиции → ордера
```

## Перечисления (Enums)

### Основные (traders/domain/schemas.py)

| Enum | Значения |
|------|---------|
| `TraderStatus` | ENABLED, DISABLED, PAUSED, REBOOTING, ERROR |
| `SignalType` | BUY, SELL, WAIT |
| `PositionType` | LONG, SHORT |
| `PositionStatus` | OPENED, CLOSED |
| `PositionCloseReason` | TAKE_PROFIT, STOP_LOSS, OPPOSITE_SIGNAL, STRATEGY, TIMEOUT, MANUAL |
| `Timeframe` | ONE_MINUTE, FIVE_MINUTES, FIFTEEN_MINUTES, ONE_HOUR, FOUR_HOURS, ONE_DAY, ONE_WEEK |
| `OptimizerStatus` | ENABLED, DISABLED |

### Exchange Client (exchange_clients/domain/schemas.py)

| Enum | Значения |
|------|---------|
| `OrderStatus` | OPENED, CLOSED, CANCELED |
| `OrderType` | MARKET, LIMIT |
| `OrderSide` | BUY, SELL |

## Pydantic-схемы

### Доменные объекты

| Схема | Назначение | Ключевые поля |
|-------|-----------|---------------|
| `TraderSignal` | Торговый сигнал | timestamp, price, candle, type, data |
| `TraderPosition` | Позиция | type, status, amount, open/close_price, SL/TP, close_reason, pnl |
| `TraderError` | Ошибка | timestamp, message, type, traceback |
| `ExchangeClientOrder` | Ордер | id, timestamp, status, side, type, price, amount, fee, cost |
| `ExchangeClientBalance` | Баланс | currency, total, free, used, debt |

### Данные стратегий (вложены в TraderSignal.data)

| Схема | Стратегия |
|-------|-----------|
| `RenkoBrick` / `RenkoData` | RenkoStrategy |
| `MoneyFlowIndexStrategyData` | MoneyFlowIndexStrategy |
| `StochasticData` | StochasticStrategy |
| `DonchianCrossoverData` | DonchianCrossoverStrategy |
| `MovingAverageCrossoverData` | MovingAverageCrossoverStrategy |
| `GridTradingData` | GridTradingStrategy |
| `MeanReversionChannelData` | MeanReversionChannelStrategy |

## Docker

### Сервисы (docker-compose.yml)

10 сервисов: postgres (14.18-alpine), redis (6.2-alpine), backend (gunicorn + debugpy:5678), beat, 5 Celery-воркеров, flower (порт 5555).

### Dockerfile

- Base: python:3.12-slim
- Poetry 2.1.2, user: appuser (UID 5678)
- Порт: 8000 (gunicorn)
- Системные зависимости: build-essential, libpq-dev

## Миксины (core/utils/mixins.py)

| Миксин | Поля | Менеджеры |
|--------|------|-----------|
| `ActiveManagerMixin` | `is_active` (BooleanField) | `objects` (все), `active_objects` (фильтр) |
| `TimeStampedMixin` | `created_at`, `updated_at` | — |

## CI/CD

### GitHub Actions

| Workflow | Триггер | Этапы |
|----------|---------|-------|
| `ci.yml` | PR → staging/main | ruff check + format, bandit, pytest |
| `cd-staging.yml` | Push → staging | lint, test, Docker build (tag: staging + SHA), SSH deploy |
| `cd-production.yml` | Push → main | lint, test, Docker build (tag: latest + SHA), SSH deploy |

### Git Flow

```
feature-branch → staging → main
```

## Тестирование

### Конфигурация

Тесты используют SQLite (не Postgres) и eager Celery (задачи выполняются синхронно). Настроено в `pyproject.toml` под `[tool.pytest.ini_options]`.

Coverage: omit `domain/**/base.py` (async-код, тестируется интеграционно).

### Иерархия фикстур

**Глобальные (`backend/conftest.py`):**
- `_mock_send_notification` (autouse) — мокает Telegram-уведомления
- `trading_pair` — BTC/USDT, fee 0.1%
- `timeframe` — ONE_HOUR
- `exchange_candle` — OHLCV доменный объект

**Приложение traders (`traders/tests/conftest.py`):**
- ORM-фикстуры: exchange, trading_pair, exchange_client, candle_source, strategy, risk_manager, trader
- Доменные фикстуры: domain_trading_pair, domain_candle, domain_signal, domain_position
- Связанные объекты: trader_signal, trader_position, closed_trader_position, exchange_client_order, trader_order

**Домен traders (`traders/tests/domain/conftest.py`):**
- Чистые Python-фикстуры (без БД): trading_pair, candle, trader
- Mock-объекты: mock_strategy, mock_risk_manager, mock_exchange_client
- Наборы данных: sample_candles, downtrend_candles

### Паттерны тестирования

- `@pytest.fixture` для всех фикстур, без Django TestCase
- pytest-asyncio для тестов доменного слоя
- Отдельные директории: `tests/models/`, `tests/domain/`, `tests/tasks/`, `tests/admin/`

## Стиль кода

- Python 3.12, длина строки 88
- Ruff — линтинг + форматирование (правила: E, W, F, I, B, C4, UP, DJ, SIM, PTH, RUF)
- Кириллица допускается в строках/комментариях (RUF001-003 игнорируются)
- Миграции исключены из линтинга
- MyPy: плагины django-stubs + pydantic, миграции/тесты исключены
- F401 игнорируется в `__init__.py`, S101 — в тестах

## Настройки Django (core/settings.py)

- LANGUAGE_CODE: ru-ru
- TIME_ZONE: Europe/Moscow
- USE_TZ: True
- Кэш: Redis (timeout 300s, prefix "trader")
- Statement timeout PostgreSQL: 30s
- Логирование: loguru (colorized в dev, JSON в production)

## Переменные окружения (.env)

| Переменная | Назначение |
|------------|-----------|
| `SECRET_KEY` | Django secret key |
| `DEBUG` | Режим отладки |
| `DJANGO_ALLOWED_HOSTS` | Разрешённые хосты |
| `POSTGRES_ENGINE/DATABASE/USER/PASSWORD/HOST/PORT` | PostgreSQL |
| `REDIS_HOST/PORT/USER/PASSWORD/DATABASE` | Redis |
| `CELERY_BROKER` | URL брокера Celery |
| `CELERY_RESULT_BACKEND` | Бэкенд результатов (django-db) |
| `CELERY_TASK_ALWAYS_EAGER` | Синхронное выполнение (True для тестов) |
| `LOG_LEVEL` | Уровень логирования |
