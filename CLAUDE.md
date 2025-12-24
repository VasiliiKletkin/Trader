# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Trader is a cryptocurrency trading platform built with Django 5.2, featuring automated trading, strategy optimization, risk management, and real-time monitoring. The backend is in Russian with extensive technical documentation in [backend/BACKEND_STRUCTURE.md](backend/BACKEND_STRUCTURE.md).

**Tech Stack:**
- Backend: Django 5.2, Celery 5.5
- Database: PostgreSQL + Redis
- Async: asyncio, aiogram, ccxt
- Analysis: pandas-ta, numpy
- Optimization: optuna, DEAP
- Visualization: django-plotly-dash
- Tests: pytest, pytest-django, pytest-asyncio

## Environment Setup

**IMPORTANT: Before running any commands, activate the Poetry virtual environment:**

```bash
cd backend
poetry shell
```

All subsequent commands should be run inside the Poetry shell. If you get "command not found" errors, make sure you've activated the Poetry environment first.

Alternative (run single command without activating shell):

```bash
cd backend
poetry run <command>
```

## Development Commands

### Running Tests

**Note:** Make sure you're in the Poetry shell (`cd backend && poetry shell`) before running tests.

```bash
# Run all tests from backend directory
cd backend
poetry shell  # Activate environment first
pytest

# Run specific test file
pytest traders/tests/test_models.py

# Run specific test function
pytest traders/domain/test_traders.py::test_trader_processes_candle

# Run with coverage
pytest --cov=. --cov-report=html

# Run only domain tests
pytest */domain/test_*.py

# Alternative: Run without activating shell
poetry run pytest traders/tests/test_models.py
```

### Django Management

```bash
cd backend

# Run development server
python manage.py runserver

# Create/apply migrations
python manage.py makemigrations
python manage.py migrate

# Django shell
python manage.py shell

# Create superuser
python manage.py createsuperuser

# Collect static files
python manage.py collectstatic
```

### Docker Commands

```bash
# Start all services (from project root)
docker-compose up

# Build and start
docker-compose up --build

# Run migrations in Docker
make dmigr

# Create superuser in Docker
make duser

# Django shell in Docker
make dshell

# Database operations
make dcreatedb    # Create database
make ddeletedb    # Drop database
make dcreatedump  # Create database dump
make dloaddump    # Load database dump
```

### Celery

```bash
cd backend

# Start Celery worker
celery -A core worker -l INFO

# Start Celery beat (scheduled tasks)
celery -A core beat -l INFO

# Start Flower (monitoring at http://localhost:5555)
celery -A core flower --url_prefix=flower

# Start specific queue worker
celery -A core worker -l INFO -Q traders_process_for_exchange_client
```

## Architecture Overview

### Domain-Driven Design (DDD) Pattern

The project uses a **hybrid approach** with ORM models for persistence and Domain models for business logic:

1. **ORM Models** (Django models) - Infrastructure layer for data persistence
2. **Domain Models** (dataclasses/Pydantic) - Business logic layer, completely independent of Django ORM
3. **Conversion Methods**:
   - `model.instantiate()` - Converts ORM → Domain
   - `domain_obj.sync()` - Saves Domain → ORM

**Example:**
```python
# ORM model (traders/models.py)
class Trader(models.Model):
    name = models.CharField(max_length=100)
    balance = models.DecimalField()

    def instantiate(self) -> DomainTrader:
        """Convert to domain model"""
        return DomainTrader(id=self.id, name=self.name, balance=float(self.balance))

# Domain model (traders/domain/traders.py)
class DomainTrader:
    def process_candle(self, candle: Candle) -> Signal:
        """Pure business logic, no ORM dependencies"""
        return self.strategy.generate_signal(candle)

    def sync(self) -> None:
        """Save back to ORM"""
        Trader.objects.filter(id=self.id).update(balance=self.balance)
```

### Registry Pattern for Extensibility

Strategies and risk managers use automatic registration via metaclass:

```python
# strategies/domain/base.py
class AbstractStrategy(ABC, metaclass=RegistryMeta):
    registry = {}

    # Subclasses are automatically registered when defined
    @classmethod
    def get_strategy(cls, name: str) -> 'AbstractStrategy':
        return cls.registry[name]
```

