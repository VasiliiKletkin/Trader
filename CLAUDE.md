# CLAUDE.md

Руководство для Claude Code (claude.ai/code) по работе с кодовой базой проекта.

## Обзор проекта

Система криптовалютной торговли на Django + Celery. Поддерживает обычную и арбитражную торговлю на 18 биржах через ccxt/ccxt.pro. Два режима работы: **Celery-задачи** (REST-опрос бирж по расписанию) и **in-memory воркеры** (WebSocket-стриминг + RPC/Bus через Redis). Архитектура — Domain-Driven Design: ORM-модели отвечают за персистентность, доменные классы — за бизнес-логику (в том числе асинхронную).

**Язык:** русский используется в `verbose_name` админки, комментариях, docstring-ах и сообщениях коммитов. В логах и пользовательских сообщениях тоже допустим.

**Стек:**
- Python 3.12, Django 5.2.6+, Celery 5.5+, Redis 6.2+, PostgreSQL 14+
- ccxt 4.5+ (биржевое API, REST + ccxt.pro WebSocket), pandas-ta 0.4.67b0 (технический анализ), Pydantic 2.11+ (валидация), websockets 16+
- aiogram 3.22+ (Telegram-бот), Optuna 4.6+ + DEAP 1.4+ (оптимизация параметров)
- loguru 0.7+ (логирование), gunicorn 23+ (WSGI), Flower 2.0+ (мониторинг Celery)
- django-cacheops 7.2+ (кэширование ORM-счётчиков), django-plotly-dash 2.5+ (графики), channels (ASGI)
- admin_auto_filters (AutocompleteFilter), django-rangefilter (фильтр диапазонов)

## Команды

Все команды выполняются из директории `backend/`. Зависимости управляются через Poetry 2.1+.

```bash
# Установка зависимостей
cd backend && poetry install

# Запуск тестов (SQLite + eager Celery + CACHEOPS_ENABLED=False,
# настроено в pyproject.toml)
cd backend && poetry run pytest
cd backend && poetry run pytest traders/tests/test_traders.py    # один файл
cd backend && poetry run pytest -k "test_handle_candle"          # один тест
cd backend && poetry run pytest --cov --cov-report=term-missing  # с coverage

# Линтинг и форматирование (ruff заменяет flake8/isort/black)
cd backend && poetry run ruff check .
cd backend && poetry run ruff check --fix .
cd backend && poetry run ruff format .

# Проверка типов (django-stubs + pydantic plugins)
cd backend && poetry run mypy .

# Сканирование безопасности (skip B101/B107/B110/B311)
cd backend && poetry run bandit -r . -c pyproject.toml

# Django
cd backend && python manage.py makemigrations
cd backend && python manage.py migrate
cd backend && python manage.py shell

# Docker
docker-compose up                    # все 13 сервисов (dev)
docker-compose up --build            # пересборка образа backend
docker-compose exec backend python manage.py shell
```

### Makefile (из корня проекта)

Makefile подключает `.env` через `include .env`, поэтому все переменные окружения доступны автоматически.

**Django:**
| Цель | Описание |
|------|----------|
| `dstrt` | `dmigr` + `dcollect` |
| `dcollect` | `collectstatic` |
| `dmigr` | `makemigrations` + `migrate` |
| `duser` | `createsuperuser` |
| `dshell` | Django shell внутри backend-контейнера |

**PostgreSQL:**
| Цель | Описание |
|------|----------|
| `dcreatedb` / `ddeletedb` | Создать / удалить базу |
| `dcreatedump` / `dloaddump` | Создать / восстановить pg_dump (Fc) |

**Мониторинг БД (pg_stat_activity):**
| Цель | Описание |
|------|----------|
| `dbconns` | Соединения по `application_name` (docker) |
| `dbconns-local` | Соединения по `application_name` (локальный psql) |
| `dbconns-detail` | PID, старт, idle-продолжительность |
| `dbconns-queries` | Idle-соединения с текстом последнего запроса |
| `dbconns-app APP=<name>` | Детали конкретного приложения |
| `dbbeat` | Состояние beat-задач из `django_celery_beat_periodictask` |

**Мониторинг трейдеров:**
| Цель | Описание |
|------|----------|
| `traders` / `arb-traders` | Список трейдеров / арбитражных трейдеров |
| `positions` / `arb-positions` | Открытые позиции |
| `errors` / `arb-errors` | Последние 20 ошибок |
| `sources` | Источники свечей с режимом/таймфреймом |

**Celery:**
| Цель | Описание |
|------|----------|
| `celery-inspect` | `inspect active` + `inspect reserved` |
| `celery-purge` | Удалить ключ `celery` из Redis |
| `celery-purge-all` | Удалить все очереди (celery, trader, optimizer, candle_source, exchange_client) |
| `celery-queues` | `LLEN` по каждой очереди |

**Прочее:**
| Цель | Описание |
|------|----------|
| `hooks` | `cd backend && pre-commit run --all-files` |

### Pre-commit хуки (`backend/.pre-commit-config.yaml`)

Стандартные: trailing-whitespace, end-of-file-fixer, check-yaml/toml/json, check-added-large-files (max 1000KB), check-merge-conflict, check-case-conflict, debug-statements, detect-private-key.

Основные: **ruff** 0.15.0 (lint + `--fix` + format), **django-upgrade** 1.29.1 (target 5.1), **bandit** 1.9.3.

Локальные (через `poetry run`, т.к. `backend/` не в PYTHONPATH изолированного окружения): **mypy**, **poetry-check**, **poetry-lock-check**.

## Архитектура

### Структура репозитория

