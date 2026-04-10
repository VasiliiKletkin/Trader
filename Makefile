#!make
include .env

SHELL_CMD = docker-compose exec backend python manage.py shell -c

# ─── Django ───────────────────────────────────────────────────────────────────

## Миграции + сбор статики
dstrt:
	make dmigr && make dcollect

## Сбор статических файлов
dcollect:
	docker-compose exec backend python manage.py collectstatic

## Создание и применение миграций
dmigr:
	docker-compose exec backend python manage.py makemigrations && docker-compose exec backend python manage.py migrate

## Создание суперпользователя
duser:
	docker-compose exec backend python manage.py createsuperuser

## Django shell
dshell:
	docker-compose exec backend python manage.py shell

# ─── PostgreSQL ───────────────────────────────────────────────────────────────

## Создать базу данных
dcreatedb:
	docker-compose exec postgres createdb -h ${POSTGRES_HOST} -U ${POSTGRES_USER} ${POSTGRES_DATABASE}

## Удалить базу данных
ddeletedb:
	docker-compose exec postgres dropdb -h ${POSTGRES_HOST} -U ${POSTGRES_USER} ${POSTGRES_DATABASE}

## Загрузить дамп базы
dloaddump:
	docker-compose exec -T postgres pg_restore --verbose --clean --no-acl --no-owner -h ${POSTGRES_HOST} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} < ${POSTGRES_DATABASE}.dump

## Создать дамп базы
dcreatedump:
	docker-compose exec postgres pg_dump -Fc --no-acl --no-owner -h ${POSTGRES_HOST} -U ${POSTGRES_USER} ${POSTGRES_DATABASE} > ./${POSTGRES_DATABASE}.dump

# ─── Мониторинг БД ───────────────────────────────────────────────────────────

## Соединения по application_name (docker)
dbconns:
	docker-compose exec postgres psql -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} -c "SELECT application_name, state, count(*) FROM pg_stat_activity GROUP BY application_name, state ORDER BY count DESC;"

## Соединения по application_name (локально)
dbconns-local:
	psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} -c "SELECT application_name, state, count(*) FROM pg_stat_activity GROUP BY application_name, state ORDER BY count DESC;"

## Детали всех соединений: PID, время создания, idle duration
dbconns-detail:
	docker-compose exec postgres psql -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} -c "SELECT pid, application_name, state, backend_start, state_change, now() - state_change AS idle_duration FROM pg_stat_activity WHERE datname = current_database() ORDER BY application_name, state_change;"

## Idle-соединения с текстом последнего запроса
dbconns-queries:
	docker-compose exec postgres psql -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} -c "SELECT application_name, left(query, 200) AS query, state, now() - state_change AS idle_duration FROM pg_stat_activity WHERE datname = current_database() AND state = 'idle' ORDER BY idle_duration DESC;"

## Детали по конкретному приложению: make dbconns-app APP=worker_default
dbconns-app:
	@test -n "$(APP)" || (echo "Использование: make dbconns-app APP=worker_default" && exit 1)
	docker-compose exec postgres psql -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} -c "SELECT pid, state, backend_start, state_change, now() - state_change AS idle_duration, left(query, 200) AS query FROM pg_stat_activity WHERE application_name = '$(APP)' ORDER BY state_change;"

## Beat-задачи: расписание, количество запусков, последний запуск
dbbeat:
	docker-compose exec postgres psql -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} -c "SELECT name, task, enabled, total_run_count, last_run_at FROM django_celery_beat_periodictask ORDER BY last_run_at DESC;"

# ─── Мониторинг трейдеров ────────────────────────────────────────────────────

## Активные трейдеры со статусами
traders:
	$(SHELL_CMD) "from traders.models import Trader; [print(f'{t.pk} | {t.get_status_display()} | {t.exchange_client} | {t.strategy}') for t in Trader.objects.select_related('exchange_client', 'strategy').all()]"

## Активные арбитражные трейдеры со статусами
arb-traders:
	$(SHELL_CMD) "from arbitrage_traders.models import ArbitrageTrader; [print(f'{t.pk} | {t.get_status_display()} | {t.left_exchange_client} <-> {t.right_exchange_client} | {t.strategy}') for t in ArbitrageTrader.objects.select_related('left_exchange_client', 'right_exchange_client', 'strategy').all()]"

## Открытые позиции трейдеров
positions:
	$(SHELL_CMD) "from traders.models import TraderPosition; [print(f'{p.pk} | {p.trader} | {p.get_type_display()} | amount={p.amount} | open={p.open_price} | pnl={p.pnl}') for p in TraderPosition.objects.filter(status='opened').select_related('trader')]"

## Открытые позиции арбитражных трейдеров
arb-positions:
	$(SHELL_CMD) "from arbitrage_traders.models import ArbitrageTraderPosition; [print(f'{p.pk} | {p.trader} | {p.get_type_display()} | amount={p.amount} | open={p.open_price} | pnl={p.pnl}') for p in ArbitrageTraderPosition.objects.filter(status='opened').select_related('trader')]"

## Последние 20 ошибок трейдеров
errors:
	$(SHELL_CMD) "from traders.models import TraderError; [print(f'{e.created_at} | {e.trader} | {e.type} | {e.message[:100]}') for e in TraderError.objects.select_related('trader').order_by('-created_at')[:20]]"

## Последние 20 ошибок арбитражных трейдеров
arb-errors:
	$(SHELL_CMD) "from arbitrage_traders.models import ArbitrageTraderError; [print(f'{e.created_at} | {e.trader} | {e.type} | {e.message[:100]}') for e in ArbitrageTraderError.objects.select_related('trader').order_by('-created_at')[:20]]"

## Источники свечей: режим, активность
sources:
	$(SHELL_CMD) "from candle_sources.models import CandleSource; [print(f'{s.pk} | {s.get_mode_display()} | active={s.is_active} | {s.exchange_client} | {s.trading_pair} | {s.get_timeframe_display()}') for s in CandleSource.objects.select_related('exchange_client', 'trading_pair').all()]"

## Активные/зарезервированные задачи в Celery
celery-inspect:
	docker-compose exec backend celery -A core inspect active
	docker-compose exec backend celery -A core inspect reserved

# ─── Celery ──────────────────────────────────────────────────────────────────

## Очистить очередь celery (default)
celery-purge:
	docker-compose exec redis redis-cli DEL celery
	@echo "Очередь celery очищена"

## Очистить все очереди Celery
celery-purge-all:
	docker-compose exec redis redis-cli DEL celery candle_source trader optimizer
	@echo "Все очереди очищены"

## Количество задач в очередях
celery-queues:
	@echo "celery: $$(docker-compose exec redis redis-cli LLEN celery)"
	@echo "candle_source: $$(docker-compose exec redis redis-cli LLEN candle_source)"
	@echo "trader: $$(docker-compose exec redis redis-cli LLEN trader)"
	@echo "optimizer: $$(docker-compose exec redis redis-cli LLEN optimizer)"

# ─── Pre-commit ───────────────────────────────────────────────────────────────

## Запуск pre-commit на всех файлах
hooks:
	cd backend && pre-commit run --all-files
