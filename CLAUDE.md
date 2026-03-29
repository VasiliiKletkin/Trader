# CLAUDE.md

Руководство для Claude Code (claude.ai/code) по работе с кодовой базой проекта.

## Обзор проекта

Система криптовалютной торговли на Django + Celery. Поддерживает обычную и арбитражную торговлю на нескольких биржах. Два режима работы: **Celery-задачи** (REST-опрос бирж) и **in-memory воркеры** (Redis Pub/Sub, event-driven). Архитектура — Domain-Driven Design: ORM-модели отвечают за персистентность, доменные классы — за асинхронную бизнес-логику.

**Язык:** русский используется в `verbose_name` админки, комментариях и сообщениях коммитов.

**Стек:**
- Python 3.12, Django 5.2+, Celery 5.5+, Redis 6.2+, PostgreSQL 14+
- ccxt (биржевое API, REST + WebSocket), pandas-ta (технический анализ), Pydantic 2.11+ (валидация)
- aiogram 3.22+ (Telegram-бот), Optuna + DEAP (оптимизация)
- loguru (логирование), gunicorn (WSGI), Flower (мониторинг Celery)
- admin_auto_filters (AutocompleteFilter), django-rangefilter (RangeFilter)

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
| `hooks` | Запуск pre-commit на всех файлах |

### Pre-commit хуки

Запускаются автоматически: ruff (lint + format + fix), bandit, django-upgrade (target 5.1), trailing-whitespace, end-of-file-fixer, проверка YAML/TOML/JSON, детекция приватных ключей и debug-стейтментов, poetry check.

## Архитектура

### Структура проекта

```
Trader/
├── .github/workflows/       # CI/CD (ci-pull-request, checks, build, deploy, cd-staging, cd-production)
├── docker-compose.yml        # Dev: 11 сервисов
├── docker-compose.staging.yml
├── docker-compose.production.yml
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
    ├── exchange_clients/     # API-клиенты бирж (16 бирж), балансы, ордера
    ├── candle_sources/       # Источники свечей (REST + WebSocket)
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
│   │   ├── base.py        # Абстрактный трейдер (generic ABC)
│   │   └── traders.py     # Конкретная реализация
│   ├── strategies/
│   │   ├── base.py        # Абстрактная стратегия
│   │   └── strategies.py  # Конкретные реализации
│   ├── risk_managers/
│   │   ├── base.py        # Абстрактный риск-менеджер + миксины
│   │   └── risk_managers.py # Конкретные комбинации миксинов
│   ├── optimizations/     # Алгоритмы оптимизации
│   ├── ws/                # WebSocket-стримы (только candle_sources)
│   └── schemas.py         # Pydantic-модели, перечисления
├── tasks/                 # Celery-задачи (или tasks.py)
├── admin/                 # Django Admin (или admin.py)
├── charts/                # Графики (equity curve, сигналы, точность)
├── management/commands/   # Management-команды (in-memory воркеры)
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

`sync()` включает: `sync_signals()`, `sync_positions()`, `sync_errors()`.

`load()` загружает в доменный объект:
- **Свечи**: последние N из БД (конвертируются через `candle.instantiate()`)
- **Позиции**: только открытые (OPENED), отсортированные по `opened_at`
- **Сигналы и ошибки**: не загружаются (пустые deque/list)

### Абстрактный трейдер (Generic ABC)

```python
class AbstractTrader[CandleT, SignalT, PositionT: PositionProtocol, StrategyT](ABC):
```

Авторегистрация через `__init_subclass__` → `TraderRegistry`.

**Обязательные async-методы**: `open_position()`, `close_position()`, `handle_candle()`, `handle_opened_positions()`, `reboot()`, `close_all_opened_positions()`.

**Встроенная статистика**: `get_pnl()`, `get_roi()`, `get_win_rate()`, `get_pnl_r2()`, `get_sharpe_ratio()`, `get_avg_pnl_per_position()`.

### Паттерн Registry

Стратегии, риск-менеджеры и клиенты бирж регистрируются через `core.utils.registry.Registry`.

```python
class Registry:
    _registry: dict[str, type]  # заполняется через __init_subclass__

    @classmethod
    def get_choices(cls) -> list[tuple[str, str]]  # для Django choices

    @classmethod
    def get_class(cls, name: str) -> type  # разрешение в runtime
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
| `ArbitrageOptimizerRegistry` | — | `arbitrage_traders.models.ArbitrageOptimizationAlgorithm` |

