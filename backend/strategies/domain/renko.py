from .base import AbstractStrategy


class RenkoStrategy(AbstractStrategy):
    def __init__(self, brick_size: int):
        self.brick_size = brick_size

    def run(self):
        print(f"Running Renko with brick_size = {self.brick_size}")
