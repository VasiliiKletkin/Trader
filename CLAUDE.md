# CLAUDE.md

Руководство для Claude Code (claude.ai/code) по работе с кодовой базой проекта.

## Обзор проекта

Система криптовалютной торговли на Django + Celery. Поддерживает обычную и арбитражную торговлю на нескольких биржах. Архитектура — Domain-Driven Design: ORM-модели отвечают за персистентность, доменные классы — за асинхронную бизнес-логику.

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
    ├── exchange_clients/     # API-клиенты бирж (18 бирж), балансы, ордера
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
│   │   └── base.py        # Доменные классы (async бизнес-логика)
│   ├── strategies/
│   │   ├── base.py        # Абстрактная стратегия
│   │   └── *.py           # Конкретные реализации
│   ├── risk_managers/
│   │   ├── base.py        # Абстрактный риск-менеджер + миксины
│   │   └── *.py           # Конкретные комбинации миксинов
│   ├── optimizations/     # Алгоритмы оптимизации
│   ├── ws/                # WebSocket-стримы (только candle_sources)
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

### Бизнес-логика обработки свечей (handle_candle)

Центральный механизм как обычного, так и арбитражного трейдера — метод `handle_candle`. Ключевые инварианты:

#### 1. Множественные сигналы на одну свечу (live-режим)

В live-режиме Beat запускает конвейер **каждую минуту**. Последняя свеча (например, часовая) ещё формируется и обновляется на бирже. При каждом запуске:
- `CandleSource` загружает последние 2 свечи с биржи и upsert'ит их в БД
- Задача берёт последнюю свечу из БД (`get_last_candles(count=1)`) и передаёт в `handle_candle`
- На одну и ту же формирующуюся свечу (один timestamp) генерируется **несколько сигналов** — по одному за каждый вызов задачи

Таким образом, одна свеча с таймфреймом 1 час может породить до ~60 сигналов (по числу минутных тиков).

#### 2. Один сигнал на свечу (reboot-режим)

При reboot (бэктестинг) трейдер обрабатывает **завершённые исторические свечи** из БД за последние 365 дней. Каждая свеча обрабатывается ровно один раз → **один сигнал на свечу**. Реальные ордера не создаются (`create_new_orders = False`). Таймстампы сигналов берутся из свечи, а не из `timezone.now()`.

#### 3. Метод `load()` — исключение текущей свечи

`load()` загружает в доменный объект:
- **Свечи**: последние 1000 из БД **без последней** (`[:-1]`) — последняя ещё формируется и будет передана в `handle_candle` отдельно
- **Позиции**: только открытые (OPENED), отсортированные по `opened_at`
- **Сигналы и ошибки**: не загружаются (пустые deque/list)

Это гарантирует, что текущая свеча не дублируется: она исключена из `load()` и попадает в `self.candles` только внутри `handle_candle`.

При reboot `load()` **не вызывается** — трейдер стартует с пустым состоянием и накапливает свечи итеративно.

#### 4. Порядок операций внутри `handle_candle`

```
1. get_signal(candle)          — свеча ещё НЕ в self.candles
2. self.signals.append(signal) — сигнал добавлен
3. self.candles.append(candle) — свеча добавлена в deque
4. handle_opened_positions()   — свеча уже в self.candles
5. can_open_position() → open_position()
```

Стратегия при генерации сигнала (шаг 1) получает `trader.candles` как историю без текущей свечи и текущую свечу как отдельный аргумент — **чтобы избежать двойного учёта**. Риск-менеджер при расчёте SL/TP (шаги 4-5) уже видит текущую свечу в `self.candles`.

#### 5. Различия обычного и арбитражного трейдера

| Аспект | Trader | ArbitrageTrader |
|--------|--------|-----------------|
| Свечи | Одна свеча от одного источника | Пара свечей (left + right) от двух бирж |
| Закрытие позиций | SL, TP, стратегия, обратный сигнал | Только стратегия и обратный сигнал |
| Trailing stop | Да (настраиваемый) | Нет |
| Reboot: синхронизация | — | Проверка совпадения таймстампов left/right, `CandleDesyncError` при расхождении |

## Django-приложения

### exchanges — Биржи и свечи

**Модели:**
- `Exchange` — определение биржи (name, class_name, max_candles_per_request=999)
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

