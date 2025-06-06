import pandas as pd
import plotly.graph_objs as go
from dash import Input, Output, dcc, html
from django_plotly_dash import DjangoDash
from exchanges.models import Candle, CandleSource

app = DjangoDash("CandleSourceChart")

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
    try:
        candle_source = CandleSource.objects.get(id=candle_source_id)
        candles = Candle.objects.filter(candle_source=candle_source).order_by(
            "timestamp"
        )[:200]

        if not candles.exists():
            return go.Figure()

        df = pd.DataFrame.from_records(
            candles.values("timestamp", "open", "high", "low", "close")
        )

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
            title="Свечной график",
            xaxis_title="Время",
            yaxis_title="Цена",
            height=600,
            xaxis_rangeslider_visible=False,
        )

        return fig

    except Exception as e:
        return go.Figure().update_layout(title=f"Ошибка: {e}")
