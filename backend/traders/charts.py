import pandas as pd
import plotly.graph_objs as go
from dash import Input, Output, State, dcc, html
from django.utils.timezone import localtime
from django_plotly_dash import DjangoDash
from exchanges.models import Candle
from traders.models import Trader, TraderSignal

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
    ]
)


@app.callback(
    Output("combined-chart", "figure"),
    Input("interval-component", "n_intervals"),
    State("trader-id", "data"),
)
def update_combined_chart(n_intervals, trader_id):
    if not trader_id:
        return go.Figure()
    trader = Trader.objects.get(id=trader_id)

    candles = Candle.objects.filter(candle_source=trader.candle_source).order_by(
        "-timestamp"
    )
    if not candles.exists():
        return go.Figure()

    # Получаем данные и сортируем
    df = pd.DataFrame.from_records(
        candles.values("timestamp", "open", "high", "low", "close")
    ).sort_values("timestamp")

    # Преобразуем время в локальное (на основе Django TIME_ZONE)
    df["timestamp"] = df["timestamp"].apply(localtime)

    # Получаем сигналы
    signals = TraderSignal.objects.filter(trader=trader).order_by("timestamp")
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
            marker=dict(color="green", symbol="triangle-up", size=10),
        )
    )

    # Добавляем сигналы "Sell"
    fig.add_trace(
        go.Scatter(
            x=[localtime(s.timestamp) for s in sell_signals],
            y=[s.price for s in sell_signals],
            mode="markers",
            name="Sell",
            marker=dict(color="red", symbol="triangle-down", size=10),
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