To add a new strategy:
1. Inherit from `AbstractStrategy`
2. Implement `get_signal()` and `position_should_be_closed()`
3. Define `PARAM_CONSTRAINTS` for optimization
4. The strategy is automatically registered in the registry

### Candle Architecture (Important!)

The project distinguishes between **exchange candles** and **synthetic candles**:

- **`ExchangeCandle`** - Direct candles from exchange APIs (has `id` field)
- **`ProviderCandle`** - Aggregated/computed candles with **required** `source_candles: List[ExchangeCandle]` field

**Candle Source Types:**
1. **`PlainCandleSource`** - Single exchange source, creates `ProviderCandle` with 1 source candle
2. **`DivisionCandleSource`** - Arbitrage between two exchanges, divides OHLCV values, creates `ProviderCandle` with 2 source candles

**Critical sync flow:**
- Domain layer always works with `ProviderCandle` containing `source_candles`
- `sync_signals()` saves signals to DB and establishes ManyToMany relation via `TraderSignal.candles.set(source_candle_ids)`
- `load()` reconstructs domain objects by calling `candle_source.get_candle(*exchange_candles)` to rebuild `ProviderCandle` with `source_candles`

### Django Apps Structure

The project has 8 main Django apps with clear separation of concerns:

1. **exchanges** - Exchange/TradingPair/Candle models (foundation layer)
2. **exchange_clients** - CCXT integration, API operations, order/balance management
3. **candle_sources** - Aggregation layer for creating synthetic candles from multiple exchanges
4. **strategies** - Trading strategy implementations (4 strategies: Renko, MFI, Stochastic, Donchian)
5. **risk_managers** - 8 risk manager combinations using mixins (SL × TP × Position Size)
6. **traders** - Main business logic, integrates strategies and risk managers
7. **optimizers** - Parameter optimization using Optuna/DEAP with metrics (ROI, Sharpe, R², Win Rate)
8. **telegram_bots** - Async notifications via aiogram

**Dependency flow:**
```
core (utils, types)
  → exchanges
  → exchange_clients
  → candle_sources
  → strategies + risk_managers (independent)
  → traders
  → optimizers + telegram_bots
```

### Celery Task Queues

The system uses dedicated queues for different task types:

**Beat Schedule (Periodic Tasks):**
- Every minute: `sources_fetch_last_candles` - Fetch latest candles from all active sources
- Every hour (XX:00): `exchange_clients_fetch_balances` - Update account balances
- Daily at 10:00: `traders_daily_report` - Send Telegram reports
- Every 30 minutes (XX:30): `optimize_old_optimizers` - Re-optimize stale optimizers (>7 days)

**Task Queues:**
- `sources_fetch_last_candles_for_exchange_client` - High-frequency candle fetching
- `traders_process_for_exchange_client` - Process candles and manage positions
- `trader_reboot` - Full trader reset with historical data
- `optimizer_optimize` - Long-running optimization tasks (up to 1 hour)

**Worker scaling in docker-compose.yml:** `--autoscale=5,1` for candle and trader processing queues.

### Async Operations

All exchange operations are async (asyncio + CCXT):

```python
# exchange_clients/domain/exchange_clients.py
async def create_order(self, symbol, side, amount, price):
    async with self.exchange_client:
        order = await self.exchange_client.create_order(...)
    return order
```

**Key async components:**
- Exchange API calls (ccxt)
- Telegram notifications (aiogram)
- Database operations use Django ORM (sync), wrapped in `sync_to_async` when needed

### Risk Manager Mixins

Risk managers are composed from 3 types of mixins:

**Stop Loss (2 options):**
- `PercentStopLossMixin` - Fixed percentage from entry price
- `ExtremumStopLossMixin` - Based on local extremums

**Take Profit (2 options):**
- `PercentTakeProfitMixin` - Fixed percentage from entry price
- `RiskRewardTakeProfitMixin` - Based on risk/reward ratio

**Position Size (2 options):**
- `AllInPositionSizeMixin` - All available capital
- `ByRiskPositionSizeMixin` - Percentage of capital at risk

This creates **8 total combinations** (2 × 2 × 2), all following the naming pattern: `{SL}{TP}{Size}RiskManager`

