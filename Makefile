#!make
include .env


dstrt:
	make dmigr && make dcollect

dcollect:
	docker-compose exec backend python manage.py collectstatic

dmigr:
	docker-compose exec backend python manage.py makemigrations && docker-compose exec backend python manage.py migrate
duser:
	docker-compose exec backend python manage.py createsuperuser
dshell:
	docker-compose exec backend python manage.py shell

dcreatedb:
	docker-compose exec postgres createdb -h ${POSTGRES_HOST} -U ${POSTGRES_USER} ${POSTGRES_DATABASE}
ddeletedb:
	docker-compose exec postgres dropdb -h ${POSTGRES_HOST} -U ${POSTGRES_USER} ${POSTGRES_DATABASE}
dloaddump:
	docker-compose exec -T postgres pg_restore --verbose --clean --no-acl --no-owner -h ${POSTGRES_HOST} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} < ${POSTGRES_DATABASE}.dump
dcreatedump:
	docker-compose exec postgres pg_dump -Fc --no-acl --no-owner -h ${POSTGRES_HOST} -U ${POSTGRES_USER} ${POSTGRES_DATABASE} > ./${POSTGRES_DATABASE}.dump

dbconns:
	docker-compose exec postgres psql -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} -c "SELECT application_name, state, count(*) FROM pg_stat_activity GROUP BY application_name, state ORDER BY count DESC;"

hooks:
	cd backend && pre-commit run --all-files
