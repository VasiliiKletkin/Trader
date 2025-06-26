import pandas as pd
import plotly.graph_objs as go
from dash import Input, Output, State, dcc, html
from django_plotly_dash import DjangoDash
from exchanges.models import Candle, CandleSource
from django.utils.timezone import localtime

app = DjangoDash("CandleSource")

app.layout = html.Div(
    [
        dcc.Graph(id="candlestick-chart"),
        dcc.Store(id="candle-source-id", data=None),
        dcc.Interval(
            id="interval-component-source",
            interval=60 * 1000,
            n_intervals=0,
        ),
    ]
)


@app.callback(
    Output("candlestick-chart", "figure"),
    Input("interval-component-source", "n_intervals"),
    State("candle-source-id", "data"),
)
def update_chart(n_intervals, candle_source_id):
    if not candle_source_id:
        return go.Figure()

    candle_source = CandleSource.objects.get(id=candle_source_id)
    candles = Candle.objects.filter(candle_source=candle_source).order_by("-timestamp")[
        :200
    ]

    if not candles.exists():
        return go.Figure()

    df = pd.DataFrame.from_records(
        candles.values("timestamp", "open", "high", "low", "close")
    )

    # Преобразуем время в локальное (на основе Django TIME_ZONE)
    df["timestamp"] = df["timestamp"].apply(localtime)

    fig = go.Figure(
        data=[
            go.Candlestick(
                x=df["timestamp"],
                open=df["open"],
                close=df["close"],
                high=df["high"],
                low=df["low"],
            )
        ]
    )

    fig.update_layout(
        title="Свечной график",
        xaxis_title="Время",
        yaxis_title="Цена",
        height=500,
        xaxis_rangeslider_visible=False,
    )

    return fig
