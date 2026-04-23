# План тестирования проекта

Документ — **инвентарь публичных методов** + **план тестовых кейсов** + **mapping на существующие тесты**.

## Методология

Разделение по слоям (основываясь на DDD-архитектуре):

| Слой | Что тестируем | Техника |
|------|---------------|---------|
| **ORM-модели** | Persistence + запросы + constraints + sync/instantiate | `pytest-django`, `@pytest.mark.django_db`, `CaptureQueriesContext` |
| **Domain** | Бизнес-логика (чистый Python, без БД) | `pytest-asyncio`, mocks, in-memory fixtures |
| **Celery tasks** | Интеграция слоёв + dispatch flow | Eager Celery + pytest-django |
| **Templates/Views** | Рендеринг + контекст | `Client.get()` + assertContains |

### Для моделей — основные категории тестов

1. **Creation** — создание с дефолтами; с explicit values; валидация `clean()`.
2. **UniqueConstraint** — IntegrityError при дубле по natural-key.
3. **ORM-методы** — `instantiate`, `sync_*`, `refresh`, `load` (что возвращают / обновляют).
4. **QuerySet-методы** — статистика (`get_pnl`, `get_win_rate`...), фильтры.
5. **SQL-аннотации** — `theoretical_pnl_annotation`, `fact_pnl_annotation` — правильность формулы.
6. **Query count** — `CaptureQueriesContext` для критичных путей (чтобы sync не делал N+1).

### Для domain — бизнес-логика

1. **Signal generation** (strategy) — на разных candle-последовательностях возвращать правильный `BUY/SELL/WAIT`.
2. **Risk manager** — SL/TP/position_size для LONG/SHORT, edge cases (мин/макс).
3. **Trader.open_position / close_position / handle_candle** — happy path, SL-exit, TP-exit, по-сигналу, trailing stop.
4. **PnL/ROI/Sharpe/R²** — на заранее рассчитанных данных.
5. **Optimizer** — scoring, разделение params по префиксам.

### Для tasks

1. **Dispatch** — правильный fanout (group of subtasks).
2. **Happy path** — с моками ORM и domain.
3. **Error handling** — что попадает в `*Error` таблицу.
4. **Query count** — интеграционные checks.

---

## 1. ORM-модели

### `traders.Trader`
**Публичные методы:**
- `instantiate() → DomainTrader`
- `load(trader)` — загрузка свечей и позиций
- `sync(trader)` — обёртка: sync_signals/positions/orders/errors
- `sync_signals(trader)`, `sync_positions(trader)`, `sync_orders(trader)`, `sync_errors(trader)`
- `enable()` / `disable()` / `clear_all_errors()` / `clear_all_data()`
- `handle_candle(candle)` / `reboot()` / `close_all_opened_positions()` / `close_position(position)`
- `has_existing_signal(timestamp)`
- `get_opened_positions()` / `get_closed_positions()` / `get_total_positions_count()` / `get_total_positions_count_with_orders()` / `get_total_orders_count()`
- `get_candles(start, end)` / `get_candle_iterator(start, end)` / `get_last_candle()` / `get_last_candles(count)`
- `get_win_rate(start, end)` / `get_fact_pnl(start, end)` / `get_theoretical_pnl(start, end)` / `get_avg_candles_per_position(start, end)` / `get_balance(date)` / `get_pnl_r2(start, end)`
- `clean()`
- **@staticmethod** `theoretical_pnl_annotation()`, `fact_pnl_annotation()`

