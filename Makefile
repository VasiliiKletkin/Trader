#!make
include .env


dstrt:
	make dmigr && make dcollect

dcollect:
	docker-compose exec backend python manage.py collectstatic
dupbuild:
	docker-compose -f "docker-compose.prod.yml" up --build
dup:
	docker-compose -f "docker-compose.prod.yml" up
dbuild:
	docker-compose -f "docker-compose.prod.yml" build
dstop:
	docker-compose -f "docker-compose.prod.yml" stop

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
