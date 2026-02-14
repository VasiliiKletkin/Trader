"""
URL configuration for core project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, reverse_lazy
from django.views.generic import RedirectView

from core.health import health_check, liveness_check

urlpatterns = [
    path("admin/", admin.site.urls),
    path("django_plotly_dash/", include("django_plotly_dash.urls")),
    path("traders/", include("traders.urls")),
    path("arbitrage-traders/", include("arbitrage_traders.urls")),
    path("candle-sources/", include("candle_sources.urls")),
    # Health check endpoints
    path("health/", health_check, name="health"),
    path("health/live/", liveness_check, name="health-live"),
    path("", RedirectView.as_view(url=reverse_lazy("admin:index"), permanent=False)),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
