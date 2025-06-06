from celery import shared_task
from django.utils import timezone
from exchanges.models import (
    Exchange as ExchangeModel,
    Candle as CandleModel,
    Timeframe as TimeframeModel,
)
from traders.models import CandleSource as CandleSourceModel


# @shared_task
# def save_candles_by_timeframe(timeframe: str):
#     """
#     Асинхронно загружает и сохраняет свечи для всех активных CandleSource с заданным timeframe.
#     """

#     async def fetch_and_prepare_candles(source: CandleSourceModel) -> list[CandleModel]:
#         exchange: ExchangeModel = source.exchange
#         symbol = source.trading_pair.name
#         tf_enum = TimeframeModel(source.timeframe)
#         since = timezone.now() - tf_enum.as_timedelta()

#         async with exchange.instantiate() as exchange_instance:
#             try:
#                 candles = await exchange_instance.get_market_candles(
#                     symbol=symbol,
#                     timeframe=source.timeframe,
#                     since=since,
#                     limit=2,
#                 )
#             except Exception as e:
#                 # можно логировать ошибки
#                 return []

#         return [
#             CandleModel(
#                 candle_source=source,
#                 timestamp=timezone.make_aware(c.timestamp),
#                 open=c.open,
#                 high=c.high,
#                 low=c.low,
#                 close=c.close,
#                 volume=c.volume,
#             )
#             for c in candles[:1]  # обрезаем до 1 свечи, как указано
#         ]

#     async def collect_and_save():
#         # Загружаем источники в отдельном потоке (ORM нельзя вызывать из async)
#         sources = await asyncio.to_thread(
#             lambda: list(
#                 CandleSourceModel.objects.select_related(
#                     "exchange", "trading_pair"
#                 ).filter(is_active=True, timeframe=timeframe)
#             )
#         )

#         # Получаем все свечи параллельно
#         all_candle_lists = await asyncio.gather(
#             *(fetch_and_prepare_candles(s) for s in sources)
#         )
#         all_candles = [c for sublist in all_candle_lists for c in sublist]

#         # Сохраняем всё сразу
#         if all_candles:
#             await asyncio.to_thread(
#                 lambda: CandleModel.objects.bulk_create(
#                     all_candles,
#                     update_conflicts=True,
#                     update_fields=["open", "high", "low", "close", "volume"],
#                     unique_fields=["candle_source", "timestamp"],
#                 )
#             )

#     return asyncio.run(collect_and_save())


@shared_task
def save_candles_by_candle_source(source_id):
    source: CandleSourceModel = CandleSourceModel.active_objects.select_related(
        "exchange", "trading_pair"
    ).get(id=source_id)
    tf_enum = TimeframeModel(source.timeframe)
    since = timezone.now() - tf_enum.as_timedelta()
    source.save_candles(limit=1, since=since)
