"""
Health check views for monitoring application status.

Provides endpoints for checking:
- Database connectivity
- Redis connectivity
- Overall application health
"""

from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse
from loguru import logger


def check_database() -> tuple[bool, str]:
    """
    Check database connectivity.

    Returns:
        Tuple[bool, str]: (is_healthy, status_message)
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        logger.debug("Health check: Database is healthy")
        return True, "ok"
    except Exception as e:
        logger.error(
            "Health check: Database is unhealthy",
            error_type=type(e).__name__,
            error_message=str(e),
        )
        return False, f"error: {e!s}"


def check_redis() -> tuple[bool, str]:
    """
    Check Redis connectivity via Django cache.

    Returns:
        Tuple[bool, str]: (is_healthy, status_message)
    """
    try:
        cache.set("health_check", "ok", timeout=10)
        result = cache.get("health_check")
        if result == "ok":
            logger.debug("Health check: Redis is healthy")
            return True, "ok"
        else:
            logger.error("Health check: Redis cache test failed")
            return False, "error: Cache test failed"
    except Exception as e:
        logger.error(
            "Health check: Redis is unhealthy",
            error_type=type(e).__name__,
            error_message=str(e),
        )
        return False, f"error: {e!s}"


def perform_health_checks() -> tuple[bool, dict[str, str]]:
    """
    Perform all health checks.

    Returns:
        Tuple[bool, Dict[str, str]]: (overall_healthy, checks_dict)
    """
    checks = {}
    overall_healthy = True

    # Database check
    db_healthy, db_status = check_database()
    checks["database"] = db_status
    if not db_healthy:
        overall_healthy = False

    # Redis check
    redis_healthy, redis_status = check_redis()
    checks["redis"] = redis_status
    if not redis_healthy:
        overall_healthy = False

    return overall_healthy, checks


def health_check(request):
    """
    Comprehensive health check endpoint.
    Returns HTTP 200 if all systems are operational, 503 otherwise.

    Usage:
        GET /health/

    Response (healthy):
        {
            "status": "healthy",
            "checks": {
                "database": "ok",
                "redis": "ok"
            }
        }

    Response (unhealthy):
        {
            "status": "unhealthy",
            "checks": {
                "database": "ok",
                "redis": "error: Connection refused"
            }
        }
    """
    overall_healthy, checks = perform_health_checks()

    status_code = 200 if overall_healthy else 503
    response_data = {
        "status": "healthy" if overall_healthy else "unhealthy",
        "checks": checks,
    }

    return JsonResponse(response_data, status=status_code)


def liveness_check(request):
    """
    Liveness probe for Kubernetes/Docker.
    Returns HTTP 200 if the application process is running.

    This is a lightweight check that only verifies the application
    can handle requests. It does not check external dependencies.

    Usage:
        GET /health/live/

    Response:
        {
            "status": "alive"
        }
    """
    return JsonResponse({"status": "alive"})
