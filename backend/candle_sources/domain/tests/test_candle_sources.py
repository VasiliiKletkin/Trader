import pytest
from datetime import datetime
from decimal import Decimal
from exchanges.domain import Candle
from candle_sources.domain import PlainCandleSource, DivisionCandleSource


class TestPlainCandleSource:
    """Тесты для PlainCandleSource."""

    @pytest.fixture
    def sample_candles(self) -> list[Candle]:
        """Создаёт список тестовых свечей."""
        return [
            Candle(
                ids=[1],
                dt_unix=1000000 + i * 60,
                timestamp=datetime(2025, 12, 13, 10, i),
                open=Decimal("100") + i,
                high=Decimal("110") + i,
                low=Decimal("90") + i,
                close=Decimal("105") + i,
                volume=Decimal("1000") + i * 100,
            )
            for i in range(10)
        ]

    def test_init(self, sample_candles):
        """Тест инициализации PlainCandleSource."""
        source = PlainCandleSource(sample_candles)
        assert source.candles == sample_candles

    def test_init_with_empty_list(self):
        """Тест инициализации с пустым списком."""
        source = PlainCandleSource([])
        assert source.candles == []

    def test_get_candle_returns_same_candle(self, sample_candles):
        """Тест get_candle возвращает ту же свечу."""
        source = PlainCandleSource(sample_candles)
        candle = sample_candles[0]
        result = source.get_candle(candle)
        assert result == candle

    def test_get_candles(self, sample_candles):
        """Тест get_candles возвращает все свечи."""
        source = PlainCandleSource(sample_candles)
        result = source.get_candles()
        assert result == sample_candles
        assert len(result) == 10

    def test_get_candles_empty(self):
        """Тест get_candles с пустым списком."""
        source = PlainCandleSource([])
        result = source.get_candles()
        assert result == []

    def test_get_last_candles_less_than_total(self, sample_candles):
        """Тест get_last_candles когда count меньше общего количества."""
        source = PlainCandleSource(sample_candles)
        result = source.get_last_candles(3)
        assert len(result) == 3
        assert result == sample_candles[-3:]

    def test_get_last_candles_equal_to_total(self, sample_candles):
        """Тест get_last_candles когда count равен общему количеству."""
        source = PlainCandleSource(sample_candles)
        result = source.get_last_candles(10)
        assert len(result) == 10
        assert result == sample_candles

    def test_get_last_candles_more_than_total(self, sample_candles):
        """Тест get_last_candles когда count больше общего количества."""
        source = PlainCandleSource(sample_candles)
        result = source.get_last_candles(20)
        assert len(result) == 10
        assert result == sample_candles

    def test_get_last_candles_zero(self, sample_candles):
        """Тест get_last_candles с count=0."""
        source = PlainCandleSource(sample_candles)
        result = source.get_last_candles(0)
        assert result == []

    def test_get_last_candles_one(self, sample_candles):
        """Тест get_last_candles с count=1."""
        source = PlainCandleSource(sample_candles)
        result = source.get_last_candles(1)
        assert len(result) == 1
        assert result[0] == sample_candles[-1]


