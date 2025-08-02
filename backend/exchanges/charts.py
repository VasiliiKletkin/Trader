from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, dcc, html
from django.utils import timezone
from django_plotly_dash import DjangoDash
from exchanges.models import Candle
from exchange_clients.models import CandleSource

app = DjangoDash("CandleSource")

app.layout = html.Div(
    [
        dcc.Graph(id="candlestick-chart"),
        dcc.Store(id="candle-source-id", data=None),
    ]
)


@app.callback(
    Output("candlestick-chart", "figure"),
    Input("candle-source-id", "data"),
)
def update_chart(candle_source_id):
    end_date = timezone.now()
    start_date = end_date - timedelta(days=30)
    fig = go.Figure()

    fig.update_layout(
        title="Свечной график",
        xaxis_title="Время",
        yaxis_title="Цена",
        height=500,
        xaxis_rangeslider_visible=False,
    )

    if not candle_source_id:
        return fig

    candle_source = CandleSource.objects.get(id=candle_source_id)
    candles = Candle.objects.filter(
        exchange=candle_source.exchange_client.exchange,
        timeframe=candle_source.timeframe,
        trading_pair=candle_source.trading_pair,
        timestamp__range=(start_date, end_date),
    ).order_by("timestamp")

    if not candles.exists():
        return fig

    df_candles = pd.DataFrame.from_records(
        candles.values("timestamp", "open", "high", "low", "close")
    )
    # Преобразуем время в локальное (на основе Django TIME_ZONE)
    df_candles["timestamp"] = df_candles["timestamp"].apply(timezone.localtime)

    fig.add_trace(
        go.Candlestick(
            x=df_candles["timestamp"],
            open=df_candles["open"],
            close=df_candles["close"],
            high=df_candles["high"],
            low=df_candles["low"],
        )
    )
    return fig
