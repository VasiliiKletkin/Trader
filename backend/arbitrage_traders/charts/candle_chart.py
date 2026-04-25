from decimal import Decimal

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, dcc, html
from django.db.models import FloatField
from django.db.models.functions import Cast
from django.utils import timezone
from django.utils.timezone import localtime
from django_plotly_dash import DjangoDash
from plotly.subplots import make_subplots

from arbitrage_traders.models import ArbitrageTrader
from arbitrage_traders.schemas import ArbitragePositionType, ArbitrageSignalType
from core.utils.charts import (
    create_date_picker_range,
    parse_date_range,
    register_date_preset_callbacks,
)
from core.utils.common import (
    dt_str,
    format_amount,
    format_fee,
    format_pnl,
    format_price,
    format_spread,
)
from exchange_clients.schemas import OrderSide

app = DjangoDash("ArbitrageCandleChart")

app.layout = html.Div(
    [
        create_date_picker_range(),
        dcc.Store(id="trader-id", data=None),
        dcc.Graph(id="arbitrage-candle-chart"),
        dcc.Graph(id="arbitrage-equity-curve-chart"),
        dcc.Graph(id="arbitrage-lag-chart"),
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
        row_heights=[0.30, 0.35, 0.35],
        subplot_titles=("Соотношение цен", "Первая биржа", "Вторая биржа"),
        specs=[
            [{"secondary_y": False}],
            [{"secondary_y": True}],
            [{"secondary_y": True}],
        ],
    )
    fig.update_layout(
        title="Арбитражный свечной график",
        height=1300,
        xaxis_rangeslider_visible=False,
        xaxis2_rangeslider_visible=False,
        xaxis3_rangeslider_visible=False,
        legend={"x": 0, "y": 1},
    )
    return fig


def _add_candlestick(fig, candles_qs, row):
    """Добавить свечной график и объёмы на subplot. Возвращает DataFrame."""
    candles_qs = candles_qs.annotate(
        open_f=Cast("open", FloatField()),
        high_f=Cast("high", FloatField()),
        low_f=Cast("low", FloatField()),
        close_f=Cast("close", FloatField()),
        volume_f=Cast("volume", FloatField()),
    ).values("timestamp", "open_f", "high_f", "low_f", "close_f", "volume_f")

    df = pd.DataFrame(list(candles_qs))
    if df.empty:
        return df

    df.rename(
        columns={
            "open_f": "open",
            "high_f": "high",
            "low_f": "low",
            "close_f": "close",
            "volume_f": "volume",
        },
        inplace=True,
    )
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


def _add_signal_markers(fig, signals):
    """Добавить маркеры сигналов на все три графика."""
    signal_styles = {
        ArbitrageSignalType.BUY: {"color": "green", "symbol": "star", "size": 10},
        ArbitrageSignalType.SELL: {"color": "red", "symbol": "star", "size": 10},
        ArbitrageSignalType.WAIT: {"color": "gray", "symbol": "circle-open", "size": 5},
    }
    for signal_type, marker in signal_styles.items():
        typed = [
            s
            for s in signals
            if s["left_type"] == signal_type and s["left_price"] and s["right_price"]
        ]
        if not typed:
            continue
        name = f"Signal {signal_type.label}"
        timestamps = [localtime(s["timestamp"]) for s in typed]
        hover = [
            (
                f"{signal_type.label}<br>"
                f"Spread: {format_spread(s['left_price'] / s['right_price'])}<br>"
                f"L: {format_price(s['left_price'])}<br>"
                f"R: {format_price(s['right_price'])}"
            )
            for s in typed
        ]
        for row, y_values in [
            (2, [float(s["left_price"]) for s in typed]),
            (3, [float(s["right_price"]) for s in typed]),
        ]:
            fig.add_trace(
                go.Scatter(
                    x=timestamps,
                    y=y_values,
                    mode="markers",
                    name=name,
                    marker=marker,
                    hovertext=hover,
                    legendgroup=name.lower(),
                    showlegend=(row == 2),
                ),
                row=row,
                col=1,
            )


def _add_position_flags(fig, positions):
    """Флаги входа/выхода позиций на график соотношения цен (row=1)."""
    entries = []
    exits = []
    for pos in positions:
        if pos.left_open_price and pos.right_open_price:
            entries.append(pos)
        if pos.closed_at and pos.left_close_price and pos.right_close_price:
            exits.append(pos)

    if entries:
        fig.add_trace(
            go.Scatter(
                x=[localtime(p.opened_at) for p in entries],
                y=[float(p.left_open_price / p.right_open_price) for p in entries],
                mode="markers",
                name="Вход в позицию",
                marker={"color": "green", "symbol": "arrow-bar-up", "size": 14},
                hovertext=[
                    f"#{p.pk} вход<br>"
                    f"L: {format_price(p.left_open_price)} / "
                    f"R: {format_price(p.right_open_price)} = "
                    f"{format_spread(p.left_open_price / p.right_open_price)}"
                    for p in entries
                ],
                legendgroup="position-entry",
            ),
            row=1,
            col=1,
        )

    if exits:
        fig.add_trace(
            go.Scatter(
                x=[localtime(p.closed_at) for p in exits],
                y=[float(p.left_close_price / p.right_close_price) for p in exits],
                mode="markers",
                name="Выход из позиции",
                marker={"color": "red", "symbol": "arrow-bar-down", "size": 14},
                hovertext=[
                    f"#{p.pk} выход<br>"
                    f"L: {format_price(p.left_close_price)} / "
                    f"R: {format_price(p.right_close_price)} = "
                    f"{format_spread(p.left_close_price / p.right_close_price)}"
                    for p in exits
                ],
                legendgroup="position-exit",
            ),
            row=1,
            col=1,
        )


def _add_order_markers(fig, orders):
    """Добавить маркеры ордеров на свечные subplot'ы."""
    if not orders:
        return

    order_styles = {
        "buy": {"color": "green", "symbol": "triangle-up", "size": 12},
        "sell": {"color": "red", "symbol": "triangle-down", "size": 12},
    }
    for side, marker in order_styles.items():
        side_orders = [o for o in orders if o.left_order.side == side]
        if not side_orders:
            continue
        name = f"Order {side.upper()}"
        for row, order_attr in [(2, "left_order"), (3, "right_order")]:
            fig.add_trace(
                go.Scatter(
                    x=[
                        localtime(getattr(o, order_attr).timestamp) for o in side_orders
                    ],
                    y=[float(getattr(o, order_attr).price) for o in side_orders],
                    mode="markers",
                    name=name,
                    marker=marker,
                    hovertext=[
                        f"#{getattr(o, order_attr).exchange_order_id} "
                        f"{getattr(o, order_attr).get_side_display()} "
                        f"{format_amount(getattr(o, order_attr).amount)} "
                        f"@ {format_price(getattr(o, order_attr).price)} "
                        f"fee: {format_fee(getattr(o, order_attr).fee)}"
                        for o in side_orders
                    ],
                    legendgroup=name.lower(),
                    showlegend=(row == 2),
                ),
                row=row,
                col=1,
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
        "left_candle_source__exchange",
        "left_candle_source__trading_pair",
        "right_candle_source__exchange",
        "right_candle_source__trading_pair",
        "left_exchange_client",
        "right_exchange_client",
    ).get(id=trader_id)

    fig.layout.annotations[1].text = str(trader.left_exchange_client)
    fig.layout.annotations[2].text = str(trader.right_exchange_client)

    left_df = _add_candlestick(
        fig,
        trader.left_candle_source.get_candles(start=start_date, end=end_date),
        row=2,
    )
    right_df = _add_candlestick(
        fig,
        trader.right_candle_source.get_candles(start=start_date, end=end_date),
        row=3,
    )

    if (
        left_df is not None
        and right_df is not None
        and not left_df.empty
        and not right_df.empty
    ):
        _add_ratio_chart(fig, left_df, right_df, row=1)

    signals = list(
        trader.signals.filter(
            timestamp__range=(start_date, end_date),
        )
        .order_by("timestamp")
        .values("timestamp", "left_type", "left_price", "right_price")
    )
    _add_signal_markers(fig, signals)

    orders = list(
        trader.orders.filter(
            left_order__timestamp__range=(start_date, end_date),
        ).select_related("left_order", "right_order")
    )
    _add_order_markers(fig, orders)

    positions = list(
        trader.positions.filter(
            opened_at__range=(start_date, end_date),
        ).order_by("opened_at")
    )
    _add_position_flags(fig, positions)

    fig.update_yaxes(title_text="Соотношение", row=1, col=1)
    fig.update_yaxes(title_text="Цена", row=2, col=1, secondary_y=False)
    fig.update_yaxes(title_text="Объём", row=2, col=1, secondary_y=True)
    fig.update_yaxes(title_text="Цена", row=3, col=1, secondary_y=False)
    fig.update_yaxes(title_text="Объём", row=3, col=1, secondary_y=True)
    fig.update_xaxes(title_text="Время", row=3, col=1)

    return fig


@app.callback(
    Output("arbitrage-equity-curve-chart", "figure"),
    [
        Input("trader-id", "data"),
        Input("date-range-picker", "start_date"),
        Input("date-range-picker", "end_date"),
    ],
)
def update_equity_curve(trader_id, start_date_str, end_date_str):
    start_date, end_date = parse_date_range(start_date_str, end_date_str)

    fig = go.Figure()
    fig.update_layout(
        title="Кривая профита на позициях",
        xaxis_title="Время",
        yaxis_title="Профит",
        xaxis_rangeslider_visible=False,
        autosize=True,
    )

    if not trader_id:
        return fig

    try:
        trader = ArbitrageTrader.objects.get(id=trader_id)
    except ArbitrageTrader.DoesNotExist:
        return fig

    positions = list(
        trader.closed_positions.filter(
            closed_at__range=(start_date, end_date),
        )
        .annotate(computed_pnl=ArbitrageTrader.theoretical_pnl_annotation())
        .order_by("closed_at")
        .values("closed_at", "computed_pnl")
    )

    if not positions:
        return fig

    cumulative_pnl = Decimal("0")
    records = []
    for pos in positions:
        pnl = pos["computed_pnl"] or Decimal("0")
        cumulative_pnl += pnl
        records.append(
            {
                "timestamp": pos["closed_at"],
                "pnl": float(pnl),
                "cumulative_pnl": float(cumulative_pnl),
            }
        )

    df = pd.DataFrame(records)
    df["timestamp"] = pd.to_datetime(df["timestamp"]).apply(timezone.localtime)

    df["hovertext"] = [
        f"Дата: {dt_str(row['timestamp'])}<br>"
        f"PnL: {format_pnl(row['pnl'])}<br>"
        f"Кумулятивный: {format_pnl(row['cumulative_pnl'])}"
        for _, row in df.iterrows()
    ]

    colors = ["green" if row["pnl"] >= 0 else "red" for _, row in df.iterrows()]

    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["cumulative_pnl"],
            mode="lines+markers",
            name="Equity Curve",
            line={"color": "blue"},
            marker={"color": colors, "size": 6},
            hovertext=df["hovertext"],
        )
    )

    if len(df) >= 2:
        x = df["timestamp"].astype(np.int64).to_numpy()
        y = df["cumulative_pnl"].to_numpy()
        m, b = np.polyfit(x, y, 1)
        y_pred = m * x + b
        ss_res = ((y - y_pred) ** 2).sum()
        ss_tot = ((y - y.mean()) ** 2).sum()
        r2 = 1.0 - ss_res / ss_tot if ss_tot else 0.0

        fig.add_trace(
            go.Scatter(
                x=df["timestamp"],
                y=y_pred,
                mode="lines",
                name="Тренд",
                line={"color": "red", "dash": "dash"},
                hoverinfo="skip",
            )
        )
        fig.add_annotation(
            xref="paper",
            yref="paper",
            x=0.01,
            y=0.99,
            xanchor="left",
            yanchor="top",
            text=f"R² = {format_spread(r2)}",
            showarrow=False,
            bgcolor="rgba(255,255,255,0.8)",
        )

    return fig