class TestDivisionCandleSource:
    """Тесты для DivisionCandleSource."""

    @pytest.fixture
    def candles1(self) -> list[Candle]:
        """Первый список свечей (числитель)."""
        return [
            Candle(
                ids=[i],
                dt_unix=1000000 + i * 60,
                timestamp=datetime(2025, 12, 13, 10, i),
                open=Decimal("100"),
                high=Decimal("110"),
                low=Decimal("90"),
                close=Decimal("105"),
                volume=Decimal("1000"),
            )
            for i in range(5)
        ]

    @pytest.fixture
    def candles2(self) -> list[Candle]:
        """Второй список свечей (знаменатель)."""
        return [
            Candle(
                ids=[i + 100],
                dt_unix=1000000 + i * 60,
                timestamp=datetime(2025, 12, 13, 10, i),
                open=Decimal("50"),
                high=Decimal("55"),
                low=Decimal("45"),
                close=Decimal("52.5"),
                volume=Decimal("500"),
            )
            for i in range(5)
        ]

    def test_init(self, candles1, candles2):
        """Тест инициализации DivisionCandleSource."""
        source = DivisionCandleSource(candles1, candles2)
        assert source.candles1 == candles1
        assert source.candles2 == candles2

    def test_get_candle_division(self, candles1, candles2):
        """Тест get_candle делит свечи корректно."""
        source = DivisionCandleSource(candles1, candles2)
        result = source.get_candle(candles1[0], candles2[0])

        assert result.timestamp == candles1[0].timestamp
        assert result.dt_unix == candles1[0].dt_unix
        assert result.open == Decimal("100") / Decimal("50")  # 2.0
        assert result.high == Decimal("110") / Decimal("55")  # 2.0
        assert result.low == Decimal("90") / Decimal("45")  # 2.0
        assert result.close == Decimal("105") / Decimal("52.5")  # 2.0
        assert result.volume == Decimal("1000") / Decimal("500")  # 2.0

    def test_get_candle_preserves_ids(self, candles1, candles2):
        """Тест get_candle сохраняет ids обеих свечей."""
        source = DivisionCandleSource(candles1, candles2)
        result = source.get_candle(candles1[0], candles2[0])

        assert result.ids == candles1[0].ids + candles2[0].ids

    def test_get_candle_division_by_zero_open(self, candles1):
        """Тест get_candle выбрасывает ошибку при делении на ноль (open)."""
        zero_candle = Candle(
            ids=[999],
            dt_unix=1000000,
            timestamp=datetime(2025, 12, 13, 10, 0),
            open=Decimal("0"),
            high=Decimal("55"),
            low=Decimal("45"),
            close=Decimal("52.5"),
            volume=Decimal("500"),
        )
        source = DivisionCandleSource(candles1, [zero_candle])

        with pytest.raises(ValueError, match="Деление на ноль в свечах"):
            source.get_candle(candles1[0], zero_candle)

    def test_get_candle_division_by_zero_high(self, candles1):
        """Тест get_candle выбрасывает ошибку при делении на ноль (high)."""
        zero_candle = Candle(
            ids=[999],
            dt_unix=1000000,
            timestamp=datetime(2025, 12, 13, 10, 0),
            open=Decimal("50"),
            high=Decimal("0"),
            low=Decimal("45"),
            close=Decimal("52.5"),
            volume=Decimal("500"),
        )
        source = DivisionCandleSource(candles1, [zero_candle])

        with pytest.raises(ValueError, match="Деление на ноль в свечах"):
            source.get_candle(candles1[0], zero_candle)

    def test_get_candle_division_by_zero_low(self, candles1):
        """Тест get_candle выбрасывает ошибку при делении на ноль (low)."""
        zero_candle = Candle(
            ids=[999],
            dt_unix=1000000,
            timestamp=datetime(2025, 12, 13, 10, 0),
            open=Decimal("50"),
            high=Decimal("55"),
            low=Decimal("0"),
            close=Decimal("52.5"),
            volume=Decimal("500"),
        )
        source = DivisionCandleSource(candles1, [zero_candle])

        with pytest.raises(ValueError, match="Деление на ноль в свечах"):
            source.get_candle(candles1[0], zero_candle)

    def test_get_candle_division_by_zero_close(self, candles1):
        """Тест get_candle выбрасывает ошибку при делении на ноль (close)."""
        zero_candle = Candle(
            ids=[999],
            dt_unix=1000000,
            timestamp=datetime(2025, 12, 13, 10, 0),
            open=Decimal("50"),
            high=Decimal("55"),
            low=Decimal("45"),
            close=Decimal("0"),
            volume=Decimal("500"),
        )
        source = DivisionCandleSource(candles1, [zero_candle])

        with pytest.raises(ValueError, match="Деление на ноль в свечах"):
            source.get_candle(candles1[0], zero_candle)

    def test_get_candle_zero_volume_in_denominator(self, candles1):
        """Тест get_candle возвращает volume=0 при нулевом volume в знаменателе."""
        zero_volume_candle = Candle(
            ids=[999],
            dt_unix=1000000,
            timestamp=datetime(2025, 12, 13, 10, 0),
            open=Decimal("50"),
            high=Decimal("55"),
            low=Decimal("45"),
            close=Decimal("52.5"),
            volume=Decimal("0"),
        )
        source = DivisionCandleSource(candles1, [zero_volume_candle])
        result = source.get_candle(candles1[0], zero_volume_candle)

        assert result.volume == 0

    def test_get_candles(self, candles1, candles2):
        """Тест get_candles возвращает все делённые свечи."""
        source = DivisionCandleSource(candles1, candles2)
        result = source.get_candles()

        assert len(result) == 5
        for i, candle in enumerate(result):
            assert candle.timestamp == candles1[i].timestamp
            assert candle.open == candles1[i].open / candles2[i].open

    def test_get_candles_different_lengths(self):
        """Тест get_candles с разной длиной списков (zip обрезает)."""
        candles1 = [
            Candle(
                ids=[i],
                dt_unix=1000000 + i * 60,
                timestamp=datetime(2025, 12, 13, 10, i),
                open=Decimal("100"),
                high=Decimal("110"),
                low=Decimal("90"),
                close=Decimal("105"),
                volume=Decimal("1000"),
            )
            for i in range(5)
        ]
        candles2 = [
            Candle(
                ids=[i + 100],
                dt_unix=1000000 + i * 60,
                timestamp=datetime(2025, 12, 13, 10, i),
                open=Decimal("50"),
                high=Decimal("55"),
                low=Decimal("45"),
                close=Decimal("52.5"),
                volume=Decimal("500"),
            )
            for i in range(3)
        ]
        source = DivisionCandleSource(candles1, candles2)
        result = source.get_candles()

        assert len(result) == 3  # zip обрезает до минимальной длины

    def test_get_last_candles_less_than_total(self, candles1, candles2):
        """Тест get_last_candles когда count меньше общего количества."""
        source = DivisionCandleSource(candles1, candles2)
        result = source.get_last_candles(2)

        assert len(result) == 2
        # Проверяем что это последние свечи
        assert result[0].timestamp == candles1[-2].timestamp
        assert result[1].timestamp == candles1[-1].timestamp

    def test_get_last_candles_equal_to_total(self, candles1, candles2):
        """Тест get_last_candles когда count равен общему количеству."""
        source = DivisionCandleSource(candles1, candles2)
        result = source.get_last_candles(5)

        assert len(result) == 5

    def test_get_last_candles_more_than_total(self, candles1, candles2):
        """Тест get_last_candles когда count больше общего количества."""
        source = DivisionCandleSource(candles1, candles2)
        result = source.get_last_candles(10)

        assert len(result) == 5  # Возвращает все доступные

    def test_get_last_candles_zero(self, candles1, candles2):
        """Тест get_last_candles с count=0."""
        source = DivisionCandleSource(candles1, candles2)
        result = source.get_last_candles(0)

        assert result == []

    def test_get_last_candles_division_applied(self, candles1, candles2):
        """Тест что get_last_candles применяет деление."""
        source = DivisionCandleSource(candles1, candles2)
        result = source.get_last_candles(2)

        for candle in result:
            assert candle.open == Decimal("100") / Decimal("50")  # 2.0


