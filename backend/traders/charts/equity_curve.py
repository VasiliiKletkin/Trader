import pandas as pd
import plotly.graph_objects as go
from dash import Output, State, dcc, html, Input
from django_plotly_dash import DjangoDash
from traders.models import Trader

app = DjangoDash("EquityCurveChart")
app.layout = html.Div(
    [
        dcc.Graph(id="equity-curve-chart"),
        dcc.Store(id="trader-id", data=None),
    ]
)


@app.callback(
    Output("equity-curve-chart", "figure"),
    Input("trader-id", "data"),
)
def update_equity_curve(trader_id):
    if not trader_id:
        return go.Figure()

    trader = Trader.objects.get(id=trader_id)
    equity_data = trader.get_equity_curve()

    if not equity_data:
        return go.Figure()

    df = pd.DataFrame(equity_data)
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["cumulative_pnl"],
            mode="lines+markers",
            name="Equity Curve",
            line=dict(color="blue"),
        )
    )

    fig.update_layout(
        title="Кривая капитала трейдера",
        xaxis_title="Время",
        yaxis_title="Капитал",
        height=600,
        xaxis_rangeslider_visible=False,
    )

    return fig
