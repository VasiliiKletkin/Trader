from datetime import timedelta
from typing import List

import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, dcc, html
from django.utils import timezone
from django.utils.timezone import localtime
from django_plotly_dash import DjangoDash
from traders.models import Trader, TraderOrder
from django.db import models

app = DjangoDash("AccuracyChart")
app.layout = html.Div(
    [
        dcc.Graph(id="accuracy-chart"),
        dcc.Store(id="trader-id", data=None),
        dcc.Store(id="accuracy-date-range", data=None),
    ]
)


# Callback для хранения диапазона дат (zoom/pan/autoscale)
@app.callback(
    Output("accuracy-date-range", "data"),
    [
        Input("accuracy-chart", "relayoutData"),
    ],
    [
        State("accuracy-date-range", "data"),
    ],
)
def update_date_range(relayout_data, stored_range):
    if relayout_data:
        x0 = relayout_data.get("xaxis.range[0]")
        x1 = relayout_data.get("xaxis.range[1]")
        if x0 and x1:
            return {"start": x0, "end": x1}
        if relayout_data.get("xaxis.autorange") or relayout_data.get(
            "xaxis.autorange", False
        ):
            return None
    return stored_range


# Callback для построения графика по диапазону
@app.callback(
    Output("accuracy-chart", "figure"),
    [
        Input("trader-id", "data"),
        Input("accuracy-date-range", "data"),
    ],
)
def update_accuracy_chart(trader_id, date_range):
    end_date = timezone.now()
    start_date = end_date - timedelta(days=300)
    if date_range and date_range.get("start") and date_range.get("end"):
        try:
            start_date = pd.to_datetime(date_range["start"])
            end_date = pd.to_datetime(date_range["end"])
        except Exception:
            pass

    fig = go.Figure()

    fig.update_layout(
        title="График задержки лага ордеров",
        xaxis_title="Время ордера",
        yaxis_title="Время лага (секунды)",
        height=500,
        xaxis_rangeslider_visible=False,
        legend=dict(x=0, y=1),
    )
    if not trader_id:
        return fig

    trader = Trader.objects.get(id=trader_id)

    trader_orders: models.QuerySet[TraderOrder] = trader.orders.filter(
        order__timestamp__range=(start_date, end_date),
    ).order_by("order__timestamp")

    if not trader_orders.exists():
        return fig

    lag_data = []
    for trader_order in trader_orders:
        order = trader_order.order
        signal_dt = order.timestamp.replace(second=0, microsecond=0)
        lag_seconds = (order.timestamp - signal_dt).total_seconds()
        lag_data.append(
            {
                "order_time": localtime(order.timestamp),
                "lag_seconds": lag_seconds,
                "order_id": order.id,
            }
        )

    if not lag_data:
        return fig

    df_lag = pd.DataFrame(lag_data)

    # Добавляем точки для каждого ордера с линией
    fig.add_trace(
        go.Scatter(
            x=df_lag["order_time"],
            y=df_lag["lag_seconds"],
            mode="lines+markers",
            name="Лаг ордеров",
            marker=dict(color="red", size=8),
            line=dict(color="red", width=2),
            hovertext=[
                f"Order ID: {row['order_id']}<br>Time: {row['order_time'].strftime('%Y-%m-%d %H:%M:%S')}<br>Lag: {row['lag_seconds']:.2f} сек"
                for _, row in df_lag.iterrows()
            ],
        )
    )

    # # Добавляем линию среднего лага
    # avg_lag = df_lag["lag_seconds"].mean()
    # fig.add_trace(
    #     go.Scatter(
    #         x=[df_lag["order_time"].min(), df_lag["order_time"].max()],
    #         y=[avg_lag, avg_lag],
    #         mode="lines",
    #         name=f"Средний лаг: {avg_lag:.2f} сек",
    #         line=dict(color="blue", dash="dash"),
    #     )
    # )

    return fig
