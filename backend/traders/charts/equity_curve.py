import pandas as pd
from django.utils.timezone import datetime, timedelta
import plotly.graph_objects as go
from dash import Output, dcc, html, Input
from django_plotly_dash import DjangoDash
from traders.models import Trader

app = DjangoDash("EquityCurveChart")
app.layout = html.Div(
    [
        dcc.Graph(id="trader-equity-curve-chart"),
        dcc.Store(id="trader-id", data=None),
    ]
)


@app.callback(
    Output("trader-equity-curve-chart", "figure"),
    Input("trader-id", "data"),
)
def update_equity_curve(trader_id):
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)

    fig = go.Figure()

    fig.update_layout(
        title="Кривая профита трейдера",
        xaxis_title="Время",
        yaxis_title="Профит",
        height=600,
        xaxis_rangeslider_visible=False,
    )
    if not trader_id:
        return fig

    trader = Trader.objects.get(id=trader_id)
    positions = (
        trader.get_closed_positions()
        .filter(opened_at__range=(start_date, end_date))
        .order_by("opened_at")
    )
    if not positions:
        return fig

    cumulative_pnl = 0.0
    equity_curve = []

    for pos in positions:
        pnl = pos.realized_pnl() or 0.0
        cumulative_pnl += pnl
        equity_curve.append(
            {
                "timestamp": pos.closed_at,
                "cumulative_pnl": cumulative_pnl,
            }
        )

    df = pd.DataFrame(equity_curve)
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["cumulative_pnl"],
            mode="lines+markers",
            name="Equity Curve",
            line=dict(color="blue"),
        )
    )

    return fig