**Что тестируем:**
| Аспект | Приоритет | Статус |
|--------|-----------|--------|
| Создание + UniqueConstraint (13 fields) | P2 | ✅ covered |
| `clean()` — max 50 traders на клиента, совпадение бирж | P1 | ✅ covered |
| `instantiate()` — все поля маппятся | P0 | ✅ covered |
| `load()` — свечи + только opened позиции | P0 | ✅ covered |
| `sync_positions` — upsert существующих, create новых, query count | P0 | ✅ covered |
| `sync_orders` — lookup по natural-key, создание `TraderOrder` | P0 | ✅ covered |
| `sync_signals` — dedup по `(trader, timestamp, type)` | P1 | ✅ covered |
| `sync_errors` — только `id is None`, вызов `send_notification` | P1 | ✅ covered |
| `handle_candle` — instantiate→load→asyncio.run→sync | P0 | ✅ covered |
| `reboot()` — clear_all_data, status transitions, `asyncio.run(trader.reboot)` | P0 | ✅ covered |
| `close_position` / `close_all_opened_positions` | P1 | ✅ covered |
| `clear_all_*` — удаление связанных объектов | P2 | ✅ covered |
| `get_*` (статистика) — на фикстурах с известными данными | P1 | ✅ covered |
| `theoretical_pnl_annotation` / `fact_pnl_annotation` — формула через cost | P0 | ✅ covered |

**Пробелы:** статистика query count (N+1 регрессии при добавлении новых полей).

---

### `traders.TraderPosition`
**Методы:** `instantiate()`, `refresh()` + computed properties (`pnl`, `pnl_pct`, `rr`, `stop_loss_pct`, `take_profit_pct`, `is_closed`).

| Аспект | Приоритет | Статус |
|--------|-----------|--------|
| UniqueConstraint `(trader, opened_at, type)` | P0 | ✅ covered |
| `instantiate()` — все поля | P0 | ✅ covered |
| `refresh()` — пересчёт из ордеров (open_price, close_price, open_amount, close_amount, open_cost, close_cost, total_fee) | P0 | ✅ covered |
| `refresh` с пустым списком ордеров — no-op | P1 | ✅ covered |
| `refresh` — weighted average price при нескольких ордерах одной стороны | P1 | ✅ covered |
| Properties: `pnl`, `pnl_pct`, `rr`, `stop_loss_pct`, `take_profit_pct`, `is_closed` | P1 | ✅ covered |

**Пробел:** `refresh` для смешанных ордеров (partial fills, отменённые).

---

### `traders.TraderOrder`, `TraderSignal`, `TraderError`
| Аспект | Приоритет | Статус |
|--------|-----------|--------|
| `TraderOrder.clean()` — position.trader == trader | P1 | ✅ covered |
| `TraderOrder.instantiate()` | P1 | ✅ covered |
| `TraderSignal` — UniqueConstraint `(trader, timestamp, type)` | P1 | ✅ covered |
| `TraderError` — автовключение отправки notification | P1 | ✅ covered |

---

### `traders.Strategy`, `RiskManager`, `TraderOptimizationAlgorithm`
**Методы:** `get_class()`, `instantiate(**kwargs)`, `save()` (заполняет `arguments` дефолтами), `get_description()`.

| Аспект | Приоритет | Статус |
|--------|-----------|--------|
| `get_class()` — возвращает class из Registry | P1 | ✅ covered |
| `instantiate(**overrides)` — merge с defaults из `arguments` | P0 | ✅ covered |
| `save()` — автозаполнение `arguments` | P1 | ✅ covered |
| Несуществующий `class_name` → ошибка | P2 | ⚠ partial |

---

### `traders.TraderOptimizer`
**Методы:** `instantiate()`, `get_candle_iterator()`, `optimize()` + @cached_property `timeframe`, `trading_pair`.

| Аспект | Приоритет | Статус |
|--------|-----------|--------|
| `optimize()` — запуск алгоритма, запись result, обработка ошибок | P0 | ✅ covered |
| `get_candle_iterator()` — возвращает domain свечи за lookback_period | P1 | ✅ covered |
| `instantiate()` — маппинг 15+ полей в domain | P1 | ⚠ partial |
| `cached_property` — 1 SQL на `timeframe`/`trading_pair` | P2 | ⚠ partial |

---

### `arbitrage_traders.*` (ArbitrageTrader, Position, Signal, Order, Error, Strategy, RiskManager, Optimizer)

Полностью симметрично `traders.*`, статус покрытия аналогичный. Специфичные для арбитража пункты:

