# Backend Project Structure - Trader

## Обзор проекта

Trader - это полнофункциональная торговая платформа для криптовалют на основе Django, включающая автоматизированную торговлю, оптимизацию стратегий, риск-менеджмент и мониторинг в режиме реального времени.

**Технологический стек:**

- Backend: Django 5.2, Celery 5.5
- БД: PostgreSQL + Redis
- Async: asyncio, aiogram, ccxt
- Анализ: pandas-ta, numpy
- Оптимизация: optuna, DEAP
- Визуализация: django-plotly-dash
- Тесты: pytest, pytest-django, pytest-asyncio

---

## 1. Django Приложения (Apps)

Проект содержит 8 основных Django приложений:

### 1.1. traders (Основное приложение трейдинга)

**Назначение:** Управление трейдерами, позициями, ордерами и сигналами

**Модели:**

- `Trader` - Основная модель трейдера с конфигурацией стратегии, риск-менеджера, баланса
  - **Источник свечей:** Использует `CandleSource` (может быть синтетическим из нескольких бирж)
  - Свойство `exchange_client_candle_source` - получает источник для конкретной биржи трейдера
- `TraderPosition` - Торговые позиции (LONG/SHORT) с метриками PnL, Risk/Reward
- `TraderOrder` - Связь с ордерами биржи
- `TraderSignal` - Торговые сигналы (BUY/SELL/WAIT)
  - Хранит множественные свечи через ManyToManyField для синтетических источников
- `ArbitrageTrader` - Арбитражные стратегии между биржами

**URL:**

- `/traders/trader/<id>/` - детальная страница трейдера

**Celery задачи:**

- `traders_process_for_exchange_client` - обработка свечей для трейдеров
- `trader_reboot` - перезагрузка трейдера с историческими данными
- `traders_daily_report` - ежедневный отчет о прибылях

**Charts:**

- equity_curve - график капитала
- accuracy_chart - точность прогнозов
- position_signal_chart - визуализация сигналов и позиций

### 1.2. exchange_clients (Клиенты бирж)

**Назначение:** Интеграция с криптобиржами через CCXT

**Модели:**

- `ExchangeClient` - API ключи для доступа к бирже (с поддержкой demo режима)
- `ExchangeClientProxy` - Прокси серверы для подключения
- `ExchangeClientBalance` - Балансы валют на счете
- `ExchangeClientOrder` - История ордеров с биржи
- `ExchangeClientCandleSource` - Источники свечей от биржи

**Celery задачи:**

- `sources_fetch_last_candles` - получение последних свечей (каждую минуту)
- `exchange_clients_fetch_balances` - обновление балансов (каждый час)
- `exchange_client_candle_source_sync_candles` - синхронизация исторических свечей

### 1.3. exchanges (Биржи и торговые пары)

**Назначение:** Управление биржами, торговыми парами и свечами

**Модели:**

- `Exchange` - Биржи (Binance, ByBit и т.д.)
- `TradingPair` - Торговые пары (BTC/USDT)
- `ExchangeTradingPair` - Специфичные настройки пары для биржи
- `ExchangeCandle` - Свечи OHLCV с различными таймфреймами
- `Candle` - Абстрактная базовая модель свечи

### 1.4. strategies (Торговые стратегии)

**Назначение:** Реализация торговых стратегий

**Модели:**

- `Strategy` - Конфигурация стратегии с JSON параметрами

**Domain стратегии:**

- `RenkoStrategy` - Стратегия на основе Renko кирпичей
- `MoneyFlowIndexStrategy` - На основе индикатора MFI
- `StochasticStrategy` - Стохастический осциллятор
- `DonchianCrossoverStrategy` - Прорывы каналов Дончиана

**Charts:**

- Визуализация работы стратегий с индикаторами

### 1.5. risk_managers (Риск-менеджмент)

**Назначение:** Управление рисками, расчет размеров позиций, SL/TP

**Модели:**

- `RiskManager` - Конфигурация риск-менеджера

**Domain менеджеры (8 комбинаций):**

Stop Loss миксины:

- `PercentStopLossMixin` - фиксированный процент от цены входа
- `ExtremumStopLossMixin` - по локальным экстремумам

