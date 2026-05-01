import pandas as pd
import plotly.graph_objs as go
from dash import Input, Output, dcc, html
from django.utils import timezone
from django_plotly_dash import DjangoDash

from core.utils.charts import (
    create_date_picker_range,
    parse_date_range,
    register_date_preset_callbacks,
)
from traders.domain import RenkoBrick
from traders.models import Trader

app = DjangoDash("RenkoStrategy")

app.layout = html.Div(
    [
        create_date_picker_range(),
        dcc.Graph(id="brick-chart"),
        dcc.Store(id="trader-id", data=None),
    ]
)

register_date_preset_callbacks(app)


@app.callback(
    Output("brick-chart", "figure"),
    [
        Input("trader-id", "data"),
        Input("date-range-picker", "start_date"),
        Input("date-range-picker", "end_date"),
    ],
)
def update_graph(trader_id, start_date_str, end_date_str):
    start_date, end_date = parse_date_range(start_date_str, end_date_str)

    fig = go.Figure()
    fig.update_layout(
        title="График кирпичей Ренко",
        xaxis_title="Индекс кирпича",
        yaxis_title="Цена",
        xaxis_rangeslider_visible=False,
    )

    try:
        trader = Trader.objects.select_related(
            "exchange_client__exchange",
            "strategy",
            "risk_manager",
            "candle_source__trading_pair__exchange",
            "candle_source__trading_pair",
        ).get(pk=trader_id)
    except Trader.DoesNotExist:
        return fig

    domain_trader = trader.instantiate()
    domain_trader.load_state(trader.data)
    bricks: list[RenkoBrick] = domain_trader.strategy.bricks

    if not bricks:
        return fig

    df = pd.DataFrame([brick.model_dump(mode="json") for brick in bricks])
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["timestamp"] = df["timestamp"].apply(timezone.localtime)
    df = df[(df["timestamp"] >= start_date) & (df["timestamp"] <= end_date)]

    df["index"] = range(len(df))
    df["color"] = (
        df["type"].map({"up": "green", "down": "red", "first": "gray"}).fillna("gray")
    )

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
