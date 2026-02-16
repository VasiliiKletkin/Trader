import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, dcc, html
from django.utils.timezone import localtime
from django_plotly_dash import DjangoDash
from plotly.subplots import make_subplots

from arbitrage_traders.models import ArbitrageTrader
from core.utils.charts import (
    create_date_picker_range,
    parse_date_range,
    register_date_preset_callbacks,
)

app = DjangoDash("ArbitrageCandleChart")

app.layout = html.Div(
    [
        create_date_picker_range(),
        dcc.Store(id="trader-id", data=None),
        dcc.Graph(id="arbitrage-candle-chart"),
    ]
)

register_date_preset_callbacks(app)


def _create_empty_figure():
    """Пустой figure с двумя subplot'ами."""
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
    return fig


def _add_candlestick(fig, candles_qs, row):
    """Добавить свечной график на subplot."""
    df = pd.DataFrame(
        list(candles_qs.values("timestamp", "open", "high", "low", "close"))
    )
    if df.empty:
        return

    df["timestamp"] = pd.to_datetime(df["timestamp"]).apply(localtime)
    fig.add_trace(
        go.Candlestick(
            x=df["timestamp"],
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            showlegend=False,
        ),
        row=row,
        col=1,
    )


def _add_markers(fig, items, time_field, price_fields, name, marker, hover_fn):
    """Добавить маркеры на оба subplot'а."""
    for row, price_field in price_fields:
        fig.add_trace(
            go.Scatter(
                x=[localtime(getattr(p, time_field)) for p in items],
                y=[float(getattr(p, price_field)) for p in items],
                mode="markers",
                name=name,
                marker=marker,
                hovertext=[hover_fn(p) for p in items],
                legendgroup=name.lower(),
                showlegend=(row == 1),
            ),
            row=row,
            col=1,
        )


def _add_position_markers(fig, positions):
    """Добавить маркеры открытия и закрытия позиций на оба subplot'а."""
    opened = list(positions.filter(opened_at__isnull=False))
    if opened:
        _add_markers(
            fig,
            opened,
            time_field="opened_at",
            price_fields=[(1, "left_open_price"), (2, "right_open_price")],
            name="Open",
            marker={"color": "blue", "symbol": "circle", "size": 16},
            hover_fn=lambda p: f"id{p.pk} OPEN {p.get_type_display()}",
        )

    closed = list(positions.filter(closed_at__isnull=False))
    if closed:
        _add_markers(
            fig,
            closed,
            time_field="closed_at",
            price_fields=[(1, "left_close_price"), (2, "right_close_price")],
            name="Close",
            marker={"color": "orange", "symbol": "x", "size": 16},
            hover_fn=lambda p: (
                f"id{p.pk} CLOSE|{p.get_close_reason_display()}"
                f"|PNL: {round(p.pnl, 2)}"
            ),
        )


@app.callback(
    Output("arbitrage-candle-chart", "figure"),
    [
        Input("trader-id", "data"),
        Input("date-range-picker", "start_date"),
        Input("date-range-picker", "end_date"),
    ],
)
def update_chart(trader_id, start_date_str, end_date_str):
    start_date, end_date = parse_date_range(start_date_str, end_date_str)
    fig = _create_empty_figure()

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

    fig.layout.annotations[0].text = str(trader.left_exchange_client)
    fig.layout.annotations[1].text = str(trader.right_exchange_client)

    _add_candlestick(
        fig,
        trader.left_candle_source.get_candles(start=start_date, end=end_date),
        row=1,
    )
    _add_candlestick(
        fig,
        trader.right_candle_source.get_candles(start=start_date, end=end_date),
        row=2,
    )

    positions = trader.positions.filter(
        opened_at__range=(start_date, end_date),
    ).order_by("opened_at")
    _add_position_markers(fig, positions)

    fig.update_yaxes(title_text="Цена", row=1, col=1)
    fig.update_yaxes(title_text="Цена", row=2, col=1)
    fig.update_xaxes(title_text="Время", row=2, col=1)

    return fig
