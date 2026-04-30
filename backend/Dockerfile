# For more information, please refer to https://aka.ms/vscode-docker-python
# Стадия 1: Сборка зависимостей
FROM python:3.12-slim

# Версия деплоя — git SHA из CI. Используется Sentry как `release`.
# Передаётся через --build-arg GIT_SHA=$GITHUB_SHA в .github/workflows/build.yml.
ARG GIT_SHA=unknown
ENV RELEASE=$GIT_SHA

# ENV переменные (не обязательны, но полезны для consistency)
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Системные зависимости
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Установка Poetry
RUN pip install poetry==2.1.2

# Установка рабочей директории
WORKDIR /app

# Скопируй файлы Poetry
COPY pyproject.toml poetry.lock /app/

# Настрой Poetry (не создавать venv)
RUN poetry config virtualenvs.create false

# Установи зависимости (включая dev, если нужно; для production добавь --no-dev)
RUN poetry install --no-interaction --no-ansi --no-root

# Скопируй остальной код проекта
COPY . /app/

# Установи Celery (если не установлен через Poetry)
# RUN pip install celery==5.5.3

# Пользователь и права
RUN adduser -u 5678 --disabled-password --gecos "" appuser && chown -R appuser /app
USER appuser

# Открой порт
EXPOSE 8000

# Запуск команды
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "core.wsgi"]