| Аспект | Приоритет | Статус |
|--------|-----------|--------|
| `get_candle_iterator()` — merge left+right по timestamp, skip unmatched | P0 | ✅ covered |
| `get_last_candle(lookup_window)` — итерация с конца, матчинг | P1 | ✅ covered |
| `clean()` — биржи разные, таймфреймы совпадают | P1 | ✅ covered |
| `ArbitrageExchangeCandle.instantiate()` — валидация `CandleDesyncError` | P1 | ✅ covered |

---

### `exchanges.Exchange`, `TradingPair`, `ExchangeTradingPair`, `ExchangeCandle`

| Аспект | Приоритет | Статус |
|--------|-----------|--------|
| `Exchange.instantiate()`, `instantiate_public_client()` | P1 | ⚠ partial |
| `Exchange.sync_trading_pairs(market_type)` — создание+update+деактивация | P0 | ❌ **missing** |
| `TradingPair.instantiate(exchange)` | P1 | ⚠ partial |
| `ExchangeTradingPair.instantiate()` | P1 | ⚠ partial |
| `ExchangeCandle.instantiate()` | P1 | ⚠ partial |

**Крупный пробел:** `Exchange.sync_trading_pairs` — критичная задача, запускается ежедневно через beat. Сейчас тестов нет.

---

### `exchange_clients.*` (ExchangeClient, Proxy, Balance, Order)

| Аспект | Приоритет | Статус |
|--------|-----------|--------|
| `ExchangeClient.instantiate()` / `.get_rpc_client()` | P1 | ⚠ partial |
| `ExchangeClient.fetch_balances` (async) + `sync_balances` | P1 | ❌ missing |
| `ExchangeClient.create_market_order` через RPC | P0 | ❌ missing |
| `ExchangeClient.set_margin_mode`, `set_leverage`, `cancel_all_orders` | P1 | ❌ missing |
| `ExchangeClient.activate/deactivate` | P2 | ⚠ partial |
| `ExchangeClientOrder.sync_from_exchange` | P0 | ⚠ partial (через sync_orders task) |
| `ExchangeClientProxy.check_obj()` | P2 | ❌ missing |

**Крупный пробел:** вся цепочка вызовов через RPC (fetch_balances → sync → БД).

---

### `candle_sources.CandleSource`

| Аспект | Приоритет | Статус |
|--------|-----------|--------|
| `instantiate(domain_exchange_client)` | P0 | ⚠ partial |
| `sync_candles(limit, since)` — батчи, upsert, error handling | P0 | ❌ missing |
| `delete_candles(before)` | P1 | ⚠ partial |
| `get_candle_iterator(start, end)` — lazy QuerySet | P1 | ✅ covered |
| `get_last_candle`, `get_last_candles(count)` | P1 | ⚠ partial |
| `clean()` — проверка пары на бирже | P1 | ❌ missing |
| UniqueConstraint `(exchange, trading_pair, timeframe)` | P2 | ⚠ partial |

---

### `telegram_bots.TelegramBot`, `TelegramChat`

| Аспект | Приоритет | Статус |
|--------|-----------|--------|
| `TelegramChat.unique(bot, chat_id)` | P2 | ⚠ partial |
| `ActiveManagerMixin.active_objects` | P2 | ⚠ partial |

---

## 2. Domain-классы

### `traders.domain.Trader`
**Async методы:** `create_market_order`, `open_position`, `close_position`, `handle_opened_positions`, `handle_candle`, `reboot(candle_iterator)`, `close_all_opened_positions`.
**Sync:** `get_last_candles`, `can_open_position`, `is_drawdown_within_limit`, `can_open_more_positions`, `get_current_balance`, `update_position`, `get_signal`, `position_should_be_closed`, `get_pnl`, `get_roi`, `get_win_rate`, `get_sharpe_ratio`, `get_pnl_r2`, `get_total_positions`, `get_avg_candles_per_position`.

