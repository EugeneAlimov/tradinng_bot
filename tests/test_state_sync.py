# tests/test_state_sync.py
import os
import json
import tempfile
import unittest
from decimal import Decimal

# Абсолютные импорты из пакета src.*
from src.application.state_sync import StateSynchronizer, LocalState
from src.infrastructure.exchange.validator import ExchangeDataValidator


class _FakeExchange:
    """
    Минимальный фейк EXMO API для теста синхронизации состояний.
    Возвращает user_info() и user_open_orders() в формате, совместимом с нашим валидатором/синхронизатором.
    """

    def __init__(self, base="DOGE", quote="EUR", base_free="123.456789", quote_free="987.65"):
        self._base = base
        self._quote = quote
        self._balances = {
            self._base: base_free,
            self._quote: quote_free,
        }

    def user_info(self):
        # Совместимая структура с нашими валидаторами и текущим кодом
        return {"balances": dict(self._balances)}

    def user_open_orders(self, pair: str | None = None):
        # Совместимая структура: словарь {PAIR: [orders]}
        if pair:
            return {pair: []}
        return {f"{self._base}_{self._quote}": []}


class TestStateSync(unittest.TestCase):
    def test_sync_and_reconcile(self):
        pair = "DOGE_EUR"
        base, quote = pair.split("_")
        with tempfile.TemporaryDirectory() as td:
            state_path = os.path.join(td, "bot_state.json")

            # Начальное локальное состояние "рассинхронено"
            st = {
                "pos_qty": "0",  # локально пусто
                "cash_eur": "0",
                "avg_price": "0",
                "pnl_sum_pos": "0",
                "pnl_sum_neg": "0",
                "round_trips": 0,
                "wins": 0,
                "timestamp": 0.0,
            }
            with open(state_path, "w") as f:
                json.dump(st, f)

            # На бирже есть позиция
            fake = _FakeExchange(base=base, quote=quote, base_free="10.5", quote_free="1000")

            sync = StateSynchronizer(exchange_api=fake, pair=pair, state_path=state_path)
            ex_state = sync.sync_with_exchange(force=True)

            # Биржевое состояние прочиталось
            self.assertIn(base, ex_state.balances)
            self.assertIn(quote, ex_state.balances)

            # Вызов сверки должен подтянуть локальное состояние к биржевому (при расхождении)
            sync.reconcile_after_restart()

            # Перечитываем локальное состояние с диска
            with open(state_path, "r") as f:
                data = json.load(f)

            # Позиция локально == бирже (с учётом допустимого "порога пыли")
            self.assertAlmostEqual(float(data["pos_qty"]), float(ex_state.positions[base]))

            # Базовые инварианты
            self.assertGreaterEqual(float(data["pos_qty"]), 0.0)
            self.assertGreaterEqual(float(data["cash_eur"]), 0.0)

    def test_validator_decimal(self):
        # Базовая проверка валидатора на корректные и некорректные значения
        v = ExchangeDataValidator.to_decimal("123.450000", "test")
        self.assertEqual(v, Decimal("123.450000"))
        with self.assertRaises(Exception):
            ExchangeDataValidator.to_decimal("nan", "test_nan")


if __name__ == "__main__":
    unittest.main()
