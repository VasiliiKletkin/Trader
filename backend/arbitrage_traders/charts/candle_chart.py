from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, dcc, html
from django.utils import timezone
from django.utils.timezone import localtime
from django_plotly_dash import DjangoDash
from plotly.subplots import make_subplots

from arbitrage_traders.models import ArbitrageTrader
from arbitrage_traders.schemas import ArbitrageSignalType

app = DjangoDash("ArbitrageCandleChart")
app.layout = html.Div(
    [
        dcc.Graph(id="arbitrage-candle-chart"),
        dcc.Store(id="trader-id", data=None),
        dcc.Store(id="arbitrage-candle-date-range", data=None),
    ]
)


@app.callback(
    Output("arbitrage-candle-date-range", "data"),
    [
        Input("arbitrage-candle-chart", "relayoutData"),
    ],
    [
        State("arbitrage-candle-date-range", "data"),
    ],
)
def update_date_range(relayout_data, stored_range):
    if relayout_data:
        x0 = relayout_data.get("xaxis.range[0]")
        x1 = relayout_data.get("xaxis.range[1]")
        if x0 and x1:
            return {"start": x0, "end": x1}
        if relayout_data.get("xaxis.autorange"):
            return None
    return stored_range


@app.callback(
    Output("arbitrage-candle-chart", "figure"),
    [
        Input("trader-id", "data"),
        Input("arbitrage-candle-date-range", "data"),
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

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        subplot_titles=("Первая биржа", "Вторая биржа"),
    )
    fig.update_layout(
        title="Арбитражный свечной график",
        height=800,
        xaxis_rangeslider_visible=False,
        xaxis2_rangeslider_visible=False,
        legend={"x": 0, "y": 1},
    )

    if not trader_id:
        return fig

    trader = ArbitrageTrader.objects.select_related(
        "left_candle_source__exchange_client__exchange",
        "left_candle_source__trading_pair",
        "right_candle_source__exchange_client__exchange",
        "right_candle_source__trading_pair",
        "left_exchange_client",
        "right_exchange_client",
    ).get(id=trader_id)

    # Обновляем заголовки subplot'ов
    fig.layout.annotations[0].text = str(trader.left_exchange_client)
    fig.layout.annotations[1].text = str(trader.right_exchange_client)

    # Получаем свечи
    left_candles = trader.left_candle_source.get_candles(start=start_date, end=end_date)
    right_candles = trader.right_candle_source.get_candles(
        start=start_date, end=end_date
    )

    # Left candlestick
    df_left = pd.DataFrame(
        list(left_candles.values("timestamp", "open", "high", "low", "close"))
    )
    if not df_left.empty:
        df_left["timestamp"] = pd.to_datetime(df_left["timestamp"]).apply(localtime)
        fig.add_trace(
            go.Candlestick(
                x=df_left["timestamp"],
                open=df_left["open"],
                high=df_left["high"],
                low=df_left["low"],
                close=df_left["close"],
                name="Left Candles",
                showlegend=False,
            ),
            row=1,
            col=1,
        )

    # Right candlestick
    df_right = pd.DataFrame(
        list(right_candles.values("timestamp", "open", "high", "low", "close"))
    )
    if not df_right.empty:
        df_right["timestamp"] = pd.to_datetime(df_right["timestamp"]).apply(localtime)
        fig.add_trace(
            go.Candlestick(
                x=df_right["timestamp"],
                open=df_right["open"],
                high=df_right["high"],
                low=df_right["low"],
                close=df_right["close"],
                name="Right Candles",
                showlegend=False,
            ),
            row=2,
            col=1,
        )

    # Сигналы
    signals = trader.signals.filter(
        timestamp__range=(start_date, end_date),
    ).order_by("timestamp")

    buy_signals = [s for s in signals if s.left_type == ArbitrageSignalType.BUY]
    sell_signals = [s for s in signals if s.left_type == ArbitrageSignalType.SELL]

    # BUY сигналы на обоих графиках
    if buy_signals:
        fig.add_trace(
            go.Scatter(
                x=[localtime(s.timestamp) for s in buy_signals],
                y=[float(s.left_price) for s in buy_signals],
                mode="markers",
                name="BUY",
                marker={"color": "green", "symbol": "triangle-up", "size": 12},
                legendgroup="buy",
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=[localtime(s.timestamp) for s in buy_signals],
                y=[float(s.right_price) for s in buy_signals],
                mode="markers",
                name="BUY",
                marker={"color": "green", "symbol": "triangle-up", "size": 12},
                legendgroup="buy",
                showlegend=False,
            ),
            row=2,
            col=1,
        )

    # SELL сигналы на обоих графиках
    if sell_signals:
        fig.add_trace(
            go.Scatter(
                x=[localtime(s.timestamp) for s in sell_signals],
                y=[float(s.left_price) for s in sell_signals],
                mode="markers",
                name="SELL",
                marker={"color": "red", "symbol": "triangle-down", "size": 12},
                legendgroup="sell",
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=[localtime(s.timestamp) for s in sell_signals],
                y=[float(s.right_price) for s in sell_signals],
                mode="markers",
                name="SELL",
                marker={"color": "red", "symbol": "triangle-down", "size": 12},
                legendgroup="sell",
                showlegend=False,
            ),
            row=2,
            col=1,
        )

    # Позиции
    positions = trader.positions.filter(
        opened_at__range=(start_date, end_date),
    ).order_by("opened_at")

    # Открытие позиций
    opened_positions = positions.filter(opened_at__isnull=False)
    if opened_positions.exists():
        fig.add_trace(
            go.Scatter(
                x=[localtime(p.opened_at) for p in opened_positions],
                y=[float(p.left_open_price) for p in opened_positions],
                mode="markers",
                name="Open",
                marker={"color": "blue", "symbol": "circle", "size": 16},
                hovertext=[
                    f"id{p.pk} OPEN {p.get_type_display()}" for p in opened_positions
                ],
                legendgroup="open",
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=[localtime(p.opened_at) for p in opened_positions],
                y=[float(p.right_open_price) for p in opened_positions],
                mode="markers",
                name="Open",
                marker={"color": "blue", "symbol": "circle", "size": 16},
                hovertext=[
                    f"id{p.pk} OPEN {p.get_type_display()}" for p in opened_positions
                ],
                legendgroup="open",
                showlegend=False,
            ),
            row=2,
            col=1,
        )

    # Закрытие позиций
    closed_positions = positions.filter(closed_at__isnull=False)
    if closed_positions.exists():
        fig.add_trace(
            go.Scatter(
                x=[localtime(p.closed_at) for p in closed_positions],
                y=[float(p.left_close_price) for p in closed_positions],
                mode="markers",
                name="Close",
                marker={"color": "orange", "symbol": "x", "size": 16},
                hovertext=[
                    f"id{p.pk} CLOSE|PNL: {round(p.pnl, 2)}" for p in closed_positions
                ],
                legendgroup="close",
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=[localtime(p.closed_at) for p in closed_positions],
                y=[float(p.right_close_price) for p in closed_positions],
                mode="markers",
                name="Close",
                marker={"color": "orange", "symbol": "x", "size": 16},
                hovertext=[
                    f"id{p.pk} CLOSE|PNL: {round(p.pnl, 2)}" for p in closed_positions
                ],
                legendgroup="close",
                showlegend=False,
            ),
            row=2,
            col=1,
        )

    fig.update_yaxes(title_text="Цена", row=1, col=1)
    fig.update_yaxes(title_text="Цена", row=2, col=1)
    fig.update_xaxes(title_text="Время", row=2, col=1)

    return fig