### Параметрическая система стратегий

Каждый доменный класс декларирует `PARAM_CONSTRAINTS: dict[str, tuple[min, max]]` — диапазоны допустимых значений параметров. Оптимизатор читает ограничения и генерирует комбинации параметров.

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

### Порядок операций внутри handle_candle

```
1. get_signal(candle)          — свеча ещё НЕ в self.candles
2. self.signals.append(signal) — сигнал добавлен
3. self.candles.append(candle) — свеча добавлена в deque
4. handle_opened_positions()   — свеча уже в self.candles
5. can_open_position() → open_position()
```

Стратегия при генерации сигнала (шаг 1) получает `trader.candles` как историю без текущей свечи и текущую свечу как отдельный аргумент.

### Различия обычного и арбитражного трейдера

| Аспект | Trader | ArbitrageTrader |
|--------|--------|-----------------|
| Биржи | Одна | Две (left + right), должны быть разными |
| Свечи | Одна ExchangeCandle | ArbitrageCandle (left + right, timestamp синхронизирован) |
| Позиции | Одна сторона | Две стороны (left_type + right_type, противоположные) |
| Закрытие | SL, TP, стратегия, обратный сигнал | Только стратегия и обратный сигнал |
| Trailing stop | Да | Нет |
| Откат при ошибке | — | Если right ордер не удался, откатывает left обратным ордером |

## Два режима работы

### 1. Celery-задачи (REST)

Beat каждую минуту → fetch свечей с бирж → fanout по exchange_client → handle_candle.

```
Beat (каждую минуту)
  → sources_fetch_last_candles
    ├── REST-источники: fanout по exchange_client
    │     → fetch + upsert свечей → traders_process_by_sources()
    └── WS-источники: sources_sync_from_redis(source_ids)
          → читает кэш из Redis → bulk insert в БД
            → traders_process_by_sources()
```

### 2. In-memory воркеры (Redis Pub/Sub)

Долгоживущие процессы (management commands), держат трейдеров в памяти. Получают свечи через Redis Pub/Sub.

| Команда | Класс | Канал | Назначение |
|---------|-------|-------|------------|
| `run_trader_worker` | `TraderWorker` | `candle:*` | Обычные трейдеры |
| `run_arbitrage_trader_worker` | `ArbitrageTraderWorker` | `arb_candle:*` | Арбитражные трейдеры |
| `run_ws_streams` | `WebSocketStreamManager` | — | WS-стримы свечей |
| `run_ws_candle_sources` | — | — | WS-источники свечей |
| `run_ws_traders` | `StreamManager` | — | WS-стримы балансов и ордеров |

**Жизненный цикл in-memory воркера:**
1. Загрузка активных трейдеров из БД → `instantiate()` + `load()`
2. Подписка на Redis Pub/Sub (`candle:*` или `arb_candle:*`)
3. При получении свечи → `handle_candle()` на доменном трейдере
4. Каждые 600с — `_reconcile_loop()`: перезагрузка из БД (добавление новых, удаление неактивных)
5. Периодический `_sync_all()` — запись состояния обратно в БД
6. Graceful shutdown по SIGTERM/SIGINT

## Django-приложения

### exchanges — Биржи и свечи

**Модели:**
- `Exchange` — определение биржи (name, class_name, max_candles_per_request=999)
- `TradingPair` — торговая пара (name, symbol, type: MarketType, min_amount, max_amount, taker_fee, maker_fee, max_leverage)
- `ExchangeTradingPair` — привязка пары к бирже (unique: exchange + trading_pair)
- `Candle` — абстрактная модель OHLCV (open, high, low, close, volume, timestamp). Decimal(30, 18)
- `ExchangeCandle` — свеча с биржи (unique: exchange + timeframe + trading_pair + timestamp)

### exchange_clients — API-клиенты

**Модели:**
- `ExchangeClientProxy` — конфигурация прокси (protocol, host, port, auth; check_obj() для тестирования)
- `ExchangeClient` — учётные данные API (api_key, api_secret, demo, proxy; unique: api_key + api_secret)
- `ExchangeClientBalance` — снимок баланса (currency, free, used, total, debt)
- `ExchangeClientOrder` — исполненный ордер (exchange_order_id, status, type, side, price, amount, cost, fee)

