from datetime import timedelta
from typing import Dict, List

import pandas as pd
import plotly.graph_objs as go
from dash import Input, Output, State, dcc, html
from django.utils import timezone
from django_plotly_dash import DjangoDash
from strategies.domain import MovingAverageCrossoverStrategy
from strategies.domain import MovingAverageCrossoverData
from traders.models import Trader

app = DjangoDash("MovingAverageCrossoverStrategy")

app.layout = html.Div(
    [
        dcc.Graph(id="moving_average_crossover-chart"),
        dcc.Store(id="trader-id", data=None),
        dcc.Store(id="moving_average_crossover-date-range", data=None),
    ]
)


# Callback для хранения диапазона дат (zoom/pan/autoscale)
@app.callback(
    Output("moving_average_crossover-date-range", "data"),
    [
        Input("moving_average_crossover-chart", "relayoutData"),
    ],
    [
        State("moving_average_crossover-date-range", "data"),
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
    Output("moving_average_crossover-chart", "figure"),
    [
        Input("trader-id", "data"),
        Input("moving_average_crossover-date-range", "data"),
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
        title="График Moving Average Crossover",
        xaxis_title="Время",
        yaxis_title="Indicator Value",
        xaxis_rangeslider_visible=False,
        legend=dict(x=0, y=1),
    )

    try:
        trader = Trader.objects.get(pk=trader_id)
    except Trader.DoesNotExist:
        return fig

    strategy: MovingAverageCrossoverStrategy = trader.strategy.instantiate()

    records = []
    states = trader.states.order_by("timestamp")
    for state in states:
        if not state.signal or not state.signal.data:
            continue
        data = MovingAverageCrossoverData(**state.signal.data)
        records.append(
            {
                "timestamp": state.timestamp,
                "fast_avg": data.fast_upper,
                "slow_avg": data.slow_upper,
            }
        )

    df = pd.DataFrame(records)

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["timestamp"] = df["timestamp"].apply(timezone.localtime)
    # Приводим start_date и end_date к той же таймзоне
    tz = timezone.get_current_timezone()
    if timezone.is_naive(start_date):
        start_date = timezone.make_aware(start_date, tz)
    if timezone.is_naive(end_date):
        end_date = timezone.make_aware(end_date, tz)

    df = df[(df["timestamp"] >= start_date) & (df["timestamp"] <= end_date)]
    if df.empty:
        return fig

    # Hover-информация для fast_avg
    df["hovertext_fast_avg"] = (
        "Дата: "
        + df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
        + "<br>Fast avg: "
        + df["fast_avg"].astype(str)
    )


    # Hover-информация для slow_avg
    df["hovertext_slow_avg"] = (
        "Дата: "
        + df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
        + "<br>Slow avg: "
        + df["slow_avg"].astype(str)
    )



    # Рисуем линию fast_avg
    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["fast_avg"],
            mode="lines+markers",
            name="Fast avg",
            line=dict(color="blue"),
            hovertext=df["hovertext_fast_avg"],
        )
    )


    # Рисуем линию slow_avg
    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["slow_avg"],
            mode="lines+markers",
            name="Slow avg",
            line=dict(color="orange"),
            hovertext=df["hovertext_slow_avg"],
        )
    )

 
    return fig