```
Trader/
├── .github/workflows/              # CI/CD: ci-pull-request, checks, build, deploy, cd-staging, cd-production
├── docker-compose.yml              # Dev: 13 сервисов (build from ./backend)
├── docker-compose.preprod.yml      # Monolith preprod (image :staging)
├── docker-compose.production.yml   # Monolith production (image :latest)
├── deploy/
│   ├── preprod/
│   │   ├── main/docker-compose.yml     # Backend + beat + infra
│   │   └── workers/docker-compose.yml  # Воркеры отдельно (split-deploy)
│   └── production/
│       ├── main/docker-compose.yml
│       └── workers/docker-compose.yml
├── Makefile                        # Docker + мониторинг + Celery-команды
├── nginx/                          # Nginx + Certbot (preprod/prod)
├── postgres/data/                  # Том PostgreSQL
├── redis/data/                     # Том Redis
└── backend/
    ├── pyproject.toml              # Зависимости, конфиг ruff/mypy/pytest/bandit
    ├── .pre-commit-config.yaml     # Хуки (живут в backend/, не в корне)
    ├── Dockerfile                  # Python 3.12-slim, Poetry 2.1.2, user appuser
    ├── entrypoint.sh               # Docker entrypoint
    ├── conftest.py                 # Глобальные pytest-фикстуры
    ├── manage.py
    ├── core/                       # Настройки Django, Celery, шина событий, RPC
    ├── exchanges/                  # Биржи, торговые пары, свечи
    ├── exchange_clients/           # API-клиенты (18 бирж), балансы, ордера, RPC, WS-стримы
    ├── candle_sources/             # Источники свечей (REST + WebSocket)
    ├── traders/                    # Основной торговый движок
    ├── arbitrage_traders/          # Арбитражная торговля
    └── telegram_bots/              # Telegram-уведомления
```

### Структура Django-приложения

```
app/
├── models/                # ORM-модели (package) или models.py
│   ├── traders.py         # Персистентность, DB-запросы, instantiate()/sync()
│   ├── strategies.py      # Стратегии (Registry-паттерн)
│   ├── risk_managers.py   # Риск-менеджеры (Registry-паттерн)
│   └── optimizations.py   # Оптимизаторы, результаты, алгоритмы
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
│   ├── optimizations/
│   │   ├── base.py        # AbstractOptimizationAlgorithm
│   │   ├── algorithms.py  # Optuna, DEAP
│   │   └── optimizations.py # DomainTraderOptimizer
│   ├── exchange_clients/  # (в exchange_clients/) имплементации бирж
│   ├── rpc/               # (в exchange_clients/) RPC: client/server/handlers/messages
│   ├── ws/                # (в candle_sources/) Redis-кэш WebSocket-свечей
│   ├── exchanges/         # (в exchanges/) имплементации бирж
│   └── schemas.py         # Pydantic-модели, StrEnum-перечисления
├── tasks/                 # Celery-задачи (package) или tasks.py
│   ├── traders.py
│   └── optimizations.py
├── admin/                 # Django Admin (package) или admin.py
│   ├── traders.py
│   ├── strategies.py
│   ├── risk_managers.py
│   └── optimizations.py
├── charts/                # Plotly-графики (equity curve, сигналы, индикаторы)
├── management/commands/   # Management-команды (только в exchange_clients/)
├── urls.py                # Роутинг приложения
└── tests/
    ├── conftest.py        # Фикстуры приложения
    ├── models/            # Тесты ORM-моделей
    ├── domain/            # Тесты доменной логики
    ├── tasks/             # Тесты Celery-задач
    └── admin/             # Тесты admin-actions (только traders/)
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

Стратегии, риск-менеджеры, клиенты бирж, алгоритмы оптимизации, трейдеры, источники свечей регистрируются через `core.utils.registry.Registry`.

```python
class Registry:
    _registry: dict[str, type]   # заполняется через __init_subclass__

    @classmethod
    def get_choices(cls) -> list[tuple[str, str]]  # для Django choices

    @classmethod
    def get_class(cls, name: str) -> type          # разрешение в runtime
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

Каждый доменный класс декларирует `PARAM_CONSTRAINTS: dict[str, tuple[min, max]]` — диапазоны допустимых значений параметров. Оптимизатор читает ограничения и генерирует комбинации параметров. Конструктор класса (`get_all_init_args`) задаёт полный набор параметров — оптимизатор разделяет их на `strategy_*` и `risk_manager_*` по префиксу.

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

`ArbitrageCandle` в Pydantic-валидаторе проверяет совпадение таймстампов left/right — при расхождении бросает `CandleDesyncError` (`arbitrage_traders/domain/exceptions.py`).

## Два режима работы

### 1. Celery-задачи (REST)

Beat каждую минуту → fetch свечей с бирж → fanout по exchange_client → handle_candle.

```
Beat (каждую минуту)
  → candle_sources_fetch_last_candles
    ├── REST-источники: fanout по exchange_client
    │     → fetch + upsert свечей → dispatch_traders_for_sources()
    └── WS-источники: candle_sources_sync_from_redis(source_ids)
          → читает Redis-кэш → bulk insert в БД
            → dispatch_traders_for_sources()
```

### 2. In-memory воркеры (WebSocket + RPC/Bus)

Долгоживущие процессы (management commands), работают через Redis Streams как шину событий и RPC-канал к exchange-клиентам.