**Поддерживаемые биржи (16):**
Binance, Bybit, OKX, Kraken, Bitfinex, BitMEX, Coinbase, KuCoin, Bitget, HTX (Huobi), Deribit, Phemex, CoinEX, MEXC, Gateio, Hyperliquid

Все используют ccxt.pro (async) с поддержкой demo-режима и HTTP/SOCKS5 прокси.

**Базовый клиент (`AbstractExchangeClient`):**
- `create_market_order(trading_pair, side, amount, price, params)` — создаёт рыночный ордер
- `fetch_orders(trading_pair, since, limit, params)` — история ордеров
- `fetch_balances()` — снимок балансов

### candle_sources — Источники свечей

**Модели:**
- `CandleSource` — связывает exchange_client + trading_pair + timeframe + mode (unique constraint)
- `CandleSourceError` — ошибки при загрузке свечей

**Режимы получения данных (`CandleSourceMode`):**
- `REST` — периодический fetch через REST API (каждую минуту через Beat)
- `WEBSOCKET` — real-time стриминг через ccxt.pro.watch_ohlcv, кэш в Redis

### traders — Торговый движок

**ORM-модели:**
- `Trader` — ядро: candle_source, exchange_client, strategy, risk_manager + параметры торговли
- `Strategy` — стратегия (class_name + arguments, Registry)
- `RiskManager` — риск-менеджер (class_name + arguments, Registry)
- `TraderSignal` — сгенерированный сигнал (trader, candle, type, price, data). Unique: (trader, timestamp, type)
- `TraderPosition` — позиция (type, status, amount, open/close price, SL/TP, close_reason, total_fee). Unique: (trader, opened_at, amount, type)
- `TraderOrder` — связь позиции и биржевого ордера (trader, order: OneToOne, position)
- `TraderError` — ошибки трейдера (message, type, traceback)
- `TraderOptimizationAlgorithm` — алгоритм оптимизации (Registry)
- `TraderOptimizer` — конфигурация оптимизации с весами метрик и lookback_period (TextChoices)
- `TraderOptimizationResult` — результат: pnl, win_rate, roi, sharpe, r2, strategy/risk_manager arguments, duration
- `TraderOptimizerError` — ошибки оптимизатора

**Настройки трейдера:**
- `use_fixed_balance` / `initial_balance` — фиксированный баланс vs реальный
- `check_drawdown` / `max_drawdown_pct` — контроль просадки
- `create_new_orders` — создавать реальные ордера на бирже
- `max_positions_count` — лимит одновременных позиций
- `candles_lookback_count` — количество свечей в памяти (choices: 50-10000)
- `close_position_by_opposite_signal` — закрытие по обратному сигналу
- `close_position_by_strategy` — закрытие по логике стратегии
- `close_position_by_stop_loss` / `close_position_by_take_profit` — SL/TP
- `trail_stop_enabled` — трейлинг стоп

**ORM-методы Trader:**
- `instantiate(domain_exchange_client)` → `DomainTrader`
- `load(trader)` — загрузка свечей (с `.instantiate()`) и позиций
- `sync(trader)` → `sync_signals()` + `sync_positions()` + `sync_errors()`
- `reboot()` — бэктестинг за 365 дней
- `get_candle_iterator(start, end)` — итератор доменных свечей (с `.instantiate()`)
- Статистика: `get_win_rate()`, `get_fact_pnl()`, `get_theoretical_pnl()`, `get_pnl_r2()`, `get_balance()`
- SQL-аннотации: `theoretical_pnl_annotation()`, `fact_pnl_annotation()`

**Графики (charts/):**
- Стратегии: `RenkoChart`, `MoneyFlowIndexChart`, `StochasticChart`, `DonchianCrossoverChart`, `MovingAverageCrossoverChart`, `GridTradingChart`
- Трейдеры: `EquityCurveChart`, `PositionSignalChart`, `AccuracyChart`

### arbitrage_traders — Арбитраж

**Ключевые отличия от traders:**
- `ArbitrageTrader` — два exchange_client (left/right) и два candle_source (left/right)
- `clean()` валидирует: клиенты на разных биржах, биржи candle_source совпадают с клиентами, таймфреймы совпадают
- Нет SL/TP и trail_stop — только закрытие по сигналу/стратегии
- `ArbitrageTraderPosition` — left_type + right_type, left/right open/close prices, left/right fees
- `ArbitrageTraderOrder` — left_order + right_order

### telegram_bots — Уведомления