| Аспект | Приоритет | Статус |
|--------|-----------|--------|
| `open_position(BUY)` → LONG, SL/TP через risk_manager, create_market_order если `create_new_orders` | P0 | ✅ covered |
| `open_position(SELL)` → SHORT | P0 | ✅ covered |
| `open_position` — `amount=None` → `return None` (fit_amount не прошёл) | P1 | ✅ covered |
| `open_position` — ошибка биржи → error в `self.errors`, `return None` | P1 | ✅ covered |
| `open_position` — min_amount, max_amount clamping | P1 | ✅ covered |
| `close_position(SL/TP/MANUAL/STRATEGY/OPPOSITE_SIGNAL)` | P0 | ✅ covered |
| `close_position` — partial fill (close_amount != open_amount) | P2 | ⚠ partial |
| `close_position` — `create_new_orders=False` (симуляция) | P0 | ✅ covered |
| `handle_candle` — WAIT сигнал → только update_position | P1 | ✅ covered |
| `handle_candle` — BUY без drawdown/max_positions → open | P0 | ✅ covered |
| `handle_candle` — BUY с drawdown > max → не открывать | P1 | ✅ covered |
| `update_position` (trailing stop) — LONG/SHORT | P1 | ✅ covered |
| `position_should_be_closed` — по SL, TP, OPPOSITE, STRATEGY | P0 | ✅ covered |
| `reboot(AsyncIterator)` — весь цикл по свечам, close_all в конце, create_new_orders=False во время | P0 | ✅ covered |
| `get_pnl/roi/sharpe/r2/win_rate/avg_candles_per_position` — формулы | P1 | ✅ covered |
| `can_open_position` — композит (WAIT signal, drawdown, max_positions) | P1 | ✅ covered |

**Пробелы:** exception в `strategy.get_signal()` (сейчас ловится в `handle_candle`, но тест на это — нет); exception в `risk_manager.calculate_position_size()`.

---

### `traders.domain.strategies.*` (9 стратегий)

Для каждой стратегии **минимальный тест-пакет**:

| Аспект | Приоритет | Статус |
|--------|-----------|--------|
| `get_signal` — BUY при правильных условиях (например, Stochastic < oversold) | P0 | ✅ covered для Stochastic, Renko, MFI, Donchian, MACrossover, MeanReversion, Grid |
| `get_signal` — SELL при противоположных условиях | P0 | ✅ covered |
| `get_signal` — WAIT (недостаточно данных, нейтральные условия) | P0 | ✅ covered |
| `PARAM_CONSTRAINTS` — валидация min/max | P2 | ⚠ partial |
| `position_should_be_closed` (если стратегия определяет) — STRATEGY reason | P1 | ✅ covered для некоторых |

---

### `traders.domain.risk_managers.*` (8 classes + mixins)

**Mixin-уровень тестов:**
| Mixin | Приоритет | Статус |
|-------|-----------|--------|
| `StopLossPercentMixin.get_stop_loss` — LONG/SHORT | P0 | ✅ covered (test_sl_percent_mixin) |
| `StopLossExtremumMixin.get_stop_loss` — из min/max N свечей | P0 | ✅ covered |
| `TakeProfitPercentMixin.get_take_profit` — LONG/SHORT | P0 | ✅ covered |
| `TakeProfitRiskRewardMixin.get_take_profit` — через SL-distance × RR | P0 | ✅ covered |
| `PositionSize*` mixins — fixed cost, % balance | P0 | ✅ covered |

**Combo-classes (8 штук):**
Проверить `instantiate` с разным набором params и что корректно работают все три hooks (SL, TP, Size) с ожидаемыми значениями.
Статус — ✅ covered, но не все 8 классов одинаково детально.

---

### `traders.domain.optimizations.TraderOptimizer`
| Аспект | Приоритет | Статус |
|--------|-----------|--------|
| `optimize()` — Optuna + DEAP алгоритмы, best params → final trader | P0 | ✅ covered |
| `get_score(params)` — метрики нормализованы, итоговый score через взвешенную сумму | P0 | ✅ covered |
| `get_trader(params)` — разделение по префиксам `strategy_*` / `risk_manager_*` | P1 | ✅ covered |
| Пустой candle_iterator → 0 метрики | P1 | ✅ covered |