| Команда | Управляется через | Назначение |
|---------|-------------------|------------|
| `run_candle_source_ws_worker` | docker-сервис `candle_source_ws_worker` | WebSocket-подписки на OHLCV, запись в `CandleRedisCache`, публикация в Bus |
| `run_trader_ws_worker` | docker-сервис `trader_ws_worker` | Держит трейдеров в памяти, подписан на Bus (свечи), вызывает `handle_candle()` |
| `run_exchange_client_rpc_worker` | docker-сервис `exchange_client_rpc_worker` | RPC-сервер: исполняет заявки/получает балансы/ордера от имени клиента в одном процессе (избегает дублирования ccxt-инстансов) |

Все три команды живут в `exchange_clients/management/commands/` (в `traders/management/` и `arbitrage_traders/management/` пусто).

**Жизненный цикл in-memory воркера:**
1. Загрузка активных трейдеров/источников из БД → `instantiate()` + `load()`
2. Подписка на Bus (Redis Streams, `REDIS_BUS_DATABASE`, по умолчанию БД 3)
3. При получении свечи → `handle_candle()` на доменном трейдере
4. Периодический `_reconcile_loop()`: перезагрузка из БД (добавление новых, удаление неактивных)
5. Периодический `_sync_all()` — запись состояния обратно в БД
6. Graceful shutdown по SIGTERM/SIGINT (deploy.yml даёт workers 30с на остановку)

### Bus (шина событий) и RPC

`core/bus.py` + `core/utils/rpc/` реализуют две независимые абстракции поверх Redis Streams:

- **Bus** (`AbstractBusClient`): публикация/подписка на события (свечи, сигналы). Две реализации — `BusClient` (через `RedisBusBroker`, production) и `LocalBusClient` (in-process, без Redis — для тестов и режима `USE_BUS=False`).
- **RPC** (`core/utils/rpc/`): модуль с `client.py`, `server.py`, `transport.py`, `base.py`, `broker.py`, `redis/`. Поверх него `exchange_clients/domain/rpc/` добавляет `client.py`, `server.py`, `handlers.py`, `messages.py` — конкретные RPC-операции с биржевым клиентом (create_market_order, fetch_balances и т.п.).

Пул соединений к Redis создаётся **на каждый вызов** `get_bus_client()`: синглтон неприменим, т.к. redis-соединение привязывается к event loop, а `asyncio.run()` закрывает loop.

## Django-приложения

### exchanges — Биржи и свечи

**Модели (`exchanges/models.py`):**
- `Exchange` — биржа (name, class_name, max_candles_per_request, timeout, rate_limit, candle_source_mode, market_types). Наследует `ActiveManagerMixin`, `TimeStampedMixin`.
- `TradingPair` — торговая пара (name, type: MarketType, base_currency, quote_currency, settle_currency, is_linear).
- `ExchangeTradingPair` — привязка пары к бирже (unique: exchange + trading_pair). Хранит лимиты: min/max amount, cost, price, precision, taker/maker fee, min/max leverage, contract_size, поддержка cross/isolated margin.
- `Candle` — абстрактная модель OHLCV (Decimal(30, 18)).
- `ExchangeCandle` — свеча с биржи (unique: exchange + timeframe + trading_pair + timestamp).

**Доменный слой (`exchanges/domain/exchanges/`):** 18 файлов-имплементаций (см. ниже).

**Таски:** `exchange_sync_trading_pairs(exchange_id)`, `exchanges_sync_all_trading_pairs()` (beat: ежедневно 00:00).

**Графики (`exchanges/charts/`):** `spread_chart.py` — анализ спредов между биржами.

### exchange_clients — API-клиенты

**Модели:**
- `ExchangeClientProxy` — HTTP/SOCKS5 прокси (exchange, proxy_host/port/user/password). `check_obj()` для тестирования.
- `ExchangeClient` — учётные данные API (exchange, name, api_key, api_secret, proxy, balance, status). Наследует `ActiveManagerMixin`.
- `ExchangeClientBalance` — снимок баланса (exchange_client, currency, free, used, total).
- `ExchangeClientOrder` — исполненный ордер на бирже (exchange_client, trading_pair, exchange_order_id, status, side, amount, price, cost, filled_amount, fee).

**Поддерживаемые биржи (18):**
Binance, Bitfinex, Bitget, BitMEX, Bybit, Coinbase, CoinEX, Deribit, Gate.io, HTX (Huobi), Hyperliquid, Kraken, KuCoin, MEXC, OKX, Paradex, Phemex, WOOFi Pro.

Все используют ccxt.pro (async) с поддержкой demo-режима и HTTP/SOCKS5 прокси.

**Доменный слой (`exchange_clients/domain/`):**
- `base.py` — `ExchangeClientRegistry`, `AbstractExchangeClient` (create_market_order, fetch_orders, fetch_balances).
- `exchange_clients/` — 18 имплементаций (binance.py, bitfinex.py, ...).
- `cache.py`, `managers.py`, `proxies.py`, `schemas.py`, `streams.py` (WS-стримы балансов/ордеров), `workers.py`.
- `rpc/` — RPC над Bus: `client.py`, `server.py`, `handlers.py`, `messages.py`.

**Таски:**
- `exchange_client_sync_order(order_id)` — очередь `exchange_client`
- `exchange_client_sync_open_orders()` — beat, каждую минуту, очередь `exchange_client`

### candle_sources — Источники свечей

**Модели:**
- `CandleSource` — exchange + trading_pair + timeframe + mode (unique). Наследует `TimeStampedMixin`, поля `status`, `last_synced`.
- `CandleSourceError` — ошибки при загрузке свечей (`BaseErrorMixin`).

**Режимы (`CandleSourceMode`):**
- `REST` — периодический fetch через REST (каждую минуту через Beat)
- `WEBSOCKET` — real-time стриминг через `ccxt.pro.watch_ohlcv`, кэш в Redis

