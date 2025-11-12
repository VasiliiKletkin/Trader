from datetime import timedelta
from typing import Dict, List

import pandas as pd
import plotly.graph_objs as go
from dash import Input, Output, State, dcc, html
from django.utils import timezone
from django_plotly_dash import DjangoDash
from strategies.domain import StochasticStrategy
from strategies.domain import StochasticData
from traders.models import Trader

app = DjangoDash("StochasticStrategy")

app.layout = html.Div(
    [
        dcc.Graph(id="stochastic-chart"),
        dcc.Store(id="trader-id", data=None),
        dcc.Store(id="stochastic-date-range", data=None),
    ]
)


# Callback для хранения диапазона дат (zoom/pan/autoscale)
@app.callback(
    Output("stochastic-date-range", "data"),
    [
        Input("stochastic-chart", "relayoutData"),
    ],
    [
        State("stochastic-date-range", "data"),
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
    Output("stochastic-chart", "figure"),
    [
        Input("trader-id", "data"),
        Input("stochastic-date-range", "data"),
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
        title="График Stochastic (K и D)",
        xaxis_title="Время",
        yaxis_title="Indicator Value",
        xaxis_rangeslider_visible=False,
        legend=dict(x=0, y=1),
    )

    try:
        trader = Trader.objects.get(pk=trader_id)
    except Trader.DoesNotExist:
        return fig

    strategy: StochasticStrategy = trader.strategy.instantiate()
    overbought = strategy.overbought
    oversold = strategy.oversold

    records = []
    states = trader.states.order_by("timestamp")
    for state in states:
        if not state.signal or not state.signal.data:
            continue
        stochastic_data = StochasticData(**state.signal.data)
        records.append(
            {
                "timestamp": state.timestamp,
                "k_value": stochastic_data.k_value,
                "d_value": stochastic_data.d_value,
            }
        )

    df = pd.DataFrame(records)
    if df.empty:
        return fig

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

    # Hover-информация для K
    df["hovertext_k"] = (
        "Дата: "
        + df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
        + "<br>K: "
        + df["k_value"].astype(str)
    )

    # Hover-информация для D
    df["hovertext_d"] = (
        "Дата: "
        + df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
        + "<br>D: "
        + df["d_value"].astype(str)
    )

    # Рисуем линию K
    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["k_value"],
            mode="lines+markers",
            name="K",
            line=dict(color="blue"),
            hovertext=df["hovertext_k"],
        )
    )

    # Рисуем линию D
    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["d_value"],
            mode="lines+markers",
            name="D",
            line=dict(color="orange"),
            hovertext=df["hovertext_d"],
        )
    )

    # Добавляем горизонтальные линии overbought/oversold
    if overbought is not None:
        fig.add_trace(
            go.Scatter(
                x=[df["timestamp"].min(), df["timestamp"].max()],
                y=[overbought, overbought],
                mode="lines",
                name="Overbought",
                line=dict(color="red", dash="dash"),
                showlegend=True,
            )
        )
    if oversold is not None:
        fig.add_trace(
            go.Scatter(
                x=[df["timestamp"].min(), df["timestamp"].max()],
                y=[oversold, oversold],
                mode="lines",
                name="Oversold",
                line=dict(color="green", dash="dash"),
                showlegend=True,
            )
        )

    return fig