Take Profit миксины:

- `PercentTakeProfitMixin` - фиксированный процент от цены входа
- `RiskRewardTakeProfitMixin` - на основе соотношения риск/прибыль

Position Size миксины:

- `AllInPositionSizeMixin` - весь доступный капитал
- `ByRiskPositionSizeMixin` - процент от капитала под риском

**Тесты:**

- Полное покрытие всех миксинов
- test_position_size_mixins.py
- test_stop_loss_mixins.py
- test_take_profit_mixins.py
- test_risk_managers.py

### 1.6. optimizers (Оптимизация параметров)

**Назначение:** Оптимизация параметров стратегий и риск-менеджеров

**Модели:**

- `TraderOptimizer` - Конфигурация оптимизации
- `TraderOptimizationAlgorithm` - Алгоритмы (Optuna, DEAP и т.д.)
- `TraderOptimizationResult` - Результаты с метриками (ROI, Sharpe, R², Win Rate)

**Celery задачи:**

- `optimizer_optimize` - запуск оптимизации
- `optimize_old_optimizers` - переоптимизация старых результатов (каждые 30 мин)

**Метрики:**

- ROI (Return on Investment)
- Sharpe Ratio
- R² (коэффициент детерминации)
- Win Rate (процент прибыльных сделок)
- Комбинированная оценка с весами

### 1.7. telegram_bots (Telegram уведомления)

**Назначение:** Отправка уведомлений о торговых событиях

**Модели:**

- `TelegramBot` - Боты с токенами
- `TelegramChat` - Чаты для уведомлений

**Celery задачи:**

- `send_notification` - асинхронная отправка сообщений через aiogram

### 1.8. candle_sources (Источники свечей)

**Назначение:** Агрегация свечей из разных источников для создания синтетических свечей

**Модели:**

- `CandleSource` - Композитные источники свечей
  - Связь ManyToMany с `ExchangeClientCandleSource`
  - Поддержка до 2 источников одновременно
  - Валидация: все источники должны иметь одинаковый таймфрейм и торговую пару
  - Валидация: источники должны быть с разных бирж (для арбитража)
  - Свойства: `timeframe`, `trading_pair`, `exchange_client` (из первого источника)

**Domain источники:**

- `PlainCandleSource` - простой источник от одной биржи (прямая передача свечей)
- `DivisionCandleSource` - деление свечей для арбитража (цена1/цена2)
  - Используется для торговли спредами между биржами
  - Создает синтетическую свечу путем деления OHLCV значений

**Методы:**

- `get_candle_iterator()` - генератор свечей для бэктеста
- `get_candles()` - список свечей за период
- `get_last_candles(count)` - последние N свечей (для Celery задач)
- `instantiate()` - конвертация в domain объект

---

## 2. Core модуль

### 2.1. Настройки (core/settings.py)

**Основные настройки:**

- Django 5.1.3
- PostgreSQL база данных
- Redis для Celery и кеширования
- Channels для WebSockets
- django-plotly-dash для интерактивных дашбордов
- Timezone: Europe/Moscow
- Loguru для логирования

### 2.2. Celery (core/celery.py)

**Beat расписание:**

```python
# Каждую минуту
sources_fetch_last_candles → получение свечей с бирж

# Каждый час (в :00)
exchange_clients_fetch_balances → обновление балансов счетов

# Ежедневно в 10:00
traders_daily_report → отчет о прибылях всех трейдеров

# Каждые 30 минут (в :30)
optimize_old_optimizers → переоптимизация устаревших результатов
```

**Очереди задач:**

- `traders_process_for_exchange_client`
- `trader_reboot`
- `optimizer_optimize`
- `sources_fetch_last_candles_for_exchange_client`

### 2.3. Утилиты (core/utils/)

**Модули:**

- `types.py` - Enums для статусов и типов

  - OrderSide (BUY, SELL)
  - SignalType (BUY, SELL, WAIT)
  - TraderStatus (ACTIVE, INACTIVE, ERROR)
  - PositionStatus (OPEN, CLOSED)
  - TimeFrame (1m, 5m, 15m, 1h, 4h, 1d)