---

### `arbitrage_traders.domain.ArbitrageTrader`
Симметрично `traders.domain.Trader`, плюс:

| Аспект | Приоритет | Статус |
|--------|-----------|--------|
| `open_position` — left+right ордера параллельно через `asyncio.gather` | P0 | ✅ covered |
| `open_position` — **left fail + right ok → rollback right** (новая ветка) | P0 | ⚠ **partial** — нет unit-теста именно этой ветки |
| `open_position` — left ok + right fail → rollback left | P0 | ✅ covered |
| `open_position` — обе упали → errors + `return None` | P0 | ✅ covered |
| `open_position` — разные `left_amount`/`right_amount` из-за `contract_size` | P0 | ✅ covered |
| `close_position` — rollback при right fail | P0 | ✅ covered |
| `ArbitrageCandle` — валидация `CandleDesyncError` | P1 | ✅ covered |

**Приоритетный пробел:** unit-тест для сценария «left fail + right ok → rollback right» в `open_position`.

---

### `exchange_clients.domain.AbstractExchangeClient` (и 18 конкретных реализаций)

**Для 18 биржевых клиентов** в основном тесты проверяют:
- Корректное формирование ccxt-параметров для `create_market_order`.
- Парсинг ответа в `ExchangeClientOrder`.
- Маппинг `MarketType` → ccxt market_type.

Статус: **большинство не тестируется** (⚠ partial). Это OK — ccxt — внешняя библиотека, mocking тяжёлый. Обычно полагаемся на real-world integration.

| Аспект | Приоритет | Статус |
|--------|-----------|--------|
| `get_ccxt_market_type(MarketType.FUTURES)` → `"swap"` | P2 | ⚠ partial |
| `fetch_candles` — корректная пагинация | P1 | ⚠ partial |
| Async context manager `__aenter__/__aexit__` | P2 | ⚠ partial |

---

### `exchanges.domain.TradingPair` (Pydantic)
**Методы:** `quantize_amount`, `quantize_price`, `compute_cost`, `cost_to_amount`, `fit_amount`.

| Аспект | Приоритет | Статус |
|--------|-----------|--------|
| `compute_cost` — linear: `amount * price` | P0 | ⚠ partial |
| `compute_cost` — inverse: `amount * contract_size * price` | P0 | ⚠ partial |
| `cost_to_amount` — обратное | P0 | ⚠ partial |
| `quantize_amount` — округление вниз до `amount_precision` | P0 | ⚠ partial |
| `fit_amount` — clamp `(min_amount, max_amount)`, precision, `None` если не подходит | P0 | ⚠ partial |

**Критичный пробел:** хотя `TradingPair.*` используется везде (open_position, close_position, fit_amount), **прямых unit-тестов Pydantic-схемы мало**. Тестируется через trader.open_position, но косвенно.

---

### `candle_sources.domain.CandleSource`
| Аспект | Приоритет | Статус |
|--------|-----------|--------|
| `fetch_candles` — одна батчевая загрузка | P0 | ✅ covered |
| `fetch_candles_iter` — итератор батчей | P0 | ✅ covered |
| `_build_batch_params` — разбиение (since, limit) на ≤ `max_candles_per_request` | P1 | ✅ covered |
| Error handling — exception в `exchange_client.fetch_candles` → пустой список + error | P1 | ⚠ partial |

---

### `candle_sources.domain.ws.CandleRedisCache` и `ArbitrageCandleCache`
| Аспект | Приоритет | Статус |
|--------|-----------|--------|
| `set_candle` + `get_candles` — up to 2 last candles, JSON | P0 | ⚠ partial (async, нужен pytest-asyncio + fakeredis) |
| `delete_candle` | P2 | ❌ missing |
| `ArbitrageCandleCache.set_candle` — return `True` при паре с совпадающим timestamp | P0 | ❌ missing |
| TTL expires | P2 | ❌ missing |

