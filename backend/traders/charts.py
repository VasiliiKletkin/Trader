from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import plotly.graph_objs as go
from dash import Input, Output, State, dcc, html
from django.utils import timezone
from django.utils.timezone import localtime, make_aware
from django_plotly_dash import DjangoDash
from exchanges.models import Candle
from traders.models import Trader, TraderSignal

from core.utils.types import Timeframe

# app = DjangoDash("TraderCandles")

# app.layout = html.Div(
#     [
#         dcc.Store(id="candles-data"),
#         dcc.Graph(id="candlestick-chart"),
#     ]
# )


# @app.callback(
#     Output("candlestick-chart", "figure"),
#     Output("candles-data", "data"),
#     Input("candlestick-chart", "relayoutData"),
#     State("candles-data", "data"),
# )
# def update_graph(relayout_data, stored_data):
#     trader = Trader.objects.get(pk=1)

#     # если данных нет, загружаем последние 200 свечей
#     if not stored_data:
#         candles = Candle.objects.filter(
#             exchange=trader.exchange,
#             trading_pair=trader.trading_pair,
#             timeframe=trader.timeframe,
#         ).order_by("timestamp")[:200]
#         df = pd.DataFrame(
#             list(candles.values("timestamp", "open", "high", "low", "close"))
#         )
#     else:
#         df = pd.read_json(stored_data, convert_dates=["timestamp"])

#     # Если relayoutData содержит изменение оси X (zoom/pan)
#     if relayout_data and (
#         "xaxis.range[0]" in relayout_data or "xaxis.range" in relayout_data
#     ):
#         # Определи текущий диапазон по оси X
#         if "xaxis.range[0]" in relayout_data:
#             start = pd.to_datetime(relayout_data["xaxis.range[0]"])
#             end = pd.to_datetime(relayout_data["xaxis.range[1]"])
#         elif "xaxis.range" in relayout_data:
#             start = pd.to_datetime(relayout_data["xaxis.range"][0])
#             end = pd.to_datetime(relayout_data["xaxis.range"][1])
#         else:
#             start = df["timestamp"].min()
#             end = df["timestamp"].max()

#         # Если пользователь приблизился к началу данных, докачай старые свечи
#         if start <= df["timestamp"].min() + pd.Timedelta(
#             minutes=1
#         ):  # например, 1 минута запас
#             older_candles = Candle.objects.filter(
#                 exchange=trader.exchange,
#                 trading_pair=trader.trading_pair,
#                 timeframe=trader.timeframe,
#                 timestamp__lt=df["timestamp"].min(),
#             ).order_by("-timestamp")[
#                 :100
#             ]  # докачать 100 старых
#             if older_candles.exists():
#                 older_df = pd.DataFrame(
#                     list(
#                         older_candles.values(
#                             "timestamp", "open", "high", "low", "close"
#                         )
#                     )
#                 )
#                 df = (
#                     pd.concat([older_df, df], ignore_index=True)
#                     .drop_duplicates()
#                     .sort_values("timestamp")
#                 )

#         # Аналогично для докачки новых свечей с конца, если надо

#     fig = go.Figure(
#         data=[
#             go.Candlestick(
#                 x=df["timestamp"],
#                 open=df["open"],
#                 high=df["high"],
#                 low=df["low"],
#                 close=df["close"],
#             )
#         ]
#     )
#     fig.update_layout(
#         title="Candle Chart",
#         xaxis_title="Time",
#         yaxis_title="Price",
#         xaxis_rangeslider_visible=False,
#     )

#     return fig, df.to_json(date_format="iso")


app = DjangoDash("SignalChart")
app.layout = html.Div(
    [
        dcc.Graph(id="combined-chart"),
        dcc.Store(id="trader-id", data=None),
        dcc.Interval(
            id="interval-component",
            interval=60 * 1000,
            n_intervals=0,
        ),
        dcc.Store(id="chart-relayout-store"),
    ]
)


@app.callback(
    Output("chart-relayout-store", "data"),
    Input("combined-chart", "relayoutData"),
    State("chart-relayout-store", "data"),
)
def store_relayout_data(relayout_data, stored_data):
    if relayout_data and "xaxis.range[0]" in relayout_data:
        return relayout_data
    return stored_data


@app.callback(
    Output("combined-chart", "figure"),
    Input("interval-component", "n_intervals"),
    Input("chart-relayout-store", "data"),  # 👈 добавь этот Input
    State("trader-id", "data"),
)
def update_combined_chart(n_intervals, relayout_data, trader_id):
    if not trader_id:
        return go.Figure()

    trader = Trader.objects.get(id=trader_id)
    default_tfs_count = 200
    tf_delta = Timeframe(trader.candle_source.timeframe).timedelta()

    now = timezone.now()

    # ✅ Проверяем: пользователь двигал график?
    if (
        relayout_data
        and "xaxis.range[0]" in relayout_data
        and "xaxis.range[1]" in relayout_data
    ):
        try:
            start_date = make_aware(
                datetime.fromisoformat(relayout_data["xaxis.range[0]"])
            )
            end_date = make_aware(
                datetime.fromisoformat(relayout_data["xaxis.range[1]"])
            )
        except Exception:
            # fallback, если relayout_data повреждено
            end_date = now
            start_date = end_date - default_tfs_count * tf_delta
    else:
        # 👈 Только если график ещё не двигали — дефолтное значение
        end_date = now
        start_date = end_date - default_tfs_count * tf_delta

    candles = Candle.objects.filter(
        candle_source=trader.candle_source,
        timestamp__range=(start_date, end_date),
    ).order_by("timestamp")

    if not candles.exists():
        return go.Figure()

    df = pd.DataFrame.from_records(
        candles.values("timestamp", "open", "high", "low", "close")
    )

    df["timestamp"] = df["timestamp"].apply(localtime)

    # Получаем сигналы
    signals = TraderSignal.objects.filter(
        trader=trader,
        timestamp__range=(start_date, end_date),
    ).order_by("timestamp")

    buy_signals = signals.filter(type="buy")
    sell_signals = signals.filter(type="sell")

    fig = go.Figure()

    # Добавляем свечной график
    fig.add_trace(
        go.Candlestick(
            x=df["timestamp"],
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="Candles",
        )
    )

    # Добавляем сигналы "Buy"
    fig.add_trace(
        go.Scatter(
            x=[localtime(s.timestamp) for s in buy_signals],
            y=[s.price for s in buy_signals],
            mode="markers",
            name="Buy",
            marker=dict(color="green", symbol="triangle-up", size=20),
        )
    )

    # Добавляем сигналы "Sell"
    fig.add_trace(
        go.Scatter(
            x=[localtime(s.timestamp) for s in sell_signals],
            y=[s.price for s in sell_signals],
            mode="markers",
            name="Sell",
            marker=dict(color="red", symbol="triangle-down", size=20),
        )
    )

    # Настройки графика
    fig.update_layout(
        title="Свечной график с торговыми сигналами",
        xaxis_title="Время",
        yaxis_title="Цена",
        height=600,
        xaxis_rangeslider_visible=False,
        legend=dict(x=0, y=1),
    )

    return fig