- `mixins.py` - Базовые миксины для моделей

  - ActiveManager - менеджер для is_active
  - TimeStampedMixin - created_at, updated_at
- `common.py` - Вспомогательные функции

  - get_all_init_args - рефлексия для __init__
  - dt_str - форматирование дат
- `registry.py` - Паттерн Registry

  - Автоматическая регистрация стратегий
  - Автоматическая регистрация риск-менеджеров

---

## 3. Domain-слой (Бизнес-логика)

Архитектура основана на DDD (Domain-Driven Design) с разделением ORM моделей и бизнес-логики.

**Важное обновление архитектуры:**

- `Trader` теперь использует `CandleSource` вместо прямого `ExchangeClientCandleSource`
- Это позволяет трейдеру работать с синтетическими свечами из нескольких источников
- Поддержка Plain (простые свечи) и Division (арбитражные) источников
- Трейдер автоматически получает нужный источник через свойство `exchange_client_candle_source`

**Типы свечей в Domain-слое:**

- `Candle` - базовый класс свечи (OHLCV данные)
- `ExchangeCandle(Candle)` - свеча с биржи (имеет `id`)
- `SyntheticCandle(Candle)` - синтетическая свеча с **обязательным** полем `source_candles: List[ExchangeCandle]`

**Процесс синхронизации (sync) Domain → ORM:**

1. **Domain-слой** работает с `SyntheticCandle` (всегда содержит `source_candles`)
   - `PlainCandleSource.get_candle()` → `SyntheticCandle` с 1 свечой в `source_candles`
   - `DivisionCandleSource.get_candle()` → `SyntheticCandle` с 2 свечами в `source_candles`
2. **Метод `sync_signals()`** сохраняет новые сигналы в БД:
   - Создает `TraderSignal` через `bulk_create()`
   - Извлекает ID исходных `ExchangeCandle` из `domain_signal.candle.source_candles`
   - Устанавливает ManyToMany связь через `db_signal.candles.set(source_candle_ids)`
3. **Метод `load()`** восстанавливает domain-объекты из БД:
   - Загружает `TraderSignal.candles` (ManyToMany)
   - В `TraderSignal.instantiate()` вызывает `candle_source.get_candle(*exchange_candles)`
   - Получает `SyntheticCandle` с заполненным `source_candles`

### 3.1. traders/domain/

**Основные файлы:**

- `traders.py` - Основная бизнес-логика трейдера

  - Обработка новых свечей
  - Управление позициями (открытие/закрытие)
  - Синхронизация с биржей
  - Проверка просадки (drawdown)
  - Trail stop механизм
- `schemas.py` - Pydantic модели для валидации данных

**Ключевые методы:**

```python
Trader.process_candle(candle) → Signal
Trader.manage_position(position, candle) → bool
Trader.sync_with_exchange() → None
Trader.check_drawdown() → bool
```

### 3.2. strategies/domain/

**Структура:**

- `base.py` - AbstractStrategy с Registry паттерном
- `strategies.py` - Реализации всех стратегий
- `schemas.py` - Pydantic схемы
  - TraderSignal
  - RenkoBrick
  - MFIState
  - StochasticState

**Параметры:**

- `PARAM_CONSTRAINTS` - ограничения для оптимизации
- Каждая стратегия определяет свои параметры

**Реализованные стратегии:**

1. **RenkoStrategy**

   - Параметры: brick_size
   - Торговля по Renko кирпичам
2. **MoneyFlowIndexStrategy**

   - Параметры: period, overbought, oversold
   - Индикатор MFI (Money Flow Index)
3. **StochasticStrategy**

   - Параметры: k_period, d_period, overbought, oversold
   - Стохастический осциллятор
4. **DonchianCrossoverStrategy**

   - Параметры: period
   - Прорывы каналов Дончиана

### 3.3. risk_managers/domain/

**Структура:**

- `base.py` - AbstractRiskManager с Registry
- `risk_managers.py` - 8 комбинаций менеджеров
- Модульная система через миксины

**Миксины:**

Stop Loss:

- `PercentStopLossMixin` - процент от entry_price
- `ExtremumStopLossMixin` - по локальным экстремумам

Take Profit:

