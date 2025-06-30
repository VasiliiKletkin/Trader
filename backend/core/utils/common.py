import inspect


def get_all_init_args(cls):
    params = {}
    for base in cls.__mro__:
        if "__init__" in base.__dict__:
            sig = inspect.signature(base.__init__)
            for k, v in sig.parameters.items():
                if (
                    k not in ("self", "args", "kwargs")
                    and v.default is not inspect.Parameter.empty
                ):
                    params[k] = v.default
    return params