@app.callback(
    Output("arbitrage-lag-chart", "figure"),
    [
        Input("trader-id", "data"),
        Input("date-range-picker", "start_date"),
        Input("date-range-picker", "end_date"),
    ],
)
def update_lag_chart(trader_id, start_date_str, end_date_str):
    start_date, end_date = parse_date_range(start_date_str, end_date_str)

    fig = go.Figure()
    fig.update_layout(
        title="График задержки лага ордеров",
        xaxis_title="Время ордера",
        yaxis_title="Лаг (секунды)",
        xaxis_rangeslider_visible=False,
        autosize=True,
        legend={"x": 0, "y": 1},
    )

    if not trader_id:
        return fig

    try:
        trader = ArbitrageTrader.objects.get(id=trader_id)
    except ArbitrageTrader.DoesNotExist:
        return fig

    orders = list(
        trader.orders.filter(
            left_order__timestamp__range=(start_date, end_date),
        )
        .select_related("left_order", "right_order", "position")
        .order_by("left_order__timestamp")
    )

    if not orders:
        return fig

    left_records = []
    right_records = []
    for order in orders:
        position = order.position
        for rec_list, exch_order, position_type in [
            (left_records, order.left_order, position.left_type),
            (right_records, order.right_order, position.right_type),
        ]:
            is_close = (
                position_type == ArbitragePositionType.LONG
                and exch_order.side == OrderSide.SELL
            ) or (
                position_type == ArbitragePositionType.SHORT
                and exch_order.side == OrderSide.BUY
            )
            ref_time = position.closed_at if is_close else position.opened_at
            if ref_time is None:
                continue
            lag = (exch_order.timestamp - ref_time).total_seconds()
            rec_list.append(
                {
                    "timestamp": exch_order.timestamp,
                    "lag_seconds": lag,
                    "order_id": exch_order.pk,
                    "kind": "закрытие" if is_close else "открытие",
                }
            )

    for records, name, color in [
        (left_records, "Left", "red"),
        (right_records, "Right", "blue"),
    ]:
        if not records:
            continue
        df = pd.DataFrame(records)
        df["timestamp"] = pd.to_datetime(df["timestamp"]).apply(timezone.localtime)
        df["hovertext"] = [
            f"Order ID: {row['order_id']}<br>"
            f"Тип: {row['kind']}<br>"
            f"Время: {dt_str(row['timestamp'])}<br>"
            f"Лаг: {round(row['lag_seconds'], 2)} сек"
            for _, row in df.iterrows()
        ]
        fig.add_trace(
            go.Scatter(
                x=df["timestamp"],
                y=df["lag_seconds"],
                mode="lines+markers",
                name=f"Лаг {name}",
                marker={"color": color, "size": 8},
                line={"color": color, "width": 2},
                hovertext=df["hovertext"],
            )
        )

    return fig