**Поддерживаемые биржи (18):**
Binance, Bybit, OKX, Kraken, Bitfinex, BitMEX, Coinbase, KuCoin, Bitget, HTX (Huobi), WooFiPro, Deribit, Paradex, Phemex, CoinEX, MEXC, Gateio, Hyperliquid

Все используют ccxt.async_support с поддержкой demo-режима и HTTP/SOCKS5 прокси.

### candle_sources — Источники свечей

**Модели:**
- `CandleSource` — связывает exchange_client + trading_pair + timeframe + mode (unique constraint)
- `CandleSourceError` — ошибки при загрузке свечей

**Режимы получения данных (`CandleSourceMode`):**
- `REST` — периодический fetch через REST API (каждую минуту через Beat)
- `WEBSOCKET` — real-time стриминг через ccxt.pro.watch_ohlcv, кэш в Redis

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

### Файлы

| Файл | Назначение |
|------|-----------|
| `candle_sources/management/commands/run_ws_streams.py` | Точка входа, колбэки on_candle/on_error |
| `candle_sources/domain/ws/manager.py` | WebSocketStreamManager — оркестрация стримов |
| `candle_sources/domain/ws/streams.py` | OHLCVStream, OrderBookStream — обработка данных |
| `candle_sources/domain/ws/redis_cache.py` | CandleRedisCache — кэш последних 2 свечей в Redis |

### Redis-кэш свечей

- БД: `REDIS_CANDLE_CACHE_DATABASE` (default: 2)
- Формат ключа: `ws:candle:{exchange}:{symbol}:{timeframe}`
- Хранит последние 2 свечи (предыдущая + формирующаяся) как JSON-dict с ключами-таймстампами
- TTL = длительность таймфрейма
- При каждом обновлении старейшая свеча удаляется, если их > 2

### Конвейер синхронизации WS → БД

```
Beat (каждую минуту) → sources_fetch_last_candles()
  → sources_sync_from_redis(source_ids) — одна задача для всех WS-источников
    → Читает свечи из Redis для каждого source_id
    → Bulk insert в PostgreSQL (upsert по unique constraint)
    → Запускает traders_process_by_sources() и arbitrage_traders_process_by_sources()
```

### Динамическое управление

- Каждые 30 секунд `_sync_loop()` загружает подписки из БД
- `_reconcile()` сравнивает текущие стримы с подписками: добавляет новые, удаляет неактивные
- Между подключением стримов — пауза 0.5с для предотвращения rate limit
- Graceful shutdown по SIGTERM/SIGINT: отмена всех задач, закрытие клиентов
- Exponential backoff (1-60с) при ошибках подключения

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
| worker_candle_sources_fetch | `candle_sources_fetch` | 5-1 | Загрузка свечей (REST + sync из Redis) |
| worker_traders_process | `traders_process` | 5-1 | Обработка трейдеров |
| worker_traders_reboot | `traders_reboot` | — | Бэктестинг (reboot) |
| worker_optimizers_optimize | `optimizers_optimize` | — | Оптимизация параметров |
| worker | default | — | Общие задачи (уведомления, балансы) |

### Beat-расписание

| Задача | Расписание |
|--------|-----------|
| `sources_fetch_last_candles` | Каждую минуту |
| `exchange_clients_fetch_balances` | Ежедневно в 00:00 |
| `traders_daily_report` | Ежедневно в 10:00 |
| `arbitrage_traders_daily_report` | Ежедневно в 10:00 |

### Конвейер задач

```
Beat (каждую минуту)
  → sources_fetch_last_candles
    ├── REST-источники: fanout sources_fetch_last_candles_for_exchange_client() по exchange_client
    │     → fetch + sync свечей для каждого CandleSource
    │       → traders_process_by_sources() / arbitrage_traders_process_by_sources()
    └── WS-источники: sources_sync_from_redis(source_ids)
          → читает кэш из Redis → bulk insert в БД
            → traders_process_by_sources() / arbitrage_traders_process_by_sources()
```

### Задачи для одиночного трейдера

| Задача | Очередь | Назначение |
|--------|---------|-----------|
| `trader_process(trader_id)` | `traders_process` | Обработка одной свечи для конкретного Trader |
| `arbitrage_trader_process(trader_id)` | `traders_process` | Обработка одной свечи для конкретного ArbitrageTrader |

Предназначены для ручного запуска из админки или shell. Используют тот же конвейер: `instantiate() → load() → handle_candle() → sync()`.

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

### Candle Source (candle_sources/schemas.py)