- `TelegramBot` — конфигурация бота (name, token)
- `TelegramChat` — подписка чата (bot, chat_id, name)
- `send_notification(message)` — отправка через aiogram (Celery task)

## Pydantic-схемы (доменный слой)

### traders/domain/schemas.py

| Схема | Ключевые поля | Вычисляемые свойства |
|-------|---------------|---------------------|
| `TraderSignal` | timestamp, price, candle: ExchangeCandle, type: SignalType, data | — |
| `TraderPosition` | type, status, amount, open/close_price, SL/TP, total_fee, orders | pnl, pnl_pct, rr, is_closed, open_cost, close_cost |
| `TraderError` | timestamp, message, type, traceback | — |
| `TraderOptimizationResult` | pnl, win_rate, roi, sharpe, pnl_r2, total_positions, strategy/risk_manager_arguments, duration | — |

**Данные стратегий (в TraderSignal.data):** `RenkoData`, `StochasticData`, `DonchianCrossoverData`, `MovingAverageCrossoverData`, `GridTradingData`, `MeanReversionChannelData`

### arbitrage_traders/domain/schemas.py

| Схема | Ключевые поля | Вычисляемые свойства |
|-------|---------------|---------------------|
| `ArbitrageCandle` | left: ExchangeCandle, right: ExchangeCandle | spread (left/right close ratio), timestamp |
| `ArbitrageTraderSignal` | left/right_type, left/right_price, left/right_candle, data | — |
| `ArbitrageTraderPosition` | left/right_type, amount, left/right_open/close_price, left/right_total_fee, left/right_orders | pnl (left_pnl + right_pnl), total_fee, is_closed |

`ArbitrageCandle` валидирует совпадение таймстампов left и right (raises `CandleDesyncError`).

## Стратегии торговли

### Обычные стратегии (9 реализаций)

| Стратегия | Описание | PARAM_CONSTRAINTS |
|-----------|----------|-------------------|
| `RenkoStrategy` | Ренко-кирпичи | threshold_up [0.1-10], threshold_down [0.1-10], count_bricks [1-10] |
| `MoneyFlowIndexStrategy` | MFI (overbought/oversold) | period [10-20], overbought/oversold/median [0-100] |
| `CounterMoneyFlowIndexStrategy` | Инверсный MFI | period [10-20], overbought/oversold/median [0-100] |
| `StochasticStrategy` | Стохастик | k_period [1-50], d_period [1-10], overbought/oversold/median [0-100] |
| `CounterStochasticStrategy` | Стохастик на пересечениях | k_period [1-50], d_period [1-10], overbought/oversold/median [0-100] |
| `DonchianCrossoverStrategy` | Каналы Дончиана | fast_period [5-15], slow_period [10-20] |
| `MovingAverageCrossoverStrategy` | Пересечение SMA | fast_period [10-80], slow_period [50-250] |
| `GridTradingStrategy` | Сеточная торговля (ATR) | narrow_grid [0.5-4], wide_grid [0.5-6], period [50-300] |
| `MeanReversionChannelStrategy` | Возврат к среднему (SMA ± sigma) | period [50-500], sigma_mult [0.5-4.0], threshold [0.001-0.1] |

### Арбитражные стратегии (2 реализации)

| Стратегия | Описание | PARAM_CONSTRAINTS |
|-----------|----------|-------------------|
| `SpreadReversionArbitrageStrategy` | Закрытие при возврате спреда к паритету | open_threshold [0.0-0.1], close_threshold [0.0-0.05] |
| `CrossSpreadArbitrageStrategy` | Закрытие при пересечении спредом паритета | open_threshold [0.0-0.1], close_threshold [0.0-0.1] |

## Риск-менеджеры

### Система миксинов (обычные трейдеры)

**Stop Loss:**
- `StopLossPercentMixin` — SL = цена ± (цена × percent / 100)
- `StopLossExtremumMixin` — SL = мин/макс последних N свечей

**Take Profit:**
- `TakeProfitPercentMixin` — TP = цена ± (цена × percent / 100)
- `TakeProfitRiskRewardMixin` — TP = цена ± (расстояние_риска × reward_risk)

**Position Size:**
- `PositionSizeAllInMixin` — balance / price
- `PositionSizeByRiskMixin` — (balance × risk_pct / stop_distance) / price
- `PositionSizeLimitMixin` — ограничение: min(amount, balance / price)

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

