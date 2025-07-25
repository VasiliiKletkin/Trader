from datetime import timedelta
from typing import Dict, List

import pandas as pd
import plotly.graph_objs as go
from dash import Input, Output, State, dcc, html
from strategies.domain import MFIState
from django.utils import timezone
from django_plotly_dash import DjangoDash
from traders.models import Trader

app = DjangoDash("MFIStrategy")

app.layout = html.Div(
    [
        dcc.Graph(id="mfi-chart"),
        dcc.Store(id="trader-id", data=None),
        dcc.Store(id="mfi-date-range", data=None),
    ]
)


# Callback для хранения диапазона дат (zoom/pan/autoscale)
@app.callback(
    Output("mfi-date-range", "data"),
    [
        Input("mfi-chart", "relayoutData"),
    ],
    [
        State("mfi-date-range", "data"),
    ],
)
def update_mfi_date_range(relayout_data, stored_range):
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
    Output("mfi-chart", "figure"),
    [
        Input("trader-id", "data"),
        Input("mfi-date-range", "data"),
    ],
)
def update_mfi_chart(trader_id, date_range):
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
        title="График MFI",
        xaxis_title="Время",
        yaxis_title="Indicator Value",
        xaxis_rangeslider_visible=False,
        legend=dict(x=0, y=1),
    )

    try:
        trader = Trader.objects.get(pk=trader_id)
    except Trader.DoesNotExist:
        return fig

    domain_trader = trader.instantiate()
    domain_trader.load_state(trader.data)
    states: List[MFIState] = domain_trader.strategy.states

    overbought = trader.strategy.arguments.get("overbought")
    oversold = trader.strategy.arguments.get("oversold")

    records = []
    for state in states:
        records.append(
            {
                "timestamp": state.timestamp,
                "mfi": state.mfi_value,
            }
        )

    df = pd.DataFrame(records)

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["timestamp"] = df["timestamp"].apply(timezone.localtime)
    # Приводим start_date и end_date к той же таймзоне, что и df["timestamp"]
    tz = timezone.get_current_timezone()
    if timezone.is_naive(start_date):
        start_date = timezone.make_aware(start_date, tz)
    if timezone.is_naive(end_date):
        end_date = timezone.make_aware(end_date, tz)

    df = df[(df["timestamp"] >= start_date) & (df["timestamp"] <= end_date)]
    if df.empty:
        return fig

    # Hover-информация
    df["hovertext"] = (
        "Дата: "
        + df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
        + "<br>MFI: "
        + df["mfi"].astype(str)
    )

    # Рисуем линию MFI
    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["mfi"],
            mode="lines+markers",
            name="MFI",
            line=dict(color="blue"),
            hovertext=df["hovertext"],
        )
    )
    # Добавляем горизонтальные линии overbought/oversold, если заданы
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
