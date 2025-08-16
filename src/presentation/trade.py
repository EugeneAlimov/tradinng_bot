# -*- coding: utf-8 -*-
from __future__ import annotations
import time

from ..integrations.exmo_private import ExmoPrivate


def _place_limit(
        exmo: ExmoPrivate,
        pair: str,
        side: str,
        price: float,
        qty_base: float,
        *,
        client_id_prefix: str,  # префикс оставляем для совместимости, но на биржу не шлём
) -> str:
    """
    Создаёт ЛИМИТ-ордер с количеством в БАЗОВОЙ валюте (DOGE).
    Требование EXMO: client_id должен быть ЧИСЛОМ. Используем timestamp-ms (31 бит).
    """
    import math
    ts_ms = int(time.time() * 1000)
    cid_int = int(ts_ms % 2_147_483_647)

    price_s = f"{price:.10f}".rstrip("0").rstrip(".")
    qty_s = f"{qty_base:.10f}".rstrip("0").rstrip(".")

    resp = exmo.order_create(
        pair=pair,
        quantity=qty_s,
        price=price_s,
        side=side,
        client_id=cid_int,  # ← строго число
    )
    oid = str(resp.get("order_id") or resp.get("order_id_str") or "")
    if not oid:
        raise RuntimeError(f"order_create failed: {resp}")
    return oid


def _await_and_cleanup(exmo: ExmoPrivate, order_id: str, wait_sec: float = 3.0) -> bool:
    """
    Ждём, пока ордера нет среди открытых (значит исполнился/снялся),
    по таймауту — пытаемся отменить.
    """
    t0 = time.time()
    while time.time() - t0 < wait_sec:
        time.sleep(0.5)
        try:
            oo = exmo.user_open_orders()
        except Exception:
            continue
        found = False
        if isinstance(oo, dict):
            for _pair, orders in oo.items():
                for o in (orders or []):
                    if str(o.get("order_id")) == order_id:
                        found = True
                        break
                if found: break
        if not found:
            return True
    try:
        exmo.order_cancel(order_id)
    except Exception:
        pass
    return False
