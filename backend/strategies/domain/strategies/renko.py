from datetime import datetime
from typing import Any, Dict, List, Optional
from exchanges.domain.schemas import Candle
from strategies.domain.strategies.schemas import Brick
from strategies.domain.strategies.base import AbstractStrategy, SignalType
from loguru import logger


class RenkoDecisionMaker:
    """
    Класс принимает сигналы Renko кирпичей (вверх/вниз) и принимает торговое решение.
    """

    def __init__(self) -> None:
        self.current_position: Optional[str] = None  # 'long', 'short', or None
        self.renko_bricks: List[str] = []  # История направлений: "up" или "down"

    def add_brick(self, direction: str) -> None:
        """
        Добавляет кирпич в историю.
        Обрезает историю до последних 5 кирпичей.
        """
        self.renko_bricks.append(direction)
        if len(self.renko_bricks) > 5:
            self.renko_bricks.pop(0)

    def get_decision(self) -> Optional[SignalType]:
        """
        Возвращает торговое решение на основе последних кирпичей:
        - "buy" если 3 вверх и не в позиции
        - "sell" если 3 вниз и не в позиции
        - Закрывает позицию, если 2 кирпича против текущей
        - "hold" если нужно держать текущую позицию
        - None если не готово к принятию решения
        """
        if len(self.renko_bricks) < 3:
            return None

        last_three = self.renko_bricks[-3:]

        if self.current_position is None:
            if all(d == "up" for d in last_three):
                self.current_position = "long"
                return "buy"
            if all(d == "down" for d in last_three):
                self.current_position = "short"
                return "sell"

        if self.current_position == "long" and all(
            d == "down" for d in self.renko_bricks[-2:]
        ):
            self.current_position = None
            return "sell"

        if self.current_position == "short" and all(
            d == "up" for d in self.renko_bricks[-2:]
        ):
            self.current_position = None
            return "buy"

        return "hold" if self.current_position else None


