import inspect
from datetime import datetime
from decimal import Decimal


def get_all_init_args(cls):
    params = {}
    for base in reversed(cls.__mro__):
        if "__init__" in base.__dict__:
            sig = inspect.signature(base.__init__)
            for k, v in sig.parameters.items():
                if (
                    k not in ("self", "args", "kwargs")
                    and v.default is not inspect.Parameter.empty
                ):
                    params[k] = v.default
    return params


def dt_str(dt: datetime) -> str:
    return dt.strftime("%d.%m.%Y %H:%M:%S")


def format_price(value: Decimal | float) -> str:
    """Форматирование цены: 2 знака после запятой."""
    return str(round(float(value), 2))


def format_amount(value: Decimal | float) -> str:
    """Форматирование количества актива: 8 знаков после запятой."""
    return str(round(float(value), 8))


def format_spread(value: Decimal | float) -> str:
    """Форматирование spread/ratio: 6 знаков после запятой."""
    return str(round(float(value), 6))


def format_fee(value: Decimal | float) -> str:
    """Форматирование комиссии: 4 знака после запятой."""
    return str(round(float(value), 4))


def format_pnl(value: Decimal | float) -> str:
    """Форматирование PnL: 2 знака после запятой."""
    return str(round(float(value), 2))