- `PercentTakeProfitMixin` - процент от entry_price
- `RiskRewardTakeProfitMixin` - соотношение risk/reward

Position Size:

- `AllInPositionSizeMixin` - весь баланс
- `ByRiskPositionSizeMixin` - процент капитала под риском

**Комбинации (8 классов):**

```python
PercentSLPercentTPAllInRiskManager
PercentSLPercentTPByRiskRiskManager
PercentSLRiskRewardTPAllInRiskManager
PercentSLRiskRewardTPByRiskRiskManager
ExtremumSLPercentTPAllInRiskManager
ExtremumSLPercentTPByRiskRiskManager
ExtremumSLRiskRewardTPAllInRiskManager
ExtremumSLRiskRewardTPByRiskRiskManager
```

### 3.4. exchange_clients/domain/

**Структура:**

- `base.py` - AbstractExchangeClient
- `exchange_clients.py` - Реализация для конкретных бирж
  - ByBitExchangeClient (через CCXT)
- `exchange_candle_sources.py` - Получение свечей
- `proxies.py` - Поддержка SOCKS5/SOCKS4

**Async методы:**

```python
async fetch_balance() → dict
async create_order(symbol, type, side, amount, price) → Order
async fetch_order(order_id) → Order
async cancel_order(order_id) → bool
async fetch_ohlcv(symbol, timeframe, since, limit) → list[Candle]
```

**Особенности:**

- Все операции асинхронные (asyncio)
- Поддержка demo режима (testnet)
- Автоматическое переподключение через прокси
- Rate limiting для API запросов

### 3.5. optimizers/domain/

**Структура:**

- `optimizers.py` - TraderOptimizer для бэктестинга
- `base.py` - AbstractOptimizationAlgorithm

**Процесс оптимизации:**

1. Загрузка исторических свечей
2. Генерация комбинаций параметров
3. Бэктест для каждой комбинации
4. Расчет метрик (ROI, Sharpe, R², Win Rate)
5. Комбинированная оценка с весами
6. Сохранение лучших результатов

**Алгоритмы:**

- Grid Search
- Random Search
- Optuna (Bayesian optimization)
- DEAP (Genetic algorithms)

### 3.6. candle_sources/domain/

**Структура:**

- `base.py` - AbstractCandleSource
- `candle_sources.py` - Реализации источников

**Типы источников:**

1. **PlainCandleSource**

   - Простой источник от одной биржи
   - Прямое получение свечей
2. **DivisionCandleSource**

   - Арбитраж между двумя биржами
   - Делит цены одного источника на другой
   - Используется для парной торговли

---

## 4. API и Views

### 4.1. URL структура

```python
/admin/                      # Django Admin (основной интерфейс)
/django_plotly_dash/         # Интерактивные графики
/traders/trader/<pk>/        # Детальная страница трейдера
/                           # Редирект на admin
```

### 4.2. Views

**Class-Based Views:**

- `TraderDetailView` - детальная информация о трейдере
  - График equity curve
  - Список позиций
  - История сигналов
  - Метрики производительности

**Остальное управление:**

- Через Django Admin панели
- Plotly Dash дашборды для визуализации

### 4.3. Admin панели

**Расширенный функционал для всех приложений:**

**Traders Admin:**

- Массовые действия: enable/disable/reboot
- Экспорт в Excel
- Метрики в списке (ROI, PnL, Win Rate)
- Фильтры по статусу, стратегии, бирже

**Positions Admin:**

- Фильтры по статусу (OPEN/CLOSED)
- Фильтры по типу (LONG/SHORT)
- Фильтры по датам
- Инлайн-редактирование ордеров

**Orders Admin:**

- Поиск по exchange_order_id
- Связь с позициями
- История изменений

**Strategies/RiskManagers Admin:**

- JSON редактор для параметров
- Валидация параметров
- Preview результатов

**Optimizers Admin:**

- Просмотр результатов оптимизации
- Сравнение метрик
- Применение лучших параметров

---

## 5. Celery задачи

### 5.1. Периодические задачи (Celery Beat)

**Каждую минуту:**