class RenkoStrategy(AbstractStrategy):
    """
    Реализация торговой стратегии на основе Renko-графиков.
    """

    def __init__(self, threshold_up: float = 1.0, threshold_down: float = 1.0) -> None:
        """
        :param threshold_up: Процент изменения цены для формирования кирпича вверх
        :param threshold_down: Процент изменения цены для формирования кирпича вниз
        """
        self.threshold_up = threshold_up
        self.threshold_down = threshold_down
        self.decision_maker = RenkoDecisionMaker()
        self.bricks: List[Brick] = []
        self._low_wick: Optional[float] = None
        self._high_wick: Optional[float] = None

        logger.info(
            f"RenkoStrategy инициализирована: threshold_up={threshold_up}, threshold_down={threshold_down}"
        )

    def handle_candle(self, candle: Candle) -> None:
        """
        Обрабатывает новую свечу: строит кирпичи и принимает торговое решение.

        Args:
            candle (Candle): Новая входящая свеча.

        Returns:
            Optional[str]: Торговое решение (buy, sell, hold).
        """
        logger.debug(f"Обработка свечи: {candle}")
        new_bricks = self.build_bricks(candle)

        if not new_bricks:
            return None

        for brick in new_bricks:
            self.add_new_brick(brick)
            self.decision_maker.add_brick(brick.type)

    def get_signal(self) -> SignalType:
        decision = self.decision_maker.get_decision()
        logger.info(f"Принято торговое решение: {decision}")
        return decision

    def load_data(self, data: Dict[str, Any]) -> None:
        """
        Загружает состояние стратегии (восстановление при перезапуске).
        """
        bricks = data.get("bricks", [])
        self.bricks = [Brick(**brick) for brick in bricks]

        # self.decision_maker.current_position = data.get("current_position", None)
        # renko_bricks_data = data.get("renko_bricks", [])
        # self.decision_maker.renko_bricks = renko_bricks_data

    def dump_data(self) -> Dict[str, Any]:
        """
        Сохраняет текущее состояние стратегии (для восстановления при перезапуске).
        """
        bricks_dicts = [brick.model_dump(mode="json") for brick in self.bricks]
        return {
            "bricks": bricks_dicts,
            # "current_position": self.decision_maker.current_position,
            # "renko_bricks": self.decision_maker.renko_bricks,
        }

    @property
    def last_brick(self) -> Optional[Brick]:
        return self.bricks[-1] if self.bricks else None

    def add_new_brick(self, brick: Brick) -> None:
        """
        Добавляет новый кирпич в список bricks.

        Args:
            brick (Brick): Кирпич, который необходимо добавить.
        """
        self.bricks.append(brick)

    def _update_wick_min(self, wick: Optional[float], price: float) -> float:
        return price if wick is None else min(wick, price)

    def _update_wick_max(self, wick: Optional[float], price: float) -> float:
        return price if wick is None else max(wick, price)

    def build_bricks(self, candle: Candle) -> List[Brick]:
        """
        Строит новые кирпичи на основе поступившей свечи.

        Args:
            candle (Candle): Входящая свеча.

        Returns:
            List[Brick]: Список новых кирпичей (может быть пустым).
        """
        price = candle.close
        dt = candle.timestamp
        new_bricks = []

        brick_size_up = price / 100 * self.threshold_up
        brick_size_down = price / 100 * self.threshold_down
        last = self.last_brick

        if last is None:
            logger.debug("Первый кирпич строится.")
            brick = Brick(timestamp=dt, type="first", open=price, close=price)
            self.add_new_brick(brick)
            return [brick]

        def create(
            direction: str, count: int, wick: Optional[float] = None
        ) -> List[Brick]:
            size = brick_size_up if direction == "up" else brick_size_down
            logger.debug(f"Создаем {count} кирпичей в направлении {direction}.")
            bricks = self.create_bricks(dt, direction, count, size, wick)
            self._low_wick = None
            self._high_wick = None
            return bricks

        if last.type == "up":
            if price > last.close:
                count = int((price - last.close) / brick_size_up)
                if count > 0:
                    new_bricks = create("up", count, self._low_wick)
                else:
                    self._high_wick = self._update_wick_max(self._high_wick, price)
            elif price < last.open:
                count = int((last.open - price) / brick_size_down)
                if count > 0:
                    new_bricks = create("down", count, self._high_wick)
                else:
                    self._low_wick = self._update_wick_min(self._low_wick, price)

        elif last.type == "down":
            if price < last.close:
                count = int((last.close - price) / brick_size_down)
                if count > 0:
                    new_bricks = create("down", count, self._high_wick)
                else:
                    self._low_wick = self._update_wick_min(self._low_wick, price)
            elif price > last.open:
                count = int((price - last.open) / brick_size_up)
                if count > 0:
                    new_bricks = create("up", count, self._low_wick)
                else:
                    self._high_wick = self._update_wick_max(self._high_wick, price)

        elif last.type == "first":
            if price > last.close:
                count = int((price - last.close) / brick_size_up)
                if count > 0:
                    new_bricks = create("up", count)
            elif price < last.close:
                count = int((last.close - price) / brick_size_down)
                if count > 0:
                    new_bricks = create("down", count)

        logger.debug(f"Построено кирпичей: {len(new_bricks)}")
        return new_bricks

    def create_bricks(
        self,
        dt: datetime,
        direction: str,
        count: int,
        brick_size: float,
        wick: Optional[float] = None,
    ) -> List[Brick]:
        """
        Создаёт список кирпичей по направлению и количеству.

        Args:
            dt (datetime): Временная метка для кирпичей.
            direction (str): Направление ('up' или 'down').
            count (int): Количество кирпичей.
            brick_size (float): Размер одного кирпича.
            wick (Optional[float]): Верхняя или нижняя тень.

        Returns:
            List[Brick]: Список созданных кирпичей.
        """
        new_bricks = []
        for _ in range(count):
            last_close = self.last_brick.close if self.bricks else 0
            new_open = last_close
            new_close = (
                last_close + brick_size
                if direction == "up"
                else last_close - brick_size
            )

            brick = Brick(
                timestamp=dt,
                type=direction,
                open=new_open,
                close=new_close,
                low=wick,
                high=wick,
            )
            new_bricks.append(brick)
        return new_bricks