Example: `PercentSLRiskRewardTPByRiskRiskManager`

## Important Patterns and Conventions

### 1. Always Use Domain Layer for Business Logic

Never put trading logic directly in ORM models or views. Flow should be:
```
View/Task → ORM Model → instantiate() → Domain Model → Business Logic → sync() → ORM Model
```

### 2. Bulk Operations for Performance

Use Django's bulk operations when dealing with multiple candles or signals:

```python
ExchangeCandle.objects.bulk_create(candles, ignore_conflicts=True)
TraderSignal.objects.bulk_create(signals)
```

### 3. ManyToMany for Synthetic Candles

`TraderSignal.candles` is a ManyToManyField to `ExchangeCandle` because synthetic candles can be composed from multiple source candles (for arbitrage).

### 4. Test Organization

- Domain tests: `app/domain/test_*.py` - Test business logic independently
- ORM tests: `app/tests/test_models.py` - Test Django models
- Integration tests: `app/tests/test_*.py` - Test full flows
- Use pytest fixtures from `conftest.py` for test data

### 5. Demo Mode Support

`ExchangeClient.is_demo=True` uses exchange testnet APIs. Always test strategies in demo mode before production.

### 6. Trail Stop Mechanism

Positions track `best_profit` and automatically adjust `trail_stop` to lock in profits:

```python
if current_profit > position.best_profit:
    position.best_profit = current_profit
    position.trail_stop = entry_price * (1 + best_profit * 0.5)
```

### 7. Trader uses CandleSource (Not Direct Exchange Source)

The `Trader` model references `CandleSource` which can aggregate multiple `CandleSource` instances. This enables:
- Plain sources (single exchange)
- Division sources (arbitrage between exchanges)
- Future: other synthetic candle types

Access the exchange-specific source via: `trader.candle_source.exchange_client_candle_source`

## Project Configuration

### Environment Variables

Key variables in `.env`:
- `DEBUG` - Django debug mode
- `SECRET_KEY` - Django secret key
- `POSTGRES_*` - Database connection
- `REDIS_*` - Redis connection
- `DJANGO_ALLOWED_HOSTS` - Allowed hosts
- `CSRF_TRUSTED_ORIGINS` - CSRF origins

### Settings Location

- Main settings: [backend/core/settings.py](backend/core/settings.py)
- Celery config: [backend/core/celery.py](backend/core/celery.py)
- Pytest config: [backend/pyproject.toml](backend/pyproject.toml)

### Timezone

The project uses `Europe/Moscow` timezone by default.

## Working with Strategies

To add a new strategy:

1. Create class in `strategies/domain/strategies.py`:
```python
class MyNewStrategy(AbstractStrategy):
    PARAM_CONSTRAINTS = {
        'my_param': (10, 100),  # (min, max) for optimization
    }

    def __init__(self, my_param: int):
        self.my_param = my_param

    def get_signal(self, trader: Trader, candle: Candle) -> TraderSignal:
        # Implement signal generation logic
        # Return TraderSignal with type BUY/SELL/WAIT
        pass

    def position_should_be_closed(self, signal: TraderSignal, position: TraderPosition) -> bool:
        # Implement position closing logic
        pass
```

2. Strategy is automatically registered via `__init_subclass__`
3. Add Pydantic schema in `strategies/domain/schemas.py` if needed for state
4. Write tests in `strategies/domain/test_strategies.py`
5. Create Strategy model instance via Django admin with JSON parameters

## Key Files Reference

- Architecture documentation: [backend/BACKEND_STRUCTURE.md](backend/BACKEND_STRUCTURE.md) (comprehensive, in Russian)
- Main trader logic: [backend/traders/domain/traders.py](backend/traders/domain/traders.py)
- Strategy base: [backend/strategies/domain/base.py](backend/strategies/domain/base.py)
- Risk manager base: [backend/risk_managers/domain/base.py](backend/risk_managers/domain/base.py)
- Candle source base: [backend/candle_sources/domain/base.py](backend/candle_sources/domain/base.py)
- Exchange client base: [backend/exchange_clients/domain/base.py](backend/exchange_clients/domain/base.py)
- Celery tasks: `backend/*/tasks.py` in each app
