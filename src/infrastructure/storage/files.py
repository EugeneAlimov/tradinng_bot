
from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, Any
from decimal import Decimal
from src.core.ports.storage import StoragePort
from src.core.domain.models import Position, TradingPair

class FileStorage(StoragePort):
    def __init__(self, path: str = "data/"):
        self.base = Path(path)
        self.base.mkdir(parents=True, exist_ok=True)
        (self.base / "trades.jsonl").touch(exist_ok=True)
        (self.base / "positions.json").touch(exist_ok=True)

    def append_trade(self, rec: Dict[str, Any]) -> None:
        with (self.base / "trades.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def get_position(self, pair: TradingPair) -> Position | None:
        try:
            data = json.loads((self.base / "positions.json").read_text() or "{}")
        except json.JSONDecodeError:
            data = {}
        p = data.get(pair.symbol())
        if not p:
            return None
        # Stored as simple dict with floats; reconstruct Position
        qty = Decimal(str(p.get("qty", 0)))
        avg = Decimal(str(p.get("avg_price", 0)))
        return Position(pair=pair, qty=qty, avg_price=avg)

    def save_position(self, p: Position) -> None:
        try:
            data = json.loads((self.base / "positions.json").read_text() or "{}")
        except json.JSONDecodeError:
            data = {}
        data[p.pair.symbol()] = {"qty": float(p.qty), "avg_price": float(p.avg_price)}
        (self.base / "positions.json").write_text(json.dumps(data, ensure_ascii=False, indent=2))
