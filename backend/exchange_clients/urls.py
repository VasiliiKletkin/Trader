from django.urls import path

from exchange_clients.views import ExchangeClientDetailView

urlpatterns = [
    path(
        "exchange_client/<int:pk>/",
        ExchangeClientDetailView.as_view(),
        name="exchange_client_detail",
    ),
]