### Арбитражные риск-менеджеры (2 штуки)

- `PSAllInArbitrageRiskManager` — balance / price
- `PSPercentArbitrageRiskManager` — (balance × percent / 100) / price

## Оптимизация параметров

### Алгоритмы

| Алгоритм | Библиотека | Параметры |
|----------|------------|-----------|
| `OptunaOptimizationAlgorithm` | Optuna | n_trials (default: 500) |
| `GenerationOptimizationAlgorithm` | DEAP | generations (50), population_size (100) |

### Мульти-метричное скоринг

`TraderOptimizer` оценивает результат по взвешенной сумме нормализованных метрик (sigmoid):
- ROI (roi_weight, default 0.40)
- R² кривой PnL (r2_weight, default 0.30)
- Sharpe Ratio (sharpe_weight, default 0.20)
- Win Rate (win_rate_weight, default 0.10)

### Период оптимизации (lookback_period)

`OptimizationPeriod` / `ArbitrageOptimizationPeriod` — `TextChoices` с методом `.timedelta()`:

| Значение | Label | timedelta |
|----------|-------|-----------|
| `1w` | 1 неделя | 7 дней |
| `2w` | 2 недели | 14 дней |
| `1M` | 1 месяц | 30 дней |
| `3M` | 3 месяца | 90 дней |
| `6M` | 6 месяцев | 180 дней |
| `1y` | 1 год (default) | 365 дней |
| `2y` | 2 года | 730 дней |
| `3y` | 3 года | 1095 дней |

### Процесс оптимизации

1. `TraderOptimizer.optimize()` → ставит статус REBOOTING
2. `DomainTraderOptimizer.optimize()` → вызывает алгоритм с `get_score()` как score_function
3. `get_score(params)` → создаёт трейдера с параметрами → `reboot(candle_iterator)` → считает метрики
4. Лучшие параметры → финальный reboot → `TraderOptimizationResult`
5. Параметры разделяются по префиксам: `strategy_*` и `risk_manager_*`

## Celery

### Очереди и воркеры

| Воркер | Очередь | Назначение |
|--------|---------|------------|
| worker_candle_sources_fetch | `candle_sources_fetch` | Загрузка свечей (REST + sync из Redis) |
| worker_traders_process | `traders_process` | Обработка трейдеров |
| worker_traders_reboot | `traders_reboot` | Бэктестинг (reboot) |
| worker_optimizers_optimize | `optimizers_optimize` | Оптимизация параметров |
| worker | default | Общие задачи (уведомления, балансы) |

### Beat-расписание

| Задача | Расписание |
|--------|-----------|
| `sources_fetch_last_candles` | Каждую минуту |
| `exchange_clients_sync_open_orders` | Каждую минуту |
| `exchange_clients_fetch_balances` | Ежедневно в 00:00 |
| `traders_daily_report` | Ежедневно в 10:00 |
| `arbitrage_traders_daily_report` | Ежедневно в 10:00 |

### Экспортируемые задачи

**traders/tasks/:** `dispatch_traders_for_sources`, `traders_process_for_exchange_client`, `trader_reboot`, `traders_daily_report`, `optimizer_optimize`

**arbitrage_traders/tasks/:** `dispatch_arbitrage_traders_for_sources`, `arbitrage_traders_process_for_exchange_clients`, `arbitrage_trader_reboot`, `arbitrage_traders_daily_report`, `arbitrage_optimizer_optimize`

## WebSocket-стриминг свечей

### Архитектура

```
run_ws_streams (management command, sync entrypoint)
  → WebSocketStreamManager (async, управляет жизненным циклом)
    → _load_subscriptions() — загрузка активных WS-источников из БД (каждые 30с)
    → _reconcile() — добавление/удаление стримов без перезапуска
    → OHLCVStream (по одному на подписку)
      → ccxt.pro.watch_ohlcv() (бесконечный цикл)
        → CandleRedisCache.set_candle() (сохранение в Redis)
```

### Redis-кэш свечей

**CandleRedisCache:**
- БД: `REDIS_CANDLE_CACHE_DATABASE` (default: 2)
- Формат ключа: `ws:candle:{exchange}:{symbol}:{timeframe}`
- Хранит последние 2 свечи (предыдущая + формирующаяся) как JSON-dict
- TTL = длительность таймфрейма

