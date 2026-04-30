"""
Django settings for core project.
"""

import logging
import os
import socket
import sys
from pathlib import Path

from loguru import logger

from core.logging import InterceptHandler

# ─── Base ─────────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("SECRET_KEY", "secret_key")
DEBUG = os.environ.get("DEBUG", "False") == "True"
LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG")
ENVIRONMENT = os.environ.get("ENVIRONMENT", "development")
RELEASE = os.environ.get("RELEASE") or None

ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split()
CSRF_TRUSTED_ORIGINS = os.environ.get("CSRF_TRUSTED_ORIGINS", "").split()
INTERNAL_IPS = ["127.0.0.1"]

# ─── Sentry ───────────────────────────────────────────────────────────────────

SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
SENTRY_TRACES_SAMPLE_RATE = float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.0"))
if SENTRY_DSN:
    import sentry_sdk

    from arbitrage_traders.domain.exceptions import CandleDesyncError

    def _sentry_before_send(event, hint):
        """Сбрасываем заведомо «бизнесовые», не-баговые исключения, чтобы
        они не забивали Sentry-канал."""
        exc_info = hint.get("exc_info") if hint else None
        if exc_info:
            exc_type = exc_info[0]
            if exc_type is not None and issubclass(exc_type, CandleDesyncError):
                return None
        return event

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=ENVIRONMENT,
        release=RELEASE,
        # Add data like request headers and IP for users,
        # see https://docs.sentry.io/platforms/python/data-management/data-collected/
        send_default_pii=True,
        # Performance monitoring (0.0 = выключено, 0.1 = 10% запросов/тасков).
        traces_sample_rate=SENTRY_TRACES_SAMPLE_RATE,
        before_send=_sentry_before_send,
    )

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
ROOT_URLCONF = "core.urls"
WSGI_APPLICATION = "core.wsgi.application"
ASGI_APPLICATION = "core.asgi.application"
X_FRAME_OPTIONS = "SAMEORIGIN"

# ─── Константы проекта ────────────────────────────────────────────────────────

ADMIN_INLINE_MAX_NUM = 10
BULK_BATCH_SIZE = 1000

# ─── Apps & Middleware ────────────────────────────────────────────────────────

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "cacheops",
    "django_celery_beat",
    "django_celery_results",
    "django_plotly_dash.apps.DjangoPlotlyDashConfig",
    "admin_auto_filters",
    "rangefilter",
    "channels",
    # Project
    "exchanges",
    "exchange_clients",
    "candle_sources",
    "telegram_bots",
    "traders",
    "arbitrage_traders",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_plotly_dash.middleware.BaseMiddleware",
]

if DEBUG:
    INSTALLED_APPS = [*INSTALLED_APPS, "debug_toolbar"]
    MIDDLEWARE = ["debug_toolbar.middleware.DebugToolbarMiddleware", *MIDDLEWARE]
    ip = socket.gethostbyname(socket.gethostname())
    INTERNAL_IPS += [ip[:-1] + "1"]
    DEBUG_TOOLBAR_CONFIG = {
        "SHOW_TOOLBAR_CALLBACK": lambda request: (
            not request.path.startswith("/django_plotly_dash/")
        ),
        "DISABLE_PANELS": {
            "debug_toolbar.panels.cache.CachePanel",
            "debug_toolbar.panels.profiling.ProfilingPanel",
        },
    }

# ─── Templates ────────────────────────────────────────────────────────────────

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    }
}

# ─── Database ─────────────────────────────────────────────────────────────────

_db_engine = os.environ.get("POSTGRES_ENGINE", "django.db.backends.sqlite3")

