# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Cryptocurrency trading system built with Django + Celery. Supports regular and arbitrage trading across multiple exchanges. The project uses a domain-driven architecture: ORM models handle persistence, domain classes handle async business logic.

Language: Russian is used in admin verbose_name, comments, and commit messages.

## Commands

All commands run from `backend/` directory. Poetry manages dependencies.

```bash
# Install dependencies
cd backend && poetry install

# Run tests (uses SQLite + eager Celery, configured in pyproject.toml)
cd backend && poetry run pytest
cd backend && poetry run pytest traders/tests/test_traders.py  # single file
cd backend && poetry run pytest -k "test_handle_candle"         # single test

# Linting & formatting (ruff replaces flake8/isort/black)
cd backend && poetry run ruff check .
cd backend && poetry run ruff check --fix .
cd backend && poetry run ruff format .

# Type checking
cd backend && poetry run mypy .

# Security scan
cd backend && poetry run bandit -r . -s B101,B107,B110,B311 -x tests,migrations

# Django management
cd backend && python manage.py makemigrations
cd backend && python manage.py migrate
cd backend && python manage.py shell

# Docker (local development)
docker-compose up                    # all services
docker-compose exec backend python manage.py shell
```

Pre-commit hooks run: ruff (lint + format), bandit, django-upgrade, trailing-whitespace, poetry check.

## Architecture

### App Structure

Each Django app follows the same pattern:
```
app/
├── models.py          # ORM models (persistence, DB queries, sync/instantiate methods)
├── domain/
│   ├── base.py        # Domain classes (async business logic)
│   ├── schemas.py     # Pydantic validation models
│   └── strategies.py  # Concrete implementations (registered via Registry)
├── tasks.py           # Celery tasks (wrap async domain calls with asyncio.run())
├── admin.py           # Django admin configuration
└── tests/
    └── conftest.py    # App-specific fixtures
```

### Domain-Driven Design Pattern

ORM and domain layers are connected via two key methods on ORM models:
- `instantiate()` — creates a domain object from an ORM model (ORM → Domain)
- `sync()` — persists domain state back to the database (Domain → ORM)

Domain classes use `async/await` for exchange API interactions. Celery tasks bridge sync/async with `asyncio.run()`.

### Registry Pattern

Strategies, risk managers, and exchange clients register via `core.utils.registry.Registry`. Models store `class_name` (CharField) + `arguments` (JSONField). At runtime, `Registry.get_class(class_name)` resolves the implementation, instantiated with the stored arguments.

### Django Apps

| App | Purpose |
|-----|---------|
| **exchanges** | Exchange definitions, TradingPair, ExchangeCandle (OHLCV data) |
| **exchange_clients** | API credentials, proxy config, balance/order tracking, async exchange connections |
| **candle_sources** | Links exchange_client + trading_pair + timeframe; fetches & syncs candles |
| **strategies** | Trading signal generation (MovingAverageCrossover, Donchian, Renko, Grid, etc.) |
| **risk_managers** | Position sizing, stop-loss, take-profit calculation |
| **traders** | Core trading engine: positions, signals, orders, PnL metrics, reboot (backtesting) |
| **optimizers** | Strategy parameter optimization (Bayesian, genetic) with multi-metric scoring |
| **telegram_bots** | Async notifications via aiogram (error alerts, daily P&L reports) |
| **core** | Settings, Celery config, shared types/enums, mixins (ActiveManagerMixin, TimeStampedMixin) |

### Celery Task Pipeline

Celery Beat triggers periodic tasks every minute:

1. **Candle Fetch** (`sources_fetch_last_candles`) → fans out to per-exchange-client tasks on queue `sources_fetch_last_candles_for_exchange_client`
2. **Trader Processing** → after candles are synced, processes each trader on queue `traders_process_for_exchange_client` (generate signals, check positions, execute orders)
3. **Additional queues**: `trader_reboot` (historical backtesting), `optimizer_optimize` (parameter optimization)

### Key Enums (core.utils.types)

- `TraderStatus`: ENABLED, DISABLED, PAUSED, REBOOTING, ERROR
- `SignalType`: BUY, SELL, WAIT
- `PositionType`: LONG, SHORT
- `PositionStatus`: OPENED, CLOSED
- `PositionCloseReason`: TAKE_PROFIT, STOP_LOSS, OPPOSITE_SIGNAL, STRATEGY, TIMEOUT, MANUAL
- `Timeframe`: 1m, 5m, 15m, 1h, 4h, 1d, 1w

## CI/CD

- **CI**: Runs `poetry run pytest` on PRs to `staging` and `main`
- **CD Staging**: Push to `staging` → test → Docker build → deploy via SSH
- **CD Production**: Push to `main` → test → Docker build → deploy via SSH

Git flow: feature branches → `staging` → `main`

## Testing

Tests use SQLite (not Postgres) and eager Celery (tasks execute synchronously). Configured in `pyproject.toml` under `[tool.pytest.ini_options]`.

Shared fixtures in `backend/conftest.py` provide `trading_pair`, `timeframe`, `exchange_candle`. Each app has its own `tests/conftest.py` with app-specific fixtures.

## Code Style

- Python 3.12, line length 88
- Ruff for linting and formatting (see `pyproject.toml [tool.ruff]` for full rule config)
- Cyrillic characters allowed in strings/comments (RUF001-003 ignored)
- Migrations excluded from linting
- `@pytest.fixture` for test setup, no Django TestCase classes
