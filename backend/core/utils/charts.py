import contextlib
from datetime import date, timedelta

import dash
import pandas as pd
from dash import Input, Output, dcc, html
from dash.exceptions import PreventUpdate
from django.utils import timezone

DEFAULT_DAYS = 30

PRESETS = [
    ("7Д", "7d", 7),
    ("14Д", "14d", 14),
    ("30Д", "30d", 30),
    ("90Д", "90d", 90),
    ("1Г", "1y", 365),
    ("Всё", "all", None),
]

_BUTTON_BASE = {
    "border": "none",
    "borderRadius": "16px",
    "padding": "3px 12px",
    "fontSize": "12px",
    "fontWeight": "500",
    "cursor": "pointer",
    "transition": "all 0.15s",
    "lineHeight": "1.6",
    "letterSpacing": "0.3px",
    "outline": "none",
}

_BUTTON_DEFAULT = {
    **_BUTTON_BASE,
    "backgroundColor": "#e9ecef",
    "color": "#495057",
}

_BUTTON_ACTIVE = {
    **_BUTTON_BASE,
    "backgroundColor": "#0d6efd",
    "color": "#ffffff",
}

_SEPARATOR = {
    "width": "1px",
    "alignSelf": "stretch",
    "backgroundColor": "#ced4da",
    "margin": "0 12px",
}


def _get_default_preset_key(days):
    """Найти ключ пресета по количеству дней."""
    for _label, key, preset_days in PRESETS:
        if preset_days == days:
            return key
    return None


def create_date_picker_range(picker_id="date-range-picker", days=DEFAULT_DAYS):
    """Создать DatePickerRange с пресет-кнопками."""
    default_end = date.today()
    default_start = default_end - timedelta(days=days)
    active_key = _get_default_preset_key(days)

    preset_buttons = [
        html.Button(
            label,
            id=f"{picker_id}-preset-{key}",
            n_clicks=0,
            style=_BUTTON_ACTIVE if key == active_key else _BUTTON_DEFAULT,
        )
        for label, key, _days in PRESETS
    ]

    return html.Div(
        [
            html.Div(
                dcc.DatePickerRange(
                    id=picker_id,
                    start_date=default_start,
                    end_date=default_end,
                    display_format="DD.MM.YYYY",
                    first_day_of_week=1,
                    style={"fontFamily": "inherit"},
                ),
                style={"marginRight": "auto"},
            ),
            html.Div(style=_SEPARATOR),
            html.Div(
                preset_buttons,
                style={"display": "flex", "gap": "4px", "marginLeft": "auto"},
            ),
        ],
        style={
            "display": "flex",
            "alignItems": "center",
            "padding": "6px 12px",
            "marginBottom": "12px",
            "backgroundColor": "#f8f9fa",
            "borderRadius": "8px",
            "border": "1px solid #dee2e6",
        },
    )


def register_date_preset_callbacks(app, picker_id="date-range-picker"):
    """Зарегистрировать callback пресет-кнопок для DatePickerRange."""

    @app.callback(
        [
            Output(picker_id, "start_date"),
            Output(picker_id, "end_date"),
        ]
        + [
            Output(f"{picker_id}-preset-{key}", "style")
            for _label, key, _days in PRESETS
        ],
        [
            Input(f"{picker_id}-preset-{key}", "n_clicks")
            for _label, key, _days in PRESETS
        ],
        prevent_initial_call=True,
    )
    def update_from_preset(*_args):
        triggered = dash.callback_context.triggered
        if not triggered:
            raise PreventUpdate
        triggered_id = triggered[0]["prop_id"].split(".")[0]

        end_date = date.today()
        for _label, key, preset_days in PRESETS:
            if triggered_id == f"{picker_id}-preset-{key}":
                if preset_days is None:
                    start_date = date(2020, 1, 1)
                else:
                    start_date = end_date - timedelta(days=preset_days)
                styles = [
                    _BUTTON_ACTIVE if k == key else _BUTTON_DEFAULT
                    for _l, k, _d in PRESETS
                ]
                return [start_date, end_date, *styles]

        raise PreventUpdate


def parse_date_range(start_date_str, end_date_str, days=DEFAULT_DAYS):
    """Парсинг дат из DatePickerRange. end_date включительно (+1 день)."""
    end = timezone.now()
    start = end - timedelta(days=days)

    if start_date_str:
        with contextlib.suppress(Exception):
            start = pd.to_datetime(start_date_str, utc=True)
    if end_date_str:
        with contextlib.suppress(Exception):
            end = pd.to_datetime(end_date_str, utc=True) + timedelta(days=1)

    return start, end
