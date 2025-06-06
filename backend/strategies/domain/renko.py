from .base import AbstractStrategy


class RenkoStrategy(AbstractStrategy):
    def __init__(self, brick_size: int):
        self.brick_size = brick_size

    async def handle_candle(self, candle):
        """Обработка новых свечей
        Args:
            candle (Candle): _description_
        """
        pass

    async def get_signal(self):
        pass
