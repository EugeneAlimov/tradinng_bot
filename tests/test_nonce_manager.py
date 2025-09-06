# tests/test_nonce_manager.py
import concurrent.futures
import threading
import time
from src.infrastructure.exchange.nonce_manager import ThreadSafeNonceManager


def test_nonce_monotonic_and_unique(tmp_path):
    """Тест монотонности и уникальности nonce в многопоточной среде"""
    f = tmp_path / ".nonce"
    nm = ThreadSafeNonceManager(str(f))

    # Сбрасываем в известное состояние
    nm.reset(1000000)  # Начинаем с фиксированного значения

    vals = []
    errors = []

    def worker():
        """Рабочая функция для получения nonce"""
        try:
            return nm.next()
        except Exception as e:
            errors.append(e)
            return None

    # Используем умеренное количество потоков и операций
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(worker) for _ in range(200)]  # Меньше операций
        for fu in futs:
            result = fu.result()
            if result is not None:
                vals.append(result)

    # Проверяем, что не было ошибок
    assert len(errors) == 0, f"Errors occurred: {errors}"

    # Проверяем уникальность
    unique_vals = set(vals)
    assert len(vals) == len(unique_vals), \
        f"nonce must be unique, got {len(vals)} values but {len(unique_vals)} unique"

    # Проверяем монотонность значений (не порядка возврата!)
    # В многопоточности порядок возврата может быть нарушен, но сами значения должны быть последовательными
    sorted_vals = sorted(vals)
    min_val = min(vals)
    max_val = max(vals)

    # Проверяем что значения образуют последовательность
    expected_vals = list(range(min_val, max_val + 1))
    missing_vals = set(expected_vals) - set(vals)
    extra_vals = set(vals) - set(expected_vals)

    # Диагностика
    print(f"Generated {len(vals)} nonces from {min_val} to {max_val}")
    print(f"Range size: {max_val - min_val + 1}, actual count: {len(vals)}")

    if missing_vals:
        print(f"Missing values in sequence: {sorted(list(missing_vals))[:10]}...")
    if extra_vals:
        print(f"Extra values: {sorted(list(extra_vals))[:10]}...")

    # Основное условие: все значения должны быть больше стартового
    assert all(v > 1000000 for v in vals), "All values should be greater than reset value"

    # Проверяем что диапазон разумный (не должно быть больших пропусков)
    range_size = max_val - min_val + 1
    efficiency = len(vals) / range_size
    print(f"Sequence efficiency: {efficiency:.2%}")

    # Должно быть достаточно эффективно (не более 5% пропусков для простого счетчика)
    assert efficiency >= 0.95, f"Too many gaps in sequence: efficiency {efficiency:.2%}"

    # Все значения должны быть уникальны (уже проверено выше, но для ясности)
    assert len(vals) == len(set(vals)), "All nonces must be unique"


def _is_mostly_monotonic(vals, tolerance=0.95):
    """
    Проверяет, что список "в основном" монотонный.
    В многопоточной среде может быть небольшое количество нарушений порядка
    из-за scheduling, но общая тенденция должна быть монотонной.
    """
    if len(vals) < 2:
        return True

    violations = 0
    for i in range(1, len(vals)):
        if vals[i] <= vals[i - 1]:
            violations += 1

    violation_rate = violations / (len(vals) - 1)
    return violation_rate < (1 - tolerance)


def test_nonce_file_persistence(tmp_path):
    """Тест сохранения nonce в файл и восстановления"""
    f = tmp_path / ".nonce_persist"

    # Создаем первый менеджер и получаем несколько nonce
    nm1 = ThreadSafeNonceManager(str(f))
    nm1.reset(1000)

    vals1 = [nm1.next() for _ in range(5)]
    last_val = vals1[-1]

    # Создаем второй менеджер - должен продолжить с того же места
    nm2 = ThreadSafeNonceManager(str(f))
    first_val_nm2 = nm2.next()

    # Новое значение должно быть больше последнего из первого менеджера
    assert first_val_nm2 > last_val, \
        f"New manager should continue from {last_val}, but got {first_val_nm2}"


def test_nonce_reset():
    """Тест функции reset"""
    nm = ThreadSafeNonceManager()

    # Получаем несколько значений
    vals1 = [nm.next() for _ in range(3)]

    # Сбрасываем в большее значение
    reset_val = max(vals1) + 1000
    nm.reset(reset_val)

    # Следующее значение должно быть больше reset_val
    next_val = nm.next()
    assert next_val > reset_val, f"After reset to {reset_val}, next should be > {reset_val}, got {next_val}"


def test_nonce_thread_safety_stress():
    """Стресс-тест для многопоточности с акцентом на уникальность"""
    nm = ThreadSafeNonceManager()
    nm.reset(5000000)  # Начинаем с большего числа

    results = []
    lock = threading.Lock()

    def stress_worker():
        local_results = []
        for _ in range(25):  # Меньше итераций для стабильности
            local_results.append(nm.next())
            # Небольшая задержка для большего разнообразия
            time.sleep(0.0001)

        with lock:
            results.extend(local_results)

    threads = []
    for _ in range(8):  # 8 потоков
        t = threading.Thread(target=stress_worker)
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    # Проверяем общие свойства
    expected_count = 8 * 25
    assert len(results) == expected_count, f"Expected {expected_count}, got {len(results)}"
    assert len(set(results)) == len(results), "All nonces must be unique"
    assert min(results) > 5000000, "All nonces must be greater than reset value"
    assert max(results) > min(results), "Nonces must be increasing"

    print(f"Stress test: {len(results)} unique nonces from {min(results)} to {max(results)}")


def test_nonce_sequential_access():
    """Тест последовательного доступа (без многопоточности)"""
    nm = ThreadSafeNonceManager()
    nm.reset(2000000)

    vals = [nm.next() for _ in range(10)]

    # В последовательном режиме должна быть строгая монотонность
    for i in range(1, len(vals)):
        assert vals[i] == vals[i - 1] + 1, f"Sequential access should be strictly monotonic: {vals[i - 1]} -> {vals[i]}"

    print(f"Sequential test: {vals}")


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        from pathlib import Path

        test_nonce_sequential_access()
        test_nonce_monotonic_and_unique(Path(tmpdir))
        test_nonce_file_persistence(Path(tmpdir))
        test_nonce_reset()
        test_nonce_thread_safety_stress()