```python
@app.task
def sources_fetch_last_candles():
    """Получение последних свечей со всех активных источников"""
    - Для каждого ExchangeClientCandleSource
    - Получает новые свечи через CCXT
    - Сохраняет в ExchangeCandle
    - Запускает обработку трейдерами
```

**Каждый час (в :00):**

```python
@app.task
def exchange_clients_fetch_balances():
    """Обновление балансов всех активных клиентов"""
    - Для каждого ExchangeClient
    - Получает текущие балансы
    - Обновляет ExchangeClientBalance
    - Синхронизирует с Trader.balance
```

**Ежедневно в 10:00:**

```python
@app.task
def traders_daily_report():
    """Ежедневный отчет о прибылях всех трейдеров"""
    - Собирает статистику за день
    - Отправляет в Telegram
    - Сохраняет в историю
```

**Каждые 30 минут (в :30):**

```python
@app.task
def optimize_old_optimizers():
    """Переоптимизация устаревших результатов"""
    - Находит оптимизаторы старше 7 дней
    - Запускает повторную оптимизацию
    - Обновляет параметры трейдеров
```

### 5.2. Асинхронные задачи

**Обработка свечей:**

```python
@app.task
def traders_process_for_exchange_client(exchange_client_id, candle_data):
    """Обработка новой свечи группой трейдеров"""
    - Находит всех активных трейдеров для данного клиента
    - Для каждого трейдера:
      * Запускает strategy.process_candle()
      * Управляет позициями
      * Синхронизирует с биржей
      * Отправляет уведомления
```

**Перезагрузка трейдера:**

```python
@app.task
def trader_reboot(trader_id):
    """Полная перезагрузка трейдера с историческими данными"""
    - Загружает свечи за последний год
    - Закрывает все открытые позиции
    - Сбрасывает состояние стратегии
    - Запускает заново с первой свечи
    - Отправляет отчет в Telegram
```

**Оптимизация:**

```python
@app.task(time_limit=3600)
def optimizer_optimize(optimizer_id):
    """Запуск оптимизации параметров (долгая задача)"""
    - Загружает исторические данные
    - Генерирует комбинации параметров
    - Запускает бэктест для каждой
    - Сохраняет результаты
    - Применяет лучшие параметры
```

**Telegram уведомления:**

```python
@app.task
def send_notification(bot_id, chat_id, message):
    """Асинхронная отправка сообщения в Telegram"""
    - Через aiogram
    - Форматирование Markdown
    - Обработка ошибок
```

---

## 6. Тесты

### 6.1. Структура тестов

**Приложения:**

```
traders/tests/
├── conftest.py                    # Фикстуры для трейдеров
├── test_models.py                 # Тесты ORM моделей
└── test_tasks_celery.py          # Тесты Celery задач

risk_managers/domain/tests/
├── __init__.py
├── test_risk_managers.py         # Тесты риск-менеджеров
├── test_stop_loss_mixins.py      # Тесты SL миксинов
├── test_take_profit_mixins.py    # Тесты TP миксинов
└── test_position_size_mixins.py  # Тесты позиции миксинов

traders/domain/
├── test_traders.py               # Тесты domain логики
└── test_trader.py                # Интеграционные тесты

strategies/domain/
└── test_strategies.py            # Тесты всех стратегий

exchange_clients/domain/
└── test_exchange_candles.py      # Тесты получения свечей

optimizers/domain/
└── test_optimizers.py            # Тесты оптимизации
```

### 6.2. Конфигурация pytest

**pyproject.toml:**

```toml
[tool.pytest.ini_options]
DJANGO_SETTINGS_MODULE = "core.settings"
python_files = ["test_*.py", "*_test.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
addopts = "-v --tb=short --strict-markers"
markers = [
    "slow: marks tests as slow",
    "integration: marks tests as integration tests",
]
```

**Основные зависимости:**

- pytest-django - интеграция с Django
- pytest-asyncio - тестирование async кода
- pytest-cov - покрытие кода
- pytest-mock - моки и патчинг

### 6.3. Примеры тестов

**Тесты domain-логики:**