class TestCandleSourceIntegration:
    """Интеграционные тесты."""

    def test_plain_source_preserves_order(self):
        """Тест что PlainCandleSource сохраняет порядок свечей."""
        candles = [
            Candle(
                ids=[i],
                dt_unix=1000000 + i * 60,
                timestamp=datetime(2025, 12, 13, 10, i),
                open=Decimal(str(i)),
                high=Decimal(str(i + 10)),
                low=Decimal(str(i - 10)) if i >= 10 else Decimal("0"),
                close=Decimal(str(i + 5)),
                volume=Decimal(str(i * 100)),
            )
            for i in range(1, 11)
        ]
        source = PlainCandleSource(candles)
        result = source.get_candles()

        for i, candle in enumerate(result):
            assert candle.open == Decimal(str(i + 1))

    def test_division_source_with_varying_values(self):
        """Тест DivisionCandleSource с разными значениями."""
        candles1 = [
            Candle(
                ids=[1],
                dt_unix=1000000,
                timestamp=datetime(2025, 12, 13, 10, 0),
                open=Decimal("200"),
                high=Decimal("220"),
                low=Decimal("180"),
                close=Decimal("210"),
                volume=Decimal("2000"),
            ),
        ]
        candles2 = [
            Candle(
                ids=[2],
                dt_unix=1000000,
                timestamp=datetime(2025, 12, 13, 10, 0),
                open=Decimal("100"),
                high=Decimal("110"),
                low=Decimal("90"),
                close=Decimal("105"),
                volume=Decimal("1000"),
            ),
        ]
        source = DivisionCandleSource(candles1, candles2)
        result = source.get_candles()

        assert len(result) == 1
        assert result[0].open == Decimal("2")
        assert result[0].high == Decimal("2")
        assert result[0].low == Decimal("2")
        assert result[0].close == Decimal("2")
        assert result[0].volume == Decimal("2")
