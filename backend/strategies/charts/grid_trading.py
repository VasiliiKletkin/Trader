from datetime import timedelta
from typing import Dict, List

import pandas as pd
import plotly.graph_objs as go
from dash import Input, Output, State, dcc, html
from django.utils import timezone
from django_plotly_dash import DjangoDash
from strategies.domain import GridTradingStrategy
from strategies.domain import GridTradingData
from traders.models import Trader
from core.utils.common import dt_str

app = DjangoDash("GridTradingStrategy")

app.layout = html.Div(
    [
        dcc.Graph(id="grid_trading-chart"),
        dcc.Store(id="trader-id", data=None),
        dcc.Store(id="grid_trading-date-range", data=None),
    ]
)


# Callback для хранения диапазона дат (zoom/pan/autoscale)
@app.callback(
    Output("grid_trading-date-range", "data"),
    [
        Input("grid_trading-chart", "relayoutData"),
    ],
    [
        State("grid_trading-date-range", "data"),
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
    Output("grid_trading-chart", "figure"),
    [
        Input("trader-id", "data"),
        Input("grid_trading-date-range", "data"),
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
        title="График Grid Trading",
        xaxis_title="Время",
        yaxis_title="Indicator Value",
        xaxis_rangeslider_visible=False,
        legend=dict(x=0, y=1),
    )

    try:
        trader = Trader.objects.get(pk=trader_id)
    except Trader.DoesNotExist:
        return fig

    records = []
    # Добавлена фильтрация по дате для оптимизации запроса
    states = trader.states.filter(
        timestamp__gte=start_date, timestamp__lte=end_date
    ).order_by("timestamp")
    for state in states:
        if not state.signal or not state.signal.data:
            continue
        data = GridTradingData(**state.signal.data)
        records.append(
            {
                "timestamp": state.timestamp,
                "avg": data.avg,
                "narrow_grid_up": data.narrow_grid_up,
                "narrow_grid_down": data.narrow_grid_down,
                "wide_grid_up": data.wide_grid_up,
                "wide_grid_down": data.wide_grid_down,
            }
        )
    df = pd.DataFrame(records)

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["timestamp"] = df["timestamp"].apply(timezone.localtime)
    if df.empty:
        return fig

    # Hover-информация для avg
    df["hovertext_avg"] = (
        "Дата: " + df["timestamp"].apply(dt_str) + "<br>avg: " + df["avg"].astype(str)
    )

    # Hover-информация для narrow_grid_up
    df["hovertext_narrow_grid_up"] = (
        "Дата: "
        + df["timestamp"].apply(dt_str)
        + "<br>narrow grid up: "
        + df["narrow_grid_up"].astype(str)
    )

    # Hover-информация для narrow_grid_down
    df["hovertext_narrow_grid_down"] = (
        "Дата: "
        + df["timestamp"].apply(dt_str)
        + "<br>narrow grid down: "
        + df["narrow_grid_down"].astype(str)
    )

    # Hover-информация для wide_grid_up
    df["hovertext_wide_grid_up"] = (
        "Дата: "
        + df["timestamp"].apply(dt_str)
        + "<br>wide grid up: "
        + df["wide_grid_up"].astype(str)
    )

    # Hover-информация для wide_grid_down
    df["hovertext_wide_grid_down"] = (
        "Дата: "
        + df["timestamp"].apply(dt_str)
        + "<br>wide grid down: "
        + df["wide_grid_down"].astype(str)
    )

    # Рисуем линию avg
    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["avg"],
            mode="lines+markers",
            name="avg",
            line=dict(color="orange"),
            hovertext=df["hovertext_avg"],
        )
    )

    # Рисуем линию narrow_grid_up
    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["narrow_grid_up"],
            mode="lines+markers",
            name="narrow grid up",
            line=dict(color="orange"),
            hovertext=df["hovertext_narrow_grid_up"],
        )
    )

    # Рисуем линию narrow_grid_down
    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["narrow_grid_down"],
            mode="lines+markers",
            name="narrow grid down",
            line=dict(color="orange"),
            hovertext=df["hovertext_narrow_grid_down"],
        )
    )

    # Рисуем линию wide_grid_up
    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["wide_grid_up"],
            mode="lines+markers",
            name="wide grid up",
            line=dict(color="orange"),
            hovertext=df["hovertext_wide_grid_up"],
        )
    )

    # Рисуем линию wide_grid_down
    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["wide_grid_down"],
            mode="lines+markers",
            name="wide grid down",
            line=dict(color="orange"),
            hovertext=df["hovertext_wide_grid_down"],
        )
    )

    return fig