---

### `core.utils.async_orm`
| Аспект | Приоритет | Статус |
|--------|-----------|--------|
| `aiter_sync_chunked(iterable, chunk_size)` — chunked через `sync_to_async` | P0 | ❌ missing |
| `aiter_from_iterable` | P2 | ⚠ implicit (тесты reboot используют) |
| Чанкование > 1000 элементов | P1 | ❌ missing |
| Ленивый QuerySet — не материализует всё сразу | P0 | ❌ missing |

**Пробел:** нет прямых unit-тестов ключевой утилиты.

---

### `core.bus.get_bus_client`
| Аспект | Приоритет | Статус |
|--------|-----------|--------|
| `local=True` → `LocalBusClient` | P1 | ⚠ partial |
| `local=False` → `BusClient` с Redis broker | P1 | ⚠ partial |

---

## 3. Celery tasks

### `traders.tasks`
| Task | Что тестируем | Статус |
|------|---------------|--------|
| `dispatch_traders_for_sources(source_ids)` | fanout: 0 traders → no-op; N traders → group(N subtasks) | ⚠ partial |
| `trader_process(trader_id)` | full cycle: instantiate→load→handle_candle→sync; exception → TraderError.create + notification | ⚠ partial |
| `trader_process` — несуществующий trader_id → DoesNotExist | P1 | ❌ missing |
| `trader_reboot(trader_id)` | вызывает `trader.reboot()` | ✅ covered |
| `trader_clear_all_data` / `trader_clear_all_errors` | ✅ covered |
| `traders_daily_report` | aggregate PnL/fee, отправка notification | ❌ missing |
| `optimizer_optimize(optimizer_id)` | `TraderOptimizer.optimize()` | ✅ covered |

---

### `arbitrage_traders.tasks`
| Task | Что тестируем | Статус |
|------|---------------|--------|
| `dispatch_arbitrage_traders_for_sources` | threshold 2 min на обе стороны → skip если одна отстала | ⚠ partial |
| `arbitrage_trader_process(trader_id)` | full cycle | ⚠ partial |
| `arbitrage_trader_reboot` | ✅ covered |
| `arbitrage_traders_daily_report` | ❌ missing |
| `arbitrage_optimizer_optimize` | ✅ covered |

---

### `candle_sources.tasks`
| Task | Статус |
|------|--------|
| `candle_source_sync_candles(source_id, since)` | ❌ missing |
| `candle_source_delete_candles(source_id, before)` | ⚠ partial |
| `candle_source_clear_all_data/errors(source_id)` | ⚠ partial |
| `candle_sources_fetch_last_candles()` — fanout REST/WS | ❌ missing |
| `candle_sources_fetch_last_candles_for_exchange(exchange_id)` | ❌ missing |
| `candle_sources_sync_from_redis(source_ids)` | ✅ covered |

**Критичный пробел:** `candle_sources_fetch_last_candles` — beat задача раз в 20 секунд, fanout по всем биржам. Тестов нет.

---

### `exchange_clients.tasks`
| Task | Статус |
|------|--------|
| `exchange_client_sync_order(order_id)` | ✅ covered |
| `exchange_client_sync_open_orders()` | ✅ covered |

---

### `exchanges.tasks`
| Task | Статус |
|------|--------|
| `exchange_sync_trading_pairs(exchange_id)` | ❌ missing |
| `exchanges_sync_all_trading_pairs()` | ❌ missing |

**Пробел:** ежедневная beat задача без тестов.

---

### `telegram_bots.tasks`
| Task | Статус |
|------|--------|
| `send_notification(message)` — активный бот, все чаты, retry | ⚠ partial |
| `async_send_notification` — TelegramRetryAfter handling | ❌ missing |

---

## 4. Приоритетный список «что добавить»

### P0 — критичные (hot path, legacy-защита):

