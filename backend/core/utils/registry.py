class Registry:
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls._registry = {}

    @classmethod
    def register(cls, target_cls):
        cls._registry[target_cls.__name__] = target_cls

    @classmethod
    def get_choices(cls):
        return [(name, name) for name in cls._registry]

    @classmethod
    def get_class(cls, name):
        try:
            return cls._registry[name]
        except KeyError:
            raise ValueError(f"Class '{name}' not found in {cls.__name__}.")
