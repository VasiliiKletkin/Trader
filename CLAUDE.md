# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Trader is a cryptocurrency trading platform built with Django 5.2, featuring automated trading, strategy optimization, risk management, and real-time monitoring. The backend is in Russian with extensive technical documentation in [backend/BACKEND_STRUCTURE.md](backend/BACKEND_STRUCTURE.md).

**Tech Stack:**
- Backend: Django 5.2.6, Celery 5.5.3
- Database: PostgreSQL 14+ + Redis 6+
- Async: asyncio, aiogram 3.22+, ccxt 4.5+
- Analysis: pandas-ta 0.4.67b0, numpy, pandas
- Optimization: optuna 4.6+, DEAP 1.4+
- Visualization: django-plotly-dash 2.5+, plotly
- Tests: pytest 8.4+, pytest-django 4.11+, pytest-asyncio 1.2+
- Utilities: pydantic 2.11+, loguru 0.7+
- **Monitoring:** Structured logging (JSON in prod), Health check endpoints

## Monitoring & Observability

### Structured Logging

The project uses **Loguru** for structured logging with automatic JSON serialization in production.

**Documentation:** [backend/LOGGING_AND_HEALTH_CHECKS.md](backend/LOGGING_AND_HEALTH_CHECKS.md)

**Key features:**
- Development: Colorized console output
- Production: JSON format for log aggregation
- File rotation: Daily logs with 30-day retention
- Error logs: Separate file with 90-day retention
- Automatic Django logging interception

**Usage example:**
```python
from loguru import logger

logger.error(
    "Failed to create order",
    trader_id=42,
    order_type="BUY",
    amount=1.5,
    error_type="InsufficientFunds"
)
```

### Health Check Endpoints

Four health check endpoints for monitoring and orchestration:

- `GET /health/` - Comprehensive check (database + Redis)
- `GET /health/live/` - Liveness probe (Kubernetes)
- `GET /health/ready/` - Readiness probe (Kubernetes)
- `GET /health/detailed/` - Extended metrics (debugging)

**Example:**
```bash
curl http://localhost:8000/health/
# {"status": "healthy", "checks": {"database": "ok", "redis": "ok"}}
```

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

The project uses a **three-layer candle architecture**:

**Layer 1: Exchange Candles** (`ExchangeCandle`)
- Direct OHLCV candles from exchange APIs
- Stored in database with unique `id`
- Fetched via `CandleSource` from CCXT

**Layer 2: Candle Providers** (`CandleProvider`)
- Abstraction layer for aggregating/transforming candles
- Three provider types:
  1. **`PlainCandleProvider`** - Wraps single exchange candle (normal trading)
  2. **`DivisionCandleProvider`** - Divides two exchange candles (arbitrage: price1 / price2)
  3. **`MinusCandleProvider`** - Subtracts two exchange candles (spread trading: price1 - price2)
- Validates same timeframe/trading_pair, different exchanges for synthetic providers

**Layer 3: Provider Candles** (`ProviderCandle`)
- Domain object with `primary_candle` and optional `secondary_candle` fields
- Used by traders for signal generation
- Enables both simple and arbitrage strategies

**Architecture Flow:**
```
ExchangeCandle (DB) → CandleSource (fetch) → CandleProvider (aggregate) → ProviderCandle (domain) → Trader
```

**Critical sync flow:**
- Domain layer works with `ProviderCandle` containing `primary_candle` and `secondary_candle`
- `sync_signals()` saves signals to DB with both candle references
- `load()` reconstructs domain objects by calling `candle_provider.get_candle()` to rebuild `ProviderCandle`

### Django Apps Structure

The project has **9 main Django apps** with clear separation of concerns:

1. **exchanges** - Exchange/TradingPair/ExchangeCandle models (foundation layer)
2. **exchange_clients** - CCXT integration, API operations, order/balance management
3. **candle_sources** - Fetches candles from exchange APIs via CCXT
4. **candle_providers** - Aggregation/transformation layer (Plain/Division/Minus providers)
5. **strategies** - Trading strategy implementations (6 strategies: Renko, MFI, Counter-MFI, Stochastic, Counter-Stochastic, Donchian)
6. **risk_managers** - 8 risk manager combinations using mixins (SL × TP × Position Size)
7. **traders** - Main business logic, integrates strategies and risk managers
8. **optimizers** - Parameter optimization using Optuna/DEAP with metrics (ROI, Sharpe, R², Win Rate)
9. **telegram_bots** - Async notifications via aiogram

**Dependency flow:**

