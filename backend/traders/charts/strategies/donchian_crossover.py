from datetime import timedelta

import pandas as pd
import plotly.graph_objs as go
from dash import Input, Output, State, dcc, html
from django.utils import timezone
from django_plotly_dash import DjangoDash

from core.utils.common import dt_str
from traders.domain import DonchianCrossoverData
from traders.models import Trader

app = DjangoDash("DonchianCrossoverStrategy")

app.layout = html.Div(
    [
        dcc.Graph(id="donchian_crossover-chart"),
        dcc.Store(id="trader-id", data=None),
        dcc.Store(id="donchian_crossover-date-range", data=None),
    ]
)


# Callback для хранения диапазона дат (zoom/pan/autoscale)
@app.callback(
    Output("donchian_crossover-date-range", "data"),
    [
        Input("donchian_crossover-chart", "relayoutData"),
    ],
    [
        State("donchian_crossover-date-range", "data"),
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
    Output("donchian_crossover-chart", "figure"),
    [
        Input("trader-id", "data"),
        Input("donchian_crossover-date-range", "data"),
    ],
)
def update_chart(trader_id, date_range):
    end_date = timezone.now()
    start_date = end_date - timedelta(days=30)
    if date_range and date_range.get("start") and date_range.get("end"):
        try:
            start_date = pd.to_datetime(date_range["start"])
            end_date = pd.to_datetime(date_range["end"])
        except Exception:
            pass

    fig = go.Figure()
    fig.update_layout(
        title="График Donchian Crossover",
        xaxis_title="Время",
        yaxis_title="Indicator Value",
        xaxis_rangeslider_visible=False,
        legend={"x": 0, "y": 1},
    )

    try:
        trader = Trader.objects.get(pk=trader_id)
    except Trader.DoesNotExist:
        return fig

    records = []
    # Добавлена фильтрация по дате для оптимизации запроса
    signals = trader.signals.filter(timestamp__range=(start_date, end_date)).order_by(
        "timestamp"
    )
    for signal in signals:
        data = DonchianCrossoverData(**signal.data)
        records.append(
            {
                "timestamp": signal.timestamp,
                "fast_upper": data.fast_upper,
                "fast_lower": data.fast_lower,
                "slow_upper": data.slow_upper,
                "slow_lower": data.slow_lower,
            }
        )

    df = pd.DataFrame(records)

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["timestamp"] = df["timestamp"].apply(timezone.localtime)
    if df.empty:
        return fig

    # Hover-информация для fast_upper
    df["hovertext_fast_upper"] = (
        "Дата: "
        + df["timestamp"].apply(dt_str)
        + "<br>Fast upper: "
        + df["fast_upper"].astype(str)
    )

    # Hover-информация для fast_lower
    df["hovertext_fast_lower"] = (
        "Дата: "
        + df["timestamp"].apply(dt_str)
        + "<br>Fast lower: "
        + df["fast_lower"].astype(str)
    )

    # Hover-информация для slow_upper
    df["hovertext_slow_upper"] = (
        "Дата: "
        + df["timestamp"].apply(dt_str)
        + "<br>Slow upper: "
        + df["slow_upper"].astype(str)
    )

    # Hover-информация для slow_lower
    df["hovertext_slow_lower"] = (
        "Дата: "
        + df["timestamp"].apply(dt_str)
        + "<br>Slow lower: "
        + df["slow_lower"].astype(str)
    )

    # Рисуем линию fast_upper
    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["fast_upper"],
            mode="lines+markers",
            name="Fast upper",
            line={"color": "orange"},
            hovertext=df["hovertext_fast_upper"],
        )
    )

    # Рисуем линию fast_lower
    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["fast_lower"],
            mode="lines+markers",
            name="Fast lower",
            line={"color": "orange"},
            hovertext=df["hovertext_fast_lower"],
        )
    )

    # Рисуем линию slow_upper
    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["slow_upper"],
            mode="lines+markers",
            name="Slow upper",
            line={"color": "orange"},
            hovertext=df["hovertext_slow_upper"],
        )
    )

    # Рисуем линию slow_lower
    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["slow_lower"],
            mode="lines+markers",
            name="Slow lower",
            line={"color": "orange"},
            hovertext=df["hovertext_slow_lower"],
        )
    )

    return fig