**Доменный слой:**
- `base.py` — `CandleSourceRegistry`, `AbstractCandleSource`
- `candle_sources.py` — имплементации REST/WS-источников
- `ws/redis_cache.py` — `CandleRedisCache`, `ArbitrageCandleCache`

**Таски:**
- `candle_source_sync_candles(source_id, since)` — очередь `candle_source`
- `candle_source_delete_candles(source_id, before)` — очередь `candle_source`
- `candle_source_clear_all_data(source_id)` / `candle_source_clear_all_errors(source_id)` — очередь `candle_source`
- `candle_sources_fetch_last_candles()` — beat, каждую минуту
- `candle_sources_fetch_last_candles_for_exchange(exchange_id)` — fetch через публичный клиент
- `candle_sources_sync_from_redis(source_ids)` — читает Redis-кэш → bulk insert в Postgres

### traders — Торговый движок

**ORM-модели:**

`traders/models/traders.py`:
- `Trader` — ядро: `exchange_client`, `candle_source`, `strategy`, `risk_manager`, `status`, `balance`, `pnl`, `settings` (JSONField с параметрами торговли)
- `TraderError` — ошибки (`BaseErrorMixin`)
- `TraderSignal` — сгенерированный сигнал (trader, type, confidence, data JSONField). Unique: (trader, timestamp, type)
- `TraderPosition` — позиция (trader, status, type, amount, open/close price, SL/TP, pnl, close_reason). Unique: (trader, opened_at, amount, type)
- `TraderOrder` — связь позиции и биржевого ордера (position, order: FK на `ExchangeClientOrder`, side, amount, price, status)

`traders/models/strategies.py`:
- `Strategy` — name, class_name, parameters (JSONField)

`traders/models/risk_managers.py`:
- `RiskManager` — name, class_name, parameters (JSONField)

`traders/models/optimizations.py`:
- `TraderOptimizationAlgorithm` — алгоритм (Registry)
- `TraderOptimizer` — конфигурация оптимизации (trader, algorithm, status, config JSONField, start/end_time)
- `TraderOptimizationResult` — результат: pnl, win_rate, roi, sharpe, r2, strategy/risk_manager arguments, duration
- `TraderOptimizerError` — ошибки оптимизатора

**Настройки трейдера (поля в `settings` / в самой модели):**
- `use_fixed_balance` / `initial_balance` — фиксированный баланс vs реальный
- `check_drawdown` / `max_drawdown_pct` — контроль просадки
- `create_new_orders` — создавать реальные ордера на бирже
- `max_positions_count` — лимит одновременных позиций
- `candles_lookback_count` — количество свечей в памяти (choices: 50-10000)
- `close_position_by_opposite_signal` — закрытие по обратному сигналу
- `close_position_by_strategy` — закрытие по логике стратегии
- `close_position_by_stop_loss` / `close_position_by_take_profit` — SL/TP
- `trail_stop_enabled` — трейлинг стоп

**Ключевые ORM-методы Trader:**
- `instantiate(domain_exchange_client)` → `DomainTrader`
- `load(trader)` — загрузка свечей (с `.instantiate()`) и позиций
- `sync(trader)` → `sync_signals()` + `sync_positions()` + `sync_errors()`
- `reboot()` — бэктестинг за период (по умолчанию 365 дней)
- `get_candle_iterator(start, end)` — итератор доменных свечей
- Статистика: `get_win_rate()`, `get_fact_pnl()`, `get_theoretical_pnl()`, `get_pnl_r2()`, `get_balance()`
- SQL-аннотации: `theoretical_pnl_annotation()`, `fact_pnl_annotation()`

**Таски (`traders/tasks/`):**
- `traders.py`: `dispatch_traders_for_sources(source_ids)`, `traders_process(traders_ids)`, `trader_process(trader_id)`, `trader_reboot(trader_id)` (очередь `trader`), `trader_clear_all_data/errors(trader_id)`, `traders_daily_report()` (beat, 10:00)
- `optimizations.py`: `optimizer_optimize(optimizer_id)` (очередь `optimizer`)

**Графики (`traders/charts/`):**
- Стратегии: `RenkoChart`, `MoneyFlowIndexChart`, `StochasticChart`, `DonchianCrossoverChart`, `MovingAverageCrossoverChart`, `GridTradingChart`
- Трейдеры (`traders/trader_chart.py`): `EquityCurveChart`, `PositionSignalChart`, `AccuracyChart`

### arbitrage_traders — Арбитраж

**Ключевые отличия от traders:**
- `ArbitrageTrader` — два `exchange_client` (left/right) и два `candle_source` (left/right)
- `clean()` валидирует: клиенты на разных биржах, биржи candle_source совпадают с клиентами, таймфреймы совпадают
- Нет SL/TP и trail_stop — только закрытие по сигналу/стратегии
- `ArbitrageTraderPosition` — `left_type` + `right_type`, left/right open/close prices, left/right fees
- `ArbitrageTraderOrder` — `left_order` + `right_order` (оба FK на `ExchangeClientOrder`)
- Исключение `CandleDesyncError` (domain/exceptions.py) при рассинхроне таймстампов левой/правой свечи

**Таски (`arbitrage_traders/tasks/`):**
- `traders.py`: `dispatch_arbitrage_traders_for_sources`, `arbitrage_traders_process`, `arbitrage_trader_process`, `arbitrage_trader_reboot` (очередь `trader`), `arbitrage_trader_clear_all_data/errors`, `arbitrage_traders_daily_report()` (beat, 10:00)
- `optimizations.py`: `arbitrage_optimizer_optimize(optimizer_id)` (очередь `optimizer`)

**Графики (`arbitrage_traders/charts/`):** `candle_chart.py` — визуализация арбитражных свечей и спреда.