```python
def test_renko_strategy_generates_buy_signal():
    """Тест генерации BUY сигнала Renko стратегией"""
    strategy = RenkoStrategy(brick_size=100)
    candles = generate_uptrend_candles()
    signal = strategy.process_candle(candles[-1])
    assert signal.type == SignalType.BUY

def test_risk_manager_calculates_position_size():
    """Тест расчета размера позиции риск-менеджером"""
    manager = ByRiskPositionSizeMixin(risk_percent=2.0)
    size = manager.calculate_position_size(
        balance=10000,
        entry_price=50000,
        stop_loss=49000
    )
    assert size == 2.0  # 2% риска
```

**Интеграционные тесты:**

```python
@pytest.mark.django_db
async def test_trader_processes_candle_and_opens_position():
    """Интеграционный тест обработки свечи"""
    trader = await create_trader()
    candle = await create_candle()

    await trader.process_candle(candle)

    positions = await TraderPosition.objects.filter(trader=trader)
    assert positions.count() == 1
    assert positions.first().status == PositionStatus.OPEN
```

---

## 7. Зависимости между модулями

### 7.1. Граф зависимостей

```
core (utils, types, settings)
  ↓
exchanges (Exchange, TradingPair, Candle models)
  ↓
exchange_clients (API integration, Orders, Balances)
  ↓
candle_sources (Aggregation from multiple exchanges)
  ↓
strategies + risk_managers (Domain logic, Independent)
  ↓
traders (Integration layer, Main business logic)
  ↑
optimizers (Parameter optimization for traders)
  ↑
telegram_bots (Notifications about trading events)
```

### 7.2. Ключевые паттерны

**1. Registry Pattern**

```python
# Автоматическая регистрация стратегий
class AbstractStrategy(metaclass=RegistryMeta):
    registry = {}

    @classmethod
    def get_strategy(cls, name: str) -> 'AbstractStrategy':
        return cls.registry[name]

# Регистрация происходит автоматически при определении класса
class RenkoStrategy(AbstractStrategy):
    name = "Renko"
```

**2. Domain-Driven Design**

```python
# ORM модель (инфраструктура)
class Trader(models.Model):
    name = models.CharField(max_length=100)
    balance = models.DecimalField()

    def instantiate(self) -> DomainTrader:
        """Конвертация ORM → Domain"""
        return DomainTrader(
            id=self.id,
            name=self.name,
            balance=float(self.balance)
        )

# Domain модель (бизнес-логика)
class DomainTrader:
    def process_candle(self, candle: Candle) -> Signal:
        """Чистая бизнес-логика без зависимости от ORM"""
        return self.strategy.generate_signal(candle)

    def sync(self) -> None:
        """Сохранение domain → ORM"""
        Trader.objects.filter(id=self.id).update(
            balance=self.balance
        )
```

**3. Active Record + Domain Model (гибридный подход)**

- ORM модели для персистентности (Django models)
- Domain модели для бизнес-логики (dataclasses/Pydantic)
- `instantiate()` для конвертации ORM → Domain
- `sync()` для сохранения Domain → ORM

**4. Async/Await**

```python
# Все операции с биржей асинхронные
async def create_order(self, symbol, side, amount, price):
    async with self.exchange_client:
        order = await self.exchange_client.create_order(
            symbol=symbol,
            side=side,
            amount=amount,
            price=price
        )
    return order
```

**5. Bulk Operations**

```python
# Массовые вставки для производительности
candles = [
    ExchangeCandle(timestamp=ts, open=o, high=h, low=l, close=c)
    for ts, o, h, l, c in ohlcv_data
]
ExchangeCandle.objects.bulk_create(candles, ignore_conflicts=True)
```

---

## 8. Ключевые особенности архитектуры

### 8.1. Преимущества

**Разделение ответственности (SRP):**

- Каждое приложение отвечает за свою область
- Domain-логика отделена от ORM
- Бизнес-правила независимы от инфраструктуры

**Расширяемость:**

- Registry паттерн для добавления новых стратегий
- Миксины для комбинирования риск-менеджеров
- Легкое добавление новых бирж

**Производительность:**

- Async операции с биржей
- Bulk операции с БД
- Celery для фоновых задач
- Redis кеширование

**Тестируемость:**

- Domain-логика легко тестируется
- Моки для external API
- Pytest фикстуры для данных

