from celery import group
from time import sleep


def run_tasks_in_groups(
    task_function, task_params, chunk_size=20, delay_between_chunks=0.5
):
    """
    Запускает задачи через group, разбивая на батчи.
    :param task_function: Функция задачи (например, trader_check_opened_positions).
    :param task_params: Список словарей с параметрами для задач (например, [{'id': 1}, {'id': 2}]).
    :param chunk_size: Размер батча (по умолчанию 20).
    :param delay_between_chunks: Задержка между батчами в секундах (по умолчанию 0.5).
    """
    for chunk in [
        task_params[i : i + chunk_size] for i in range(0, len(task_params), chunk_size)
    ]:
        group(task_function.s(**params) for params in chunk)()
        if delay_between_chunks > 0:
            sleep(delay_between_chunks)