```
core (utils, types, registry)
  → exchanges
  → exchange_clients
  → candle_sources
  → candle_providers (NEW - aggregation layer)
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

### 7. Trader uses CandleProvider (Not Direct Exchange Source)

The `Trader` model references `CandleProvider` (not `CandleSource` directly). This enables:
- Plain providers (single exchange, normal trading)
- Division providers (arbitrage via price1/price2)
- Minus providers (spread trading via price1-price2)

Access the primary candle source via: `trader.candle_provider.primary_source`

**ArbitrageTrader Support:**
The `ArbitrageTrader` model coordinates two traders on different exchanges using the same `CandleProvider` for synchronized arbitrage strategies.

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

### Available Strategies (6 Total)

**Trend Following:**

1. **RenkoStrategy** - Renko brick-based signals
   - Parameters: `threshold_up` (0.1-10.0), `threshold_down` (0.1-10.0), `count_bricks` (1-10)
2. **DonchianCrossoverStrategy** - Donchian channel breakouts
   - Parameters: `fast_period` (5-15), `slow_period` (10-20)

**Oscillator-Based:**

3. **MoneyFlowIndexStrategy** - MFI overbought/oversold
   - Parameters: `period` (10-20), `overbought` (0-100), `oversold` (0-100), `median` (0-100)
4. **CounterMoneyFlowIndexStrategy** - Inverse MFI (buy oversold, sell overbought)
   - Same parameters as MoneyFlowIndexStrategy
5. **StochasticStrategy** - Stochastic oscillator
   - Parameters: `k_period` (10-20), `d_period` (1-10), `overbought` (0-100), `oversold` (0-100), `median` (0-100)
6. **CounterStochasticStrategy** - Inverse Stochastic logic
   - Same parameters as StochasticStrategy

### Adding a New Strategy

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

### Risk Manager Combinations (8 Total)

All risk managers follow the naming pattern: `SL{StopLoss}TP{TakeProfit}PS{PositionSize}RiskManager`

**Complete list:**

1. `SLPercentTPPercentPSAllInRiskManager`
2. `SLPercentTPPercentPSByRiskRiskManager`
3. `SLPercentTPRiskRewardPSAllInRiskManager`
4. `SLPercentTPRiskRewardPSByRiskRiskManager`
5. `SLExtremumTPPercentPSAllInRiskManager`
6. `SLExtremumTPPercentPSByRiskRiskManager`
7. `SLExtremumTPRiskRewardPSAllInRiskManager`
8. `SLExtremumTPRiskRewardPSByRiskRiskManager`

**Parameter Ranges:**

- `stop_loss_percent`: 0.01-30.0 (default 1.0)
- `extremum_candle_length`: 1-100 (default 5)
- `take_profit_percent`: 0.01-50.0 (default 2.0)
- `reward_risk`: 0.01-10.0 (default 2.0)
- `max_risk_per_trade`: 0.1-100.0 (default 1.5)

## Optimization

### Optimization Algorithms (2 Available)

1. **OptunaOptimizationAlgorithm** - Bayesian optimization using Optuna library
   - Default: 500 trials
   - Best for: Finding global optimum efficiently

2. **GenerationOptimizationAlgorithm** - Genetic algorithms using DEAP
   - Default: 50 generations, 100 population size
   - Best for: Complex parameter spaces

### Optimization Metrics

The optimizer uses a **weighted composite score** combining:

- **ROI (Return on Investment)** - Weight: 0.40 (default)
- **R² (Coefficient of Determination)** - Weight: 0.30 (default)
- **Sharpe Ratio** - Weight: 0.15 (default)
- **Win Rate** - Weight: 0.15 (default)

Weights are configurable per `TraderOptimizer` instance.

### Re-optimization

The `optimize_old_optimizers` task runs every 30 minutes to re-optimize strategies older than 7 days, ensuring parameters stay current with market conditions.

## Key Files Reference

- Architecture documentation: [backend/BACKEND_STRUCTURE.md](backend/BACKEND_STRUCTURE.md) (comprehensive, in Russian)
- Main trader logic: [backend/traders/domain/traders.py](backend/traders/domain/traders.py)
- Strategy base: [backend/strategies/domain/base.py](backend/strategies/domain/base.py)
- Risk manager base: [backend/risk_managers/domain/base.py](backend/risk_managers/domain/base.py)
- Candle source base: [backend/candle_sources/domain/base.py](backend/candle_sources/domain/base.py)
- Candle provider base: [backend/candle_providers/domain/base.py](backend/candle_providers/domain/base.py)
- Exchange client base: [backend/exchange_clients/domain/base.py](backend/exchange_clients/domain/base.py)
- Celery tasks: `backend/*/tasks.py` in each app
- Celery config: [backend/core/celery.py](backend/core/celery.py)
