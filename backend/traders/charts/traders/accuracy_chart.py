import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, dcc, html
from django.db import models
from django.utils import timezone
from django_plotly_dash import DjangoDash

from core.utils.charts import (
    create_date_picker_range,
    parse_date_range,
    register_date_preset_callbacks,
)
from core.utils.common import dt_str
from traders.models import Trader, TraderOrder

app = DjangoDash("AccuracyChart")
app.layout = html.Div(
    [
        create_date_picker_range(),
        dcc.Graph(id="accuracy-chart"),
        dcc.Store(id="trader-id", data=None),
    ]
)

register_date_preset_callbacks(app)


@app.callback(
    Output("accuracy-chart", "figure"),
    [
        Input("trader-id", "data"),
        Input("date-range-picker", "start_date"),
        Input("date-range-picker", "end_date"),
    ],
)
def update_accuracy_chart(trader_id, start_date_str, end_date_str):
    start_date, end_date = parse_date_range(start_date_str, end_date_str)

    fig = go.Figure()

    fig.update_layout(
        title="График задержки лага ордеров",
        xaxis_title="Время ордера",
        yaxis_title="Время лага (секунды)",
        height=500,
        xaxis_rangeslider_visible=False,
        legend={"x": 0, "y": 1},
    )
    if not trader_id:
        return fig

    trader = Trader.objects.get(id=trader_id)

    trader_orders: models.QuerySet[TraderOrder] = trader.orders.filter(
        order__timestamp__range=(start_date, end_date),
    ).order_by("order__timestamp")

    if not trader_orders.exists():
        return fig

    records = []
    for trader_order in trader_orders:
        order = trader_order.order
        signal_dt = order.timestamp.replace(second=0, microsecond=0)
        lag_seconds = (order.timestamp - signal_dt).total_seconds()
        records.append(
            {
                "timestamp": order.timestamp,
                "lag_seconds": lag_seconds,
                "order_id": order.pk,
            }
        )

    df = pd.DataFrame(records)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["timestamp"] = df["timestamp"].apply(timezone.localtime)

    df["hovertext"] = [
        f"Order ID: {row['order_id']}<br>Time: {dt_str(row['timestamp'])}<br>Lag: {row['lag_seconds']:.2f} сек"
        for _, row in df.iterrows()
    ]

    # Добавляем точки для каждого ордера с линией
    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["lag_seconds"],
            mode="lines+markers",
            name="Лаг ордеров",
            marker={"color": "red", "size": 8},
            line={"color": "red", "width": 2},
            hovertext=df["hovertext"],
        )
    )

    return fig
