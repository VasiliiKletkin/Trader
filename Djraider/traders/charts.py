from django_plotly_dash import DjangoDash
from dash import dcc, html, Input, Output
import plotly.graph_objs as go
from traders.models import Trader
from candles.models import Candle
import pandas as pd

app = DjangoDash("TraderCandles")

app.layout = html.Div(
    [
        dcc.Graph(id="candlestick-chart"),
    ]
)


@app.callback(
    Output("candlestick-chart", "figure"),
)
def update_graph():
    trader = Trader.objects.get(pk=1)
    candles = Candle.objects.filter(
        exchange=trader.exchange,
        trading_pair=trader.trading_pair,
        timeframe=trader.timeframe,
    ).order_by("timestamp")[:200]

    if not candles.exists():
        return go.Figure()

    df = pd.DataFrame(list(candles.values("timestamp", "open", "high", "low", "close")))

    fig = go.Figure(
        data=[
            go.Candlestick(
                x=df["timestamp"],
                open=df["open"],
                high=df["high"],
                low=df["low"],
                close=df["close"],
            )
        ]
    )
    fig.update_layout(
        title="Candle Chart",
        xaxis_title="Time",
        yaxis_title="Price",
        xaxis_rangeslider_visible=False,
    )
    return fig