DATABASES = {
    "default": {
        "ENGINE": _db_engine,
        "NAME": os.environ.get("POSTGRES_DATABASE", BASE_DIR / "db.sqlite3"),
        "USER": os.environ.get("POSTGRES_USER", "user"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "password"),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

DB_STATEMENT_TIMEOUT = int(os.environ.get("DB_STATEMENT_TIMEOUT", "30000"))

if "postgresql" in _db_engine:
    DATABASES["default"]["CONN_MAX_AGE"] = 600  # type: ignore[assignment]
    DATABASES["default"]["CONN_HEALTH_CHECKS"] = True  # type: ignore[assignment]
    _app_name = os.environ.get("POSTGRES_APP_NAME", "django")
    DATABASES["default"]["OPTIONS"] = {  # type: ignore[assignment]
        "options": (
            f"-c statement_timeout={DB_STATEMENT_TIMEOUT}"
            f" -c application_name={_app_name}"
        ),
    }

# ─── Redis & Cache ────────────────────────────────────────────────────────────

REDIS = {
    "HOST": os.environ.get("REDIS_HOST", "redis"),
    "PORT": os.environ.get("REDIS_PORT", "6379"),
    "USER": os.environ.get("REDIS_USER", ""),
    "PASSWORD": os.environ.get("REDIS_PASSWORD", ""),
    "BROKER_DATABASE": os.environ.get("REDIS_BROKER_DATABASE", 0),
    "CACHE_DATABASE": os.environ.get("REDIS_CACHE_DATABASE", 1),
    "EXCHANGE_CACHE_DATABASE": os.environ.get("REDIS_EXCHANGE_CACHE_DATABASE", 2),
    "BUS_DATABASE": os.environ.get("REDIS_BUS_DATABASE", 3),
    "CACHEOPS_DATABASE": os.environ.get("REDIS_CACHEOPS_DATABASE", 4),
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": f"redis://{REDIS['HOST']}:{REDIS['PORT']}/{REDIS['CACHE_DATABASE']}",
        "OPTIONS": {
            **({"password": REDIS["PASSWORD"]} if REDIS.get("PASSWORD") else {}),
        },
        "KEY_PREFIX": "trader",
        "TIMEOUT": 300,
    }
}

# ─── Cacheops ────────────────────────────────────────────────────────────────

CACHEOPS_ENABLED = os.environ.get("CACHEOPS_ENABLED", "True") == "True"

CACHEOPS_REDIS = f"redis://{REDIS['HOST']}:{REDIS['PORT']}/{REDIS['CACHEOPS_DATABASE']}"

# Кэшируем только count-запросы для display-методов в админке
CACHEOPS = {
    "candle_sources.CandleSource": {"ops": "count", "timeout": 300},
    "candle_sources.CandleSourceError": {"ops": "count", "timeout": 300},
    "exchanges.ExchangeCandle": {"ops": "count", "timeout": 30},
    "traders.Trader": {"ops": "count", "timeout": 300},
    "arbitrage_traders.ArbitrageTrader": {"ops": "count", "timeout": 300},
}

# ─── Celery ───────────────────────────────────────────────────────────────────

CELERY_BROKER_URL = (
    f"redis://{REDIS['HOST']}:{REDIS['PORT']}/{REDIS['BROKER_DATABASE']}"
)
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "django-db")
CELERY_RESULT_EXTENDED = True
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
CELERY_TASK_ALWAYS_EAGER = os.environ.get("CELERY_TASK_ALWAYS_EAGER", "False") == "True"
CELERY_TASK_EAGER_PROPAGATES = (
    os.environ.get("CELERY_TASK_EAGER_PROPAGATES", "False") == "True"
)
CELERY_WORKER_LOG_LEVEL = LOG_LEVEL

# ─── Auth ─────────────────────────────────────────────────────────────────────

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ─── Internationalization ─────────────────────────────────────────────────────

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "Europe/Moscow"
USE_I18N = True
USE_TZ = True

# ─── Static files ─────────────────────────────────────────────────────────────

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "mediafiles"

STATICFILES_FINDERS = [
    "django.contrib.staticfiles.finders.FileSystemFinder",
    "django.contrib.staticfiles.finders.AppDirectoriesFinder",
    "django_plotly_dash.finders.DashComponentFinder",
]

# ─── Logging (loguru) ─────────────────────────────────────────────────────────

logger.remove()

if DEBUG:
    logger.add(
        sys.stdout,
        level=LOG_LEVEL,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level> | {extra}"
        ),
        enqueue=True,
        backtrace=True,
        diagnose=True,
    )
else:
    logger.add(
        sys.stdout,
        level=LOG_LEVEL,
        serialize=True,
        enqueue=True,
        backtrace=True,
        diagnose=False,
    )

logging.basicConfig(handlers=[InterceptHandler()], level=0)
for logger_name in logging.root.manager.loggerDict:
    logging.getLogger(logger_name).handlers = []
    logging.getLogger(logger_name).propagate = True