### 8.2. Особенности реализации

**Конвертация ORM ↔ Domain:**

```python
# ORM → Domain
trader_domain = trader_orm.instantiate()

# Domain → ORM
trader_orm.sync(trader=trader_domain)
```

**Поддержка demo режима:**

```python
exchange_client = ExchangeClient(
    exchange=bybit,
    is_demo=True  # Использует testnet
)
```

**Trail stop механизм:**

```python
if current_profit > best_profit:
    position.best_profit = current_profit
    position.trail_stop = entry_price * (1 + best_profit * 0.5)
```

**Множественные позиции:**

```python
# Трейдер может иметь несколько открытых позиций одновременно
positions = Position.objects.filter(
    trader=trader,
    status=PositionStatus.OPEN
)
```

**Просадка и риск-менеджмент:**

```python
if trader.current_balance < trader.initial_balance * (1 - max_drawdown):
    trader.status = TraderStatus.STOPPED
    trader.close_all_positions()
```

**Telegram уведомления:**

```python
# Автоматические уведомления о событиях
- Открытие позиции
- Закрытие позиции
- Достижение целевой прибыли
- Срабатывание стоп-лосса
- Ошибки выполнения
```

### 8.3. Технологический стек

**Backend Framework:**

- Django 5.2 - основной фреймворк
- Django REST Framework - API (если используется)
- Channels - WebSockets для real-time обновлений

**Асинхронность:**

- Celery 5.5 - очереди задач
- Redis - брокер для Celery + кеш
- asyncio - асинхронные операции
- aiogram - Telegram bot framework

**База данных:**

- PostgreSQL - основная БД
- Redis - кеш и очереди

**Торговля:**

- ccxt - унифицированный API для бирж
- pandas-ta - технические индикаторы
- numpy - вычисления

**Оптимизация:**

- optuna - Bayesian optimization
- DEAP - генетические алгоритмы
- scipy - статистика

**Визуализация:**

- django-plotly-dash - интерактивные графики
- plotly - построение графиков

**Тестирование:**

- pytest - тестовый фреймворк
- pytest-django - Django интеграция
- pytest-asyncio - async тесты
- pytest-cov - покрытие кода
- pytest-mock - моки

**Утилиты:**

- pydantic - валидация данных
- loguru - логирование
- python-dotenv - переменные окружения

---

## 9. Статистика проекта

**Файловая структура:**

- Всего Python файлов: ~133
- Domain-слой: 38 файлов
- Django приложений: 8
- ORM моделей: ~25
- Celery задач: 8
- Admin панелей: 8
- URL маршрутов: 3
- Тестовых файлов: ~17

**Бизнес-логика:**

- Стратегий: 4 (расширяемо)
- Риск-менеджеров: 8 комбинаций
- Поддерживаемых бирж: 2+ (Binance, ByBit)
- Типов источников свечей: 2 (Plain, Division)

**Покрытие тестами:**

- Domain-логика: высокое покрытие
- Риск-менеджеры: 100% миксины
- Стратегии: основные сценарии
- Интеграционные: ключевые потоки

---

## 10. Рекомендации по развитию

### Что можно улучшить:

**Тестирование:**

- Добавить больше интеграционных тестов
- E2E тесты для критических потоков
- Нагрузочное тестирование

**Мониторинг:**

- Prometheus метрики
- Grafana дашборды
- Алерты на критические события

**Документация:**

- API документация (Swagger/OpenAPI)
- Диаграммы архитектуры
- Руководство по добавлению стратегий

**Безопасность:**

- Шифрование API ключей
- Rate limiting для API
- Audit log для всех операций

**Производительность:**

- Оптимизация SQL запросов
- Кеширование частых запросов
- Профилирование узких мест

---

## Заключение

Trader представляет собой профессиональную торговую платформу с:

- Четкой архитектурой на основе DDD
- Модульной структурой с возможностью расширения
- Автоматизацией через Celery
- Оптимизацией параметров
- Real-time обработкой данных
- Полным риск-менеджментом
- Мониторингом и уведомлениями

Проект готов к продакшену и может масштабироваться под различные торговые стратегии и биржи.
