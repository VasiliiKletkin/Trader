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

