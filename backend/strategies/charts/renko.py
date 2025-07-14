from datetime import timedelta

import pandas as pd
import plotly.graph_objs as go
from dash import Input, Output, State, dcc, html
from django.utils import timezone
from django_plotly_dash import DjangoDash
from traders.models import Trader

app = DjangoDash("RenkoStrategy")

app.layout = html.Div(
    [
        dcc.Graph(id="brick-chart"),
        dcc.Store(id="trader-id", data=None),
        # dcc.Interval(
        #     id="interval-component-strategy",
        #     interval=60 * 1000,
        #     n_intervals=0,
        # ),
    ]
)


@app.callback(
    Output("brick-chart", "figure"),
    # Input("interval-component-strategy", "n_intervals"),
    Input("trader-id", "data"),
)
def update_graph(trader_id):
    end_date = timezone.now()
    start_date = end_date - timedelta(days=30)

    fig = go.Figure()
    fig.update_layout(
        title="График кирпичей Ренко",
        xaxis_title="Индекс кирпича",
        yaxis_title="Цена",
        xaxis_rangeslider_visible=False,
    )

    if not trader_id:
        return fig

    trader = Trader.objects.get(pk=trader_id)
    bricks = trader.data.get("bricks", [])

    if not bricks:
        return fig

    df = pd.DataFrame(bricks)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["timestamp"] = df["timestamp"].apply(timezone.localtime)
    df = df[(df["timestamp"] >= start_date) & (df["timestamp"] <= end_date)]

    df["index"] = range(len(df))
    df["color"] = (
        df["type"].map({"up": "green", "down": "red", "first": "gray"}).fillna("gray")
    )

    # Преобразуем open/close/high/low к float для арифметики
    for col in ["open", "close", "high", "low"]:
        if col in df:
            df[col] = df[col].astype(float)

    df["height"] = (df["close"] - df["open"]).abs()
    df["bar_base"] = df[["open", "close"]].min(axis=1)

    df["hovertext"] = (
        "Дата: "
        + df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
        + "<br>Open: "
        + df["open"].astype(str)
        + "<br>Close: "
        + df["close"].astype(str)
    )
    fig = go.Figure(
        data=[
            go.Bar(
                x=df["index"],
                y=df["height"],
                base=df["bar_base"],
                marker_color=df["color"],
                hovertext=df["hovertext"],
            )
        ]
    )
    return fig