**ArbitrageCandleCache:**
- Буфер: `arb:buf:{trader_id}:{side}` — ожидание пары
- Парная свеча: `arb:paired:{trader_id}` — готовая ArbitrageCandle
- `set_candle()` → возвращает True если пара собрана

### Redis Pub/Sub

| Канал | Публикует | Подписчик |
|-------|-----------|-----------|
| `candle:*` | CandleSource sync | TraderWorker |
| `arb_candle:*` | ArbitrageCandleProvider | ArbitrageTraderWorker |

### Redis БД

| БД | Назначение |
|----|-----------|
| 0 | Celery broker |
| 1 | Django cache (timeout 300s, prefix "trader") |
| 2 | WebSocket candle cache |
| 3 | Bus (Pub/Sub events) |

## Перечисления (Enums)

### ORM-уровень (Django TextChoices/IntegerChoices)

**traders/schemas.py:** `SignalType`, `PositionType`, `PositionStatus`, `PositionCloseReason`, `TraderStatus`, `OptimizerStatus`, `OptimizationPeriod`, `CandlesLookbackCount`

**arbitrage_traders/schemas.py:** `ArbitrageSignalType`, `ArbitragePositionType`, `ArbitragePositionStatus`, `ArbitragePositionCloseReason`, `ArbitrageTraderStatus`, `ArbitrageOptimizerStatus`, `ArbitrageOptimizationPeriod`, `ArbitrageCandlesLookbackCount`

**exchanges/schemas.py:** `MarketType` (FUTURES/SPOT), `Timeframe` (1m, 5m, 15m, 1h, 4h, 1d, 1w — с `.timedelta()`)

**candle_sources/schemas.py:** `CandleSourceMode` (REST/WEBSOCKET)

### Доменный уровень (StrEnum)

Дублируют ORM-версии в `domain/schemas.py` каждого приложения. Используются в Pydantic-моделях.

## Утилиты (core/utils/)

| Модуль | Назначение |
|--------|-----------|
| `registry.py` | Базовый класс Registry с авто-регистрацией через `__init_subclass__` |
| `mixins.py` | `ActiveManagerMixin` (is_active + active_objects), `TimeStampedMixin` (created_at, updated_at), `BaseErrorMixin` (message, type, traceback) |
| `cache.py` | `@cached_method(timeout)` — Redis-кэширование методов с TTL, `invalidate_cached_methods()` |
| `common.py` | `get_all_init_args(cls)` — параметры конструктора, `dt_str(dt)` — DD.MM.YYYY HH:MM:SS |
| `async_utils.py` | `run_with_exchange_client(client, tasks)` — выполнение корутин в контексте клиента |

## Django Admin

### Общие паттерны

- `AutocompleteFilter` (из `admin_auto_filters`) — автодополнение в фильтрах для FK-полей
- `autocomplete_fields` — автодополнение в формах редактирования FK/M2M полей
- `RangeFilter` — фильтрация по диапазону дат
- Кастомные actions через `group().apply_async()` (Celery) для bulk-операций
- Inline-модели для ошибок, ордеров, результатов оптимизации

### Admin-классы с search_fields (необходимы для autocomplete)

| Admin | search_fields |
|-------|--------------|
| `ExchangeAdmin` | name |
| `TradingPairAdmin` | name, symbol |
| `ExchangeClientAdmin` | name |
| `CandleSourceAdmin` | exchange_client__name, trading_pair__name |
| `StrategyAdmin` | name, class_name |
| `RiskManagerAdmin` | name, class_name |
| `TelegramBotAdmin` | name |

## Docker

### Сервисы

**Dev (docker-compose.yml) — 11 сервисов:**
postgres (14.18-alpine), redis (6.2-alpine), backend (gunicorn + debugpy:5678), beat, worker_candle_sources_fetch, worker_traders_process, worker_traders_reboot, worker_optimizers_optimize, worker, ws_streams, flower (порт 5555).

**Staging (docker-compose.staging.yml):**
Те же сервисы + nginx (SSL/Certbot). Образы: `kletkinvasilii/trader:staging`. PostgreSQL на порту 15432. Health checks.

**Production (docker-compose.production.yml):**
Без PostgreSQL (внешняя БД). Образы: `kletkinvasilii/trader:latest`. nginx (SSL/Certbot).

### Dockerfile

- Base: python:3.12-slim
- Poetry 2.1.2, user: appuser (UID 5678)
- Порт: 8000 (gunicorn)
- Системные зависимости: build-essential, libpq-dev