### telegram_bots — Уведомления

- `TelegramBot` — конфигурация бота (name, token). `ActiveManagerMixin`.
- `TelegramChat` — подписка чата (bot, chat_id, name). `ActiveManagerMixin`.
- `send_notification(message)` — отправка через aiogram (Celery task).

## Pydantic-схемы (доменный слой)

### traders/domain/schemas.py

| Схема | Ключевые поля | Вычисляемые свойства |
|-------|---------------|---------------------|
| `TraderSignal` | timestamp, price, candle: ExchangeCandle, type: SignalType, data | — |
| `TraderPosition` | type, status, amount, open/close_price, SL/TP, total_fee, orders | pnl, pnl_pct, rr, is_closed, open_cost, close_cost |
| `TraderError` | timestamp, message, type, traceback | — |
| `TraderOptimizationResult` | pnl, win_rate, roi, sharpe, pnl_r2, total_positions, strategy/risk_manager_arguments, duration | — |

**Данные стратегий (в `TraderSignal.data`):** `RenkoData`, `StochasticData`, `DonchianCrossoverData`, `MovingAverageCrossoverData`, `GridTradingData`, `MeanReversionChannelData`.

### arbitrage_traders/domain/schemas.py

| Схема | Ключевые поля | Вычисляемые свойства |
|-------|---------------|---------------------|
| `ArbitrageCandle` | left: ExchangeCandle, right: ExchangeCandle | spread (left/right close ratio), timestamp |
| `ArbitrageTraderSignal` | left/right_type, left/right_price, left/right_candle, data | — |
| `ArbitrageTraderPosition` | left/right_type, amount, left/right_open/close_price, left/right_total_fee, left/right_orders | pnl (left_pnl + right_pnl), total_fee, is_closed |

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
| `OptunaOptimizationAlgorithm` | Optuna 4.6 | n_trials (default: 500) |
| `GenerationOptimizationAlgorithm` | DEAP 1.4 | generations (50), population_size (100) |

### Мульти-метричный скоринг

`TraderOptimizer` оценивает результат по взвешенной сумме нормализованных метрик (sigmoid):
- ROI (`roi_weight`, default 0.40)
- R² кривой PnL (`r2_weight`, default 0.30)
- Sharpe Ratio (`sharpe_weight`, default 0.20)
- Win Rate (`win_rate_weight`, default 0.10)

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

| Воркер (docker-сервис) | Очередь | Автоскейлинг (preprod/prod) | Назначение |
|------------------------|---------|------------------------------|------------|
| `trader_worker` | `trader` | 1,1 | Обработка трейдеров + бэктестинг (`trader_reboot`) |
| `optimizer_worker` | `optimizer` | 1,1 | Оптимизация параметров (Optuna, DEAP) |
| `candle_source_worker` | `candle_source` | 1,1 | Загрузка свечей (REST + sync из Redis) |
| `exchange_client_worker` | `exchange_client` | 1,1 | Синк открытых ордеров |
| `celery_worker` | default (`celery`) | 5,1 | Прочее: отчёты, уведомления, балансы, `dispatch_*` |

### Beat-расписание (`core/celery.py`)

| Задача | Расписание |
|--------|-----------|
| `exchanges_sync_all_trading_pairs` | Ежедневно 00:00 |
| `candle_sources_fetch_last_candles` | Каждую минуту |
| `exchange_client_sync_open_orders` | Каждую минуту |
| `traders_daily_report` | Ежедневно 10:00 |
| `arbitrage_traders_daily_report` | Ежедневно 10:00 |

### Экспортируемые задачи

**`exchanges/tasks.py`**: `exchange_sync_trading_pairs`, `exchanges_sync_all_trading_pairs`.

**`candle_sources/tasks.py`**: `candle_source_sync_candles`, `candle_source_delete_candles`, `candle_source_clear_all_data`, `candle_source_clear_all_errors`, `candle_sources_fetch_last_candles`, `candle_sources_fetch_last_candles_for_exchange`, `candle_sources_sync_from_redis`.

**`exchange_clients/tasks.py`**: `exchange_client_sync_order`, `exchange_client_sync_open_orders`.

**`traders/tasks/`**: `dispatch_traders_for_sources`, `traders_process`, `trader_process`, `trader_reboot`, `trader_clear_all_data`, `trader_clear_all_errors`, `traders_daily_report`, `optimizer_optimize`.

**`arbitrage_traders/tasks/`**: `dispatch_arbitrage_traders_for_sources`, `arbitrage_traders_process`, `arbitrage_trader_process`, `arbitrage_trader_reboot`, `arbitrage_trader_clear_all_data`, `arbitrage_trader_clear_all_errors`, `arbitrage_traders_daily_report`, `arbitrage_optimizer_optimize`.

## WebSocket-стриминг свечей

### Архитектура

```
run_candle_source_ws_worker (management command, sync entrypoint)
  → WebSocketStreamManager (async, управляет жизненным циклом)
    → _load_subscriptions() — загрузка активных WS-источников из БД (каждые 30с)
    → _reconcile() — добавление/удаление стримов без перезапуска
    → OHLCVStream (по одному на подписку)
      → ccxt.pro.watch_ohlcv() (бесконечный цикл)
        → CandleRedisCache.set_candle() (сохранение в Redis)
          → Bus publish → trader_ws_worker
```

### Redis-кэш свечей (`candle_sources/domain/ws/redis_cache.py`)

**`CandleRedisCache`:**
- БД: `REDIS_EXCHANGE_CACHE_DATABASE` (default: 2)
- Формат ключа: `ws:candle:{exchange}:{symbol}:{timeframe}`
- Хранит последние 2 свечи (предыдущая + формирующаяся) как JSON-dict
- TTL = длительность таймфрейма