| Enum | Значения |
|------|---------|
| `CandleSourceMode` | REST, WEBSOCKET |

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

### Сервисы

**Dev (docker-compose.yml) — 11 сервисов:**
postgres (14.18-alpine), redis (6.2-alpine), backend (gunicorn + debugpy:5678), beat, worker_candle_sources_fetch, worker_traders_process, worker_traders_reboot, worker_optimizers_optimize, worker, ws_streams, flower (порт 5555).

**Staging (docker-compose.staging.yml):**
Те же сервисы + nginx (SSL/Certbot). Образы: `kletkinvasilii/trader:staging`. PostgreSQL на порту 15432. Autoscale: 3-1 для sources/traders, 1-1 для reboot/optimizers. Health checks.

**Production (docker-compose.production.yml):**
Без PostgreSQL (внешняя БД). Образы: `kletkinvasilii/trader:latest`. nginx (SSL/Certbot). Те же воркеры с оптимизированным масштабированием.

### Dockerfile

- Base: python:3.12-slim
- Poetry 2.1.2, user: appuser (UID 5678)
- Порт: 8000 (gunicorn)
- Системные зависимости: build-essential, libpq-dev

## Утилиты (core/utils/)

| Модуль | Назначение |
|--------|-----------|
| `registry.py` | Базовый класс Registry с авто-регистрацией через `__init_subclass__` |
| `mixins.py` | `ActiveManagerMixin` (is_active + active_objects), `TimeStampedMixin` (created_at, updated_at) |
| `cache.py` | `@cached_method` — Redis-кэширование методов с TTL, `invalidate_cached_methods()` |
| `common.py` | `get_all_init_args()` — параметры конструктора, `dt_str()` — форматирование даты (DD.MM.YYYY HH:MM:SS) |
| `charts.py` | Генерация графиков: equity curve, позиции/сигналы, точность |

## Django Admin

### Общие паттерны

- `AutocompleteFilter` (из `admin_auto_filters`) — автодополнение в фильтрах для FK-полей
- `autocomplete_fields` — автодополнение в формах редактирования FK/M2M полей
- `RangeFilter` — фильтрация по диапазону дат
- Кастомные actions: enable/disable, reboot, export XLSX, close positions
- Inline-модели для ошибок, ордеров

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

### Deploy-процесс (deploy.yml)

1. Pull новых Docker-образов (backend, workers, beat, flower, ws_streams)
2. Остановка beat (предотвращение новых задач)
3. Graceful stop воркеров (30с timeout)
4. Миграции + collectstatic
5. Рестарт backend с health checks
6. Рестарт воркеров, beat, ws_streams
7. Reload nginx

### Git Flow

```
feature-branch → staging → main
```

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

## Тестирование

### Конфигурация

Тесты используют SQLite (не Postgres) и eager Celery (задачи выполняются синхронно). Настроено в `pyproject.toml` под `[tool.pytest.ini_options]`.

Coverage: omit `domain/**/base.py` (async-код, тестируется интеграционно). Минимальный порог: 50%.

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
- Redis БД: 0 (Celery broker), 1 (Django cache), 2 (WebSocket candle cache)
- Кэш: Redis (timeout 300s, prefix "trader")
- Statement timeout PostgreSQL: 30s
- Логирование: loguru (colorized в dev, JSON в production)
- INSTALLED_APPS: django_celery_beat, django_celery_results, django_plotly_dash, admin_auto_filters, rangefilter, channels, debug_toolbar (dev)

## Переменные окружения (.env)

| Переменная | Назначение |
|------------|-----------|
| `SECRET_KEY` | Django secret key |
| `DEBUG` | Режим отладки |
| `DJANGO_ALLOWED_HOSTS` | Разрешённые хосты |
| `POSTGRES_ENGINE/DATABASE/USER/PASSWORD/HOST/PORT` | PostgreSQL |
| `REDIS_HOST/PORT/USER/PASSWORD/DATABASE` | Redis |
| `REDIS_CANDLE_CACHE_DATABASE` | Redis БД для WS-кэша свечей (default: 2) |
| `CELERY_BROKER` | URL брокера Celery |
| `CELERY_RESULT_BACKEND` | Бэкенд результатов (django-db) |
| `CELERY_TASK_ALWAYS_EAGER` | Синхронное выполнение (True для тестов) |
| `LOG_LEVEL` | Уровень логирования |
