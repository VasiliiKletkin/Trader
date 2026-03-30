class Registry:
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls._registry = {}

    @classmethod
    def register(cls, target_cls):
        """Регистрирует класс в реестре. Может использоваться как декоратор."""
        cls._registry[target_cls.__name__] = target_cls
        return target_cls

    @classmethod
    def get_choices(cls):
        return [(name, name) for name in cls._registry]

    @classmethod
    def get_class(cls, name):
        try:
            return cls._registry[name]
        except KeyError as err:
            raise ValueError(f"Класс '{name}' не найден в {cls.__name__}.") from err