**`ArbitrageCandleCache`:**
- Буфер: `arb:buf:{trader_id}:{side}` — ожидание пары
- Парная свеча: `arb:paired:{trader_id}` — готовая ArbitrageCandle
- `set_candle()` → возвращает True если пара собрана (т.е. пришли обе стороны с совпадающими таймстампами)

### Шина событий (Redis Streams)

| Канал/стрим | Публикует | Подписчик |
|-------------|-----------|-----------|
| candle.* | `candle_source_ws_worker` | `trader_ws_worker` |
| arb_candle.* | ArbitrageCandleProvider | trader_ws_worker (арбитражные) |
| rpc:exchange_client:* | `trader_ws_worker` (клиенты) | `exchange_client_rpc_worker` |

Переключение между Redis Streams и in-memory режимом через `USE_BUS` (см. `core/bus.py`).

### Redis БД (5 разных DB)

| БД | Переменная | Назначение |
|----|-----------|-----------|
| 0 | `REDIS_BROKER_DATABASE` | Celery broker |
| 1 | `REDIS_CACHE_DATABASE` | Django cache (timeout 300s, prefix "trader") |
| 2 | `REDIS_EXCHANGE_CACHE_DATABASE` | WebSocket candle cache |
| 3 | `REDIS_BUS_DATABASE` | Bus (Redis Streams / Pub-Sub) и RPC |
| 4 | `REDIS_CACHEOPS_DATABASE` | django-cacheops (кэш ORM-count-запросов) |

## Перечисления (Enums)

### ORM-уровень (Django TextChoices/IntegerChoices)

**`traders/schemas.py`:** `SignalType`, `PositionType`, `PositionStatus`, `PositionCloseReason`, `TraderStatus`, `OptimizerStatus`, `OptimizationPeriod`, `CandlesLookbackCount`.

**`arbitrage_traders/schemas.py`:** `ArbitrageSignalType`, `ArbitragePositionType`, `ArbitragePositionStatus`, `ArbitragePositionCloseReason`, `ArbitrageTraderStatus`, `ArbitrageOptimizerStatus`, `ArbitrageOptimizationPeriod`, `ArbitrageCandlesLookbackCount`.

**`exchanges/schemas.py`:** `MarketType` (FUTURES/SPOT), `Timeframe` (1m, 5m, 15m, 1h, 4h, 1d, 1w — с `.timedelta()`).

**`candle_sources/schemas.py`:** `CandleSourceMode` (REST/WEBSOCKET).

### Доменный уровень (StrEnum)

Дублируют ORM-версии в `domain/schemas.py` каждого приложения. Используются в Pydantic-моделях.

## Утилиты (`core/utils/`)

| Модуль | Назначение |
|--------|-----------|
| `registry.py` | Базовый класс `Registry` с авто-регистрацией через `__init_subclass__` |
| `models.py` | Миксины: `ActiveManagerMixin` (is_active + active_objects), `TimeStampedMixin` (created_at, updated_at), `BaseErrorMixin` (message, type, traceback) |
| `admin.py` | `ReadOnlyAdminMixin` и общие admin-утилиты |
| `charts.py` | Общие helper-функции для Plotly-графиков |
| `common.py` | `get_all_init_args(cls)` (параметры конструктора), `dt_str(dt)` (DD.MM.YYYY HH:MM:SS), `format_fee`, `format_pnl` |
| `worker.py` | Утилиты для долгоживущих воркеров (graceful shutdown, reconcile-loop) |
| `async_orm.py` | `aiter_sync_chunked(iterable_factory, transform, chunk_size=1000)` — чанкованная async-итерация над sync-iterable (типично lazy QuerySet) через `sync_to_async`. Используется в `Trader.reboot` / `ArbitrageTrader.reboot` / оптимизаторах, чтобы не материализовать весь датасет в память и не нуждаться в `DJANGO_ALLOW_ASYNC_UNSAFE`. Также `aiter_from_iterable` — простая async-обёртка для уже готовых коллекций (тесты). |
| `rpc/` | Пакет с RPC-инфраструктурой: `base.py` (AbstractBusClient, BusClient, LocalBusClient), `broker.py`, `client.py`, `server.py`, `transport.py`, `redis/broker.py` (`RedisBusBroker`) |

### Кэширование

- `django-cacheops` — автоматическое кэширование **только count-запросов** для display-методов в админке. Включается флагом `CACHEOPS_ENABLED` (в тестах `False`). Модели в `CACHEOPS` dict: `CandleSource`, `CandleSourceError`, `ExchangeCandle` (TTL 30c), `Trader`, `ArbitrageTrader`.
- Django cache (Redis DB 1, prefix `"trader"`, default timeout 300с) — для ручного `cache.get/set` в коде.

## Django Admin

### Общие паттерны

- `AutocompleteFilter` (из `admin_auto_filters`) — автодополнение в фильтрах для FK-полей
- `autocomplete_fields` — автодополнение в формах редактирования FK/M2M полей
- `RangeFilter` — фильтрация по диапазону дат
- Кастомные actions через `group().apply_async()` (Celery) для bulk-операций
- `ReadOnlyAdminMixin` (`core/utils/admin.py`) — для инлайнов ошибок/позиций/ордеров/сигналов
- `ADMIN_INLINE_MAX_NUM = 10` — глобальное ограничение inline-записей

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

### TraderAdmin / ArbitrageTraderAdmin actions

`clean_trader_data`, `reboot`, `enable`, `disable`, `clear_errors`, `close_all_positions`, `export_to_xlsx` (через xlsxwriter). Display-методы: `get_balance`, `fact_pnl`, `theoretical_pnl`, `win_rate`.

