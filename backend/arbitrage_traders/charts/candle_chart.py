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
    """Пустой figure с тремя subplot'ами и secondary Y для объёмов."""
    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        row_heights=[0.35, 0.35, 0.30],
        subplot_titles=("Первая биржа", "Вторая биржа", "Соотношение цен"),
        specs=[
            [{"secondary_y": True}],
            [{"secondary_y": True}],
            [{"secondary_y": False}],
        ],
    )
    fig.update_layout(
        title="Арбитражный свечной график",
        height=1000,
        xaxis_rangeslider_visible=False,
        xaxis2_rangeslider_visible=False,
        xaxis3_rangeslider_visible=False,
        legend={"x": 0, "y": 1},
    )
    return fig


def _add_candlestick(fig, candles_qs, row):
    """Добавить свечной график и объёмы на subplot. Возвращает DataFrame."""
    df = pd.DataFrame(
        list(candles_qs.values("timestamp", "open", "high", "low", "close", "volume"))
    )
    if df.empty:
        return df

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
        secondary_y=False,
    )
    fig.add_trace(
        go.Bar(
            x=df["timestamp"],
            y=df["volume"],
            name="Volume",
            marker_color="rgba(100, 149, 237, 0.3)",
            showlegend=False,
        ),
        row=row,
        col=1,
        secondary_y=True,
    )
    fig.update_yaxes(
        showgrid=False,
        range=[0, df["volume"].max() * 4],
        row=row,
        col=1,
        secondary_y=True,
    )
    return df


def _add_ratio_chart(fig, left_df, right_df, row):
    """Добавить график соотношения цен (left / right) на subplot."""
    merged = pd.merge(
        left_df[["timestamp", "close"]],
        right_df[["timestamp", "close"]],
        on="timestamp",
        suffixes=("_left", "_right"),
    )
    if merged.empty:
        return

    merged["ratio"] = merged["close_left"] / merged["close_right"]
    fig.add_trace(
        go.Scatter(
            x=merged["timestamp"],
            y=merged["ratio"],
            mode="lines",
            name="Left / Right",
            line={"color": "#636EFA", "width": 1.5},
            showlegend=False,
        ),
        row=row,
        col=1,
    )
    fig.add_hline(y=1.0, line_dash="dash", line_color="gray", row=row, col=1)


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
                f"id{p.pk} CLOSE|{p.get_close_reason_display()}|PNL: {round(p.pnl, 2)}"
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

    left_df = _add_candlestick(
        fig,
        trader.left_candle_source.get_candles(start=start_date, end=end_date),
        row=1,
    )
    right_df = _add_candlestick(
        fig,
        trader.right_candle_source.get_candles(start=start_date, end=end_date),
        row=2,
    )

    if (
        left_df is not None
        and right_df is not None
        and not left_df.empty
        and not right_df.empty
    ):
        _add_ratio_chart(fig, left_df, right_df, row=3)

    positions = trader.positions.filter(
        opened_at__range=(start_date, end_date),
    ).order_by("opened_at")
    _add_position_markers(fig, positions)

    fig.update_yaxes(title_text="Цена", row=1, col=1, secondary_y=False)
    fig.update_yaxes(title_text="Объём", row=1, col=1, secondary_y=True)
    fig.update_yaxes(title_text="Цена", row=2, col=1, secondary_y=False)
    fig.update_yaxes(title_text="Объём", row=2, col=1, secondary_y=True)
    fig.update_yaxes(title_text="Соотношение", row=3, col=1)
    fig.update_xaxes(title_text="Время", row=3, col=1)

    return fig