## CI/CD

### GitHub Actions

| Workflow | Файл | Триггер | Назначение |
|----------|------|---------|-----------|
| CI (PR checks) | `ci-pull-request.yml` | PR → staging/main | Вызывает checks.yml |
| Checks (reusable) | `checks.yml` | Вызывается из CI/CD | ruff, mypy, bandit, pytest (min 50% coverage) |
| Build (reusable) | `build.yml` | Вызывается из CD | Docker build + push to Docker Hub |
| Deploy (reusable) | `deploy.yml` | Вызывается из CD | SSH deploy с graceful shutdown |
| CD Staging | `cd-staging.yml` | Push → staging | checks → build (tag: staging) → deploy |
| CD Production | `cd-production.yml` | Push → main | checks → build (tag: latest) → deploy |

### Git Flow

```
feature-branch → staging → main
```

## Тестирование

### Конфигурация

Тесты используют SQLite (не Postgres) и eager Celery (задачи выполняются синхронно). Настроено в `pyproject.toml` под `[tool.pytest.ini_options]`.

Coverage: omit `domain/**/base.py` (async-код, тестируется интеграционно). Минимальный порог: 50%.

### Иерархия фикстур

**Глобальные (`backend/conftest.py`):**
- `_mock_send_notification` (autouse) — мокает Telegram-уведомления
- `trading_pair` — BTC/USDT:USDT, FUTURES, fee 0.1%
- `timeframe` — ONE_HOUR
- `exchange_candle` — OHLCV доменный объект (open=100, high=110, low=90, close=105, volume=1000)

**Приложение traders (`traders/tests/conftest.py`):**
ORM-фикстуры: exchange, trading_pair, exchange_client, candle_source, strategy, risk_manager, trader
Доменные фикстуры: domain_trading_pair, domain_candle, domain_signal, domain_position

**Домен traders (`traders/domain/conftest.py`):**
Чистые Python-фикстуры (без БД): trading_pair, candle, trader, mock_strategy, mock_risk_manager, mock_exchange_client, sample_candles, downtrend_candles

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
- Импорты всегда выносятся на верх файла, не использовать локальные импорты внутри функций/методов

## Настройки Django (core/settings.py)

- LANGUAGE_CODE: ru-ru
- TIME_ZONE: Europe/Moscow
- USE_TZ: True
- CONN_MAX_AGE: 600, CONN_HEALTH_CHECKS: True
- Statement timeout PostgreSQL: 30000ms
- Кэш: Redis (timeout 300s, prefix "trader")
- Логирование: loguru (colorized в dev, JSON в production)
- INSTALLED_APPS: django_celery_beat, django_celery_results, django_plotly_dash, admin_auto_filters, rangefilter, channels, debug_toolbar (dev)
- ADMIN_INLINE_MAX_NUM: 10 (для ограничения inline в админке)

## URL-роутинг

| URL | Назначение |
|-----|-----------|
| `/admin/` | Django Admin |
| `/django_plotly_dash/` | Plotly-дашборды (equity curves, графики) |
| `/traders/` | Эндпоинты трейдеров |
| `/arbitrage_traders/` | Эндпоинты арбитражных трейдеров |
| `/candle_sources/` | Эндпоинты источников свечей |
| `/exchanges/` | Эндпоинты бирж |
| `/health/` | Health check |
| `/health/live/` | Liveness check |
| `/` | Редирект на /admin/ |

## Переменные окружения (.env)

| Переменная | Назначение |
|------------|-----------|
| `SECRET_KEY` | Django secret key |
| `DEBUG` | Режим отладки |
| `DJANGO_ALLOWED_HOSTS` | Разрешённые хосты |
| `POSTGRES_ENGINE/DATABASE/USER/PASSWORD/HOST/PORT` | PostgreSQL |
| `REDIS_HOST/PORT/USER/PASSWORD/DATABASE` | Redis |
| `REDIS_CANDLE_CACHE_DATABASE` | Redis БД для WS-кэша свечей (default: 2) |
| `REDIS_BUS_DATABASE` | Redis БД для Pub/Sub (default: 3) |
| `CELERY_BROKER` | URL брокера Celery |
| `CELERY_RESULT_BACKEND` | Бэкенд результатов (django-db) |
| `CELERY_TASK_ALWAYS_EAGER` | Синхронное выполнение (True для тестов) |
| `LOG_LEVEL` | Уровень логирования |