## Docker

### Dev (`docker-compose.yml`) — 13 сервисов

`postgres:14.18-alpine` (5432), `redis:6.2-alpine` (6379), `backend` (gunicorn + debugpy:5678, build из `./backend`), `celery_beat`, `trader_worker` (`-Q trader`), `optimizer_worker` (`-Q optimizer`), `candle_source_worker` (`-Q candle_source`), `exchange_client_worker` (`-Q exchange_client`), `celery_worker` (default queue), `exchange_client_rpc_worker` (management command), `trader_ws_worker`, `candle_source_ws_worker`, `flower` (5555, `--url_prefix=flower`).

### Preprod (`docker-compose.preprod.yml`)

Те же сервисы + `nginx` + `certbot`. Образ `kletkinvasilii/trader:staging`. PostgreSQL на порту 15432 (для удалённого доступа). Автоскейлинг workers: `trader/optimizer/candle_source/exchange_client` = 1,1, `celery_worker` = 5,1. Healthchecks везде. `POSTGRES_APP_NAME=<сервис>` — для идентификации соединений в `pg_stat_activity`. Flower с `--basic_auth=${FLOWER_USER}:${FLOWER_PASSWORD}`.

### Production (`docker-compose.production.yml`)

Без PostgreSQL (внешняя управляемая БД). Образ `kletkinvasilii/trader:latest`. Остальные сервисы — копия preprod.

### Split-деплой (`deploy/{preprod,production}/{main,workers}/`)

Альтернативный вариант разнести backend+beat+infra на main-хост, а воркеры — на отдельный воркер-хост. Тот же состав сервисов разделён по двум compose-файлам.

### Dockerfile (`backend/Dockerfile`)

- Base: `python:3.12-slim`
- Poetry 2.1.2
- Пользователь: `appuser` (UID 5678)
- Порт: 8000 (gunicorn)
- Системные зависимости: build-essential, libpq-dev
- `entrypoint.sh` — миграции + collectstatic на старте

## CI/CD

### GitHub Actions (`.github/workflows/`)

| Workflow | Файл | Триггер | Назначение |
|----------|------|---------|-----------|
| CI (PR checks) | `ci-pull-request.yml` | PR → staging/main | Вызывает `checks.yml` |
| Checks (reusable) | `checks.yml` | Вызов из CI/CD | ruff check + ruff format + mypy + bandit + pytest --cov |
| Build (reusable) | `build.yml` | Вызов из CD | Docker build + push на Docker Hub |
| Deploy (reusable) | `deploy.yml` | Вызов из CD | SSH-деплой: pull → beat graceful shutdown → workers graceful shutdown (30с) → migrate + collectstatic → backend restart с healthcheck → workers restart → nginx reload → cleanup старых образов |
| CD Staging | `cd-staging.yml` | Push → `staging` | checks → build (`:staging`) → deploy |
| CD Production | `cd-production.yml` | Push → `main` | checks → build (`:latest`) → deploy |

**Примечание:** `cd-staging.yml` работает с veteran-именем "staging", при этом сами compose-файлы называются `preprod`. Образ имеет тег `:staging`.

### Git Flow

```
feature-branch → staging → main
```

## Тестирование

### Конфигурация (`pyproject.toml` `[tool.pytest.ini_options]`)

Тесты работают с **SQLite** (не Postgres), `CELERY_TASK_ALWAYS_EAGER=True`, `CELERY_TASK_EAGER_PROPAGATES=True`, `CACHEOPS_ENABLED=False`. `DJANGO_SETTINGS_MODULE=core.settings`.

**Coverage** (`[tool.coverage.run]`) omit: `**/domain/**/base.py`, `**/admin/**`, `**/charts/**`, `**/migrations/**`, `**/__init__.py`. Минимальный порог (в `checks.yml`): 50%.

### Иерархия фикстур

**Глобальные (`backend/conftest.py`):**
- `_mock_send_notification` (autouse) — мокает Telegram-уведомления
- `trading_pair` — BTC/USDT:USDT, FUTURES, fee 0.1%
- `timeframe` — ONE_HOUR
- `exchange_candle` — OHLCV доменный объект (open=100, high=110, low=90, close=105, volume=1000)

**Приложение traders (`traders/tests/conftest.py`):**
ORM-фикстуры: `exchange`, `trading_pair`, `exchange_client`, `candle_source`, `strategy`, `risk_manager`, `trader`.
Доменные фикстуры: `domain_trading_pair`, `domain_candle`, `domain_signal`, `domain_position`.

**Домен traders (`traders/domain/conftest.py`):**
Чистые Python-фикстуры (без БД): `trading_pair`, `candle`, `trader`, `mock_strategy`, `mock_risk_manager`, `mock_exchange_client`, `sample_candles`, `downtrend_candles`.

### Структура тестов

```
app/tests/
├── conftest.py
├── models/         # Тесты ORM-моделей
├── domain/         # Тесты доменной логики (pytest-asyncio для async)
├── tasks/          # Тесты Celery-задач
└── admin/          # Только traders/ — тесты admin-actions
```

В `traders/tests/domain/` есть отдельные файлы `test_*_mixins.py` для проверки каждого SL/TP/PS-миксина.

### Паттерны тестирования

- `@pytest.fixture` для всех фикстур, без Django `TestCase`
- `pytest-asyncio` для тестов доменного слоя
- `pytest-django` для ORM-тестов
- `pytest-env` для env-переменных из `pyproject.toml`
- `pytest-cov` для покрытия

## Стиль кода