1. **`exchanges.Exchange.sync_trading_pairs`** — ежедневная beat-задача, регулярно трогает БД + API бирж.
2. **`candle_sources_fetch_last_candles_for_exchange`** — главный beat-task (теперь каждые 20 сек).
3. **`exchange_client.create_market_order` через RPC** — вся цепочка торговли.
4. **`TradingPair.compute_cost` / `cost_to_amount` / `fit_amount`** — базовая математика, используется везде.
5. **`ArbitrageTrader.open_position` «left fail + right ok → rollback right»** — новая ветка после перехода на `asyncio.gather`, не покрыта unit-тестом.
6. **`aiter_sync_chunked`** — критическая утилита для backtest/optimize.

### P1 — важные:

7. `trader_process(trader_id)` — полный интеграционный flow (мок domain, проверка sync).
8. `dispatch_*_for_sources` — правильный fanout + filter по `ready_ids`.
9. `traders_daily_report` + `arbitrage_traders_daily_report` — агрегации PnL.
10. `CandleRedisCache` async — set/get/delete через fakeredis.
11. `ExchangeClient.fetch_balances / sync_balances / set_leverage / set_margin_mode`.

### P2 — полезные, не срочные:

12. Model `clean()` валидации для несуществующих сценариев.
13. Edge cases для `close_position` с partial fill.
14. `exchange_clients.tasks.exchange_client_sync_open_orders` — performance-bounds.

---

## 5. Общая статистика

| Приложение | Test-файлы | Test-классы | Test-методы | Оценка покрытия |
|-----------|-----------|-------------|-------------|------------------|
| `traders` | 12 | 86 | 378 | ✅ хорошо |
| `arbitrage_traders` | 13 | 104 | 309 | ✅ хорошо |
| `exchange_clients` | 3 | 16 | 18 | ⚠ минимально |
| `candle_sources` | 3 | 5 | 18 | ⚠ минимально |
| `exchanges` | 1 | 3 | 6 | ❌ критически мало |
| `telegram_bots` | 1 | 1 | 4 | ⚠ минимально |
| `core` | 5 | 9 | 15 | ⚠ минимально |
| **Итого** | 38 | **224** | **748** | 50% threshold проходит |

**Coverage по категориям:**
- ORM-модели `traders`/`arbitrage_traders` — ~85%.
- Domain-логика `traders`/`arbitrage_traders` — ~80%.
- Celery tasks — ~40%.
- Infrastructure (exchanges/exchange_clients/candle_sources) — ~30%.

---

## 6. Рекомендации по развитию тестов

### Паттерны, которые стоит применять
1. **CaptureQueriesContext** для хот-путей (`sync`, `dispatch`, `trader_process`). Сейчас есть частично в `traders/tests/models/test_traders.py::TestTraderSync*QueryCount`. Расширить на arbitrage и tasks.
2. **pytest-asyncio** для ws-cache и domain. Уже широко используется.
3. **Eager Celery** (`CELERY_TASK_ALWAYS_EAGER=True`) — есть. Но integration-тесты Celery-tasks почти отсутствуют, можно добавить мокая domain.
4. **fakeredis** для `CandleRedisCache`, `ArbitrageCandleCache` и `Bus`. Сейчас не используется.
5. **VCR / responses** для ccxt-вызовов. Сейчас ccxt обычно мокается вручную.

### Что не стоит тестировать
- Конкретные ccxt-клиенты (`binance.py`, `bybit.py`...) — внешняя зависимость, integration-тесты разумнее real-market'ом.
- `*/admin/__init__.py`, `*/charts/*.py` — уже excluded в `pyproject.toml` coverage.
- Миграции.

### Структурные улучшения

- **Вынести common fixtures** в `backend/conftest.py` для cross-app (сейчас есть `_mock_send_notification` autouse).
- **Разделить unit и integration** — тесты в `tests/integration/` (создают реальные цепочки: beat → task → model → domain).
- **Contract tests для RPC** — тестировать, что `fetch_balances` message и result совместимы между client и server (без реальной биржи).

---

*Документ сгенерирован автоматически на основе инвентаря кода и текущих тестов.*
