# -*- coding: utf-8 -*-
"""
Minimal CLI helpers for live trading / diagnostics.
Key changes:
- API secrets are fully masked in logs (no last-4 printing).
- Small utilities for pretty-print and launching live trade run.

This module does NOT replace your project-wide CLI (main.py).
It provides helpers you can import from main CLI without leaking secrets.

Example usage in your main CLI:
    from src.presentation.cli.app import mask_secret, print_env_summary, run_live
"""
from __future__ import annotations

import logging
import os
from typing import Optional
from decimal import Decimal

from src.presentation.live_trade import run_live_trade, LiveTradeConfig

logger = logging.getLogger(__name__)


def mask_secret(value: Optional[str]) -> str:
    """Mask any secret value; never show tail digits."""
    if not value:
        return "<none>"
    return f"<len={len(value)}>"


def print_env_summary() -> None:
    """Print environment summary without exposing secrets."""
    api_key = os.environ.get("EXMO_API_KEY")
    api_secret = os.environ.get("EXMO_API_SECRET")
    base_url = os.environ.get("EXMO_BASE_URL", "https://api.exmo.com/v1.1")
    nonce_file = os.environ.get("EXMO_NONCE_FILE", "data/.exmo_nonce")

    logger.info("EXMO_BASE_URL: %s", base_url)
    logger.info("EXMO_API_KEY:  %s", mask_secret(api_key))
    logger.info("EXMO_API_SECRET: %s", mask_secret(api_secret))
    logger.info("EXMO_NONCE_FILE: %s", nonce_file)


def run_live(
    pair: str = "DOGE_EUR",
    max_notional_eur: str = "100",
    maker: bool = False,
    iterations: int = 1,
    tick_ms: int = 1000,
) -> None:
    """
    Lightweight runner for live_trade with masked env printing.
    """
    print_env_summary()
    cfg = LiveTradeConfig(
        pair=pair,
        max_notional_eur=Decimal(max_notional_eur),
        maker=maker,
        iterations=int(iterations),
        tick_ms=int(tick_ms),
    )
    run_live_trade(cfg)