- Python 3.12, длина строки 88
- **Ruff** — линтинг + форматирование (правила: E, W, F, I, B, C4, UP, DJ, SIM, PTH, RUF)
- Игнорируется: E501 (handled by formatter), B008, B905, RUF001-003 (кириллица допустима в строках/комментариях/докстрингах), RUF012
- Миграции и `staticfiles/` исключены из линтинга
- **MyPy:** plugins = `django-stubs`, `pydantic`. Исключены `migrations/` и `tests/`. Для моделей и тасков отключены `var-annotated` и `attr-defined` (конфликтуют с Django-магией).
- F401 игнорируется в `__init__.py`, S101 — в тестах
- **Импорты всегда выносятся на верх файла** — не использовать локальные импорты внутри функций/методов (это feedback-правило, см. MEMORY.md)
- first-party модули для isort: `core`, `exchanges`, `exchange_clients`, `candle_sources`, `candle_providers`, `traders`, `arbitrage_traders`, `telegram_bots`

## Настройки Django (`core/settings.py`)

- `LANGUAGE_CODE = "ru-ru"`, `TIME_ZONE = "Europe/Moscow"`, `USE_TZ = True`
- `CONN_MAX_AGE=600`, `CONN_HEALTH_CHECKS=True` (только для postgresql)
- `DB_STATEMENT_TIMEOUT=30000` (мс) — через `options`
- `application_name` в опциях соединения = `POSTGRES_APP_NAME` env-var (идентификация в `pg_stat_activity`)
- Кэш: Redis (DB 1, timeout 300с, prefix `"trader"`)
- Cacheops: отдельная Redis DB 4, кэшируются только count-запросы
- Логирование: **loguru** (colorized в DEBUG, JSON-serialize в production), все стандартные Django-логгеры перенаправляются через `InterceptHandler`
- `INSTALLED_APPS`: `django_celery_beat`, `django_celery_results`, `django_plotly_dash`, `admin_auto_filters`, `rangefilter`, `channels`, `cacheops`, `debug_toolbar` (только DEBUG)
- `CHANNEL_LAYERS`: `channels.layers.InMemoryChannelLayer`
- `ADMIN_INLINE_MAX_NUM=10`, `BULK_BATCH_SIZE=1000`
- Debug Toolbar отключён на пути `/django_plotly_dash/` и панели Cache/Profiling
- Все ORM-обращения из async-контекста проходят через `core.utils.async_orm.aiter_sync_chunked` (чанкованная `sync_to_async`-итерация) или инстанциируются до `asyncio.run`. Флаг `DJANGO_ALLOW_ASYNC_UNSAFE` не выставляется — `SynchronousOnlyOperation` работает.

## URL-роутинг (`core/urls.py`)

| URL | Назначение |
|-----|-----------|
| `/admin/` | Django Admin |
| `/django_plotly_dash/` | Plotly-дашборды (equity curves, графики стратегий) |
| `/traders/` | Эндпоинты трейдеров |
| `/arbitrage_traders/` | Эндпоинты арбитражных трейдеров |
| `/candle_sources/` | Эндпоинты источников свечей |
| `/exchanges/` | Эндпоинты бирж |
| `/exchange_clients/` | Эндпоинты клиентов бирж |
| `/health/` | Health check (проверяет БД + Redis через `cache.set/get`, возвращает 503 при проблемах) |
| `/health/live/` | Liveness check (просто `{"status": "alive"}`) |
| `/` | Редирект на `/admin/` |

В DEBUG добавляются `debug_toolbar_urls()` и статика.

## Переменные окружения (`.env`)

| Переменная | Назначение | Default |
|------------|-----------|---------|
| `SECRET_KEY` | Django secret key | `"secret_key"` |
| `DEBUG` | Режим отладки | `False` |
| `LOG_LEVEL` | Уровень логирования | `DEBUG` |
| `DJANGO_ALLOWED_HOSTS` | Разрешённые хосты (через пробел) | `*` |
| `CSRF_TRUSTED_ORIGINS` | CSRF origins (через пробел) | `""` |
| `POSTGRES_ENGINE` | Django DB engine | `django.db.backends.sqlite3` |
| `POSTGRES_DATABASE/USER/PASSWORD/HOST/PORT` | Параметры Postgres | — |
| `POSTGRES_APP_NAME` | `application_name` в pg_stat_activity | `django` |
| `DB_STATEMENT_TIMEOUT` | мс, statement_timeout | `30000` |
| `REDIS_HOST/PORT/USER/PASSWORD` | Параметры Redis | `redis:6379` |
| `REDIS_BROKER_DATABASE` | DB для Celery | `0` |
| `REDIS_CACHE_DATABASE` | DB для Django cache | `1` |
| `REDIS_EXCHANGE_CACHE_DATABASE` | DB для WS-кэша свечей | `2` |
| `REDIS_BUS_DATABASE` | DB для Bus/RPC | `3` |
| `REDIS_CACHEOPS_DATABASE` | DB для cacheops | `4` |
| `CACHEOPS_ENABLED` | Включить cacheops | `True` |
| `CELERY_RESULT_BACKEND` | Бэкенд результатов | `django-db` |
| `CELERY_TASK_ALWAYS_EAGER` | Синхронное выполнение (True в тестах) | `False` |
| `CELERY_TASK_EAGER_PROPAGATES` | Пробрасывать исключения в eager-режиме | `False` |
| `FLOWER_USER/PASSWORD` | Basic auth для Flower (prod) | — |
| `DOCKERHUB_USERNAME/PASSWORD` | Credentials для push (GitHub Actions secret) | — |
| `USE_BUS` | Использовать Redis-шину (иначе LocalBusClient) | — |
