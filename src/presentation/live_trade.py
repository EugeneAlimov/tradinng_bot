# src/presentation/live_trade.py
from __future__ import annotations

import argparse
import logging
import math
import os
import signal
import sys
import time
from dataclasses import dataclass
from decimal import Decimal, getcontext
from typing import Any, Dict, Optional, Tuple

# --- логгер ---
logger = logging.getLogger(__name__)

# --- точность десятичных ---
getcontext().prec = 28

# --- наши интеграции/слои ---
from src.integrations.exmo_private import ExmoPrivate
from src.infrastructure.exchange.validator import (
    SafeExmoWrapper,
    ExchangeDataValidator,
    ValidationError,
)
from src.infrastructure.exchange.order_manager import ImprovedOrderManager
from src.application.sync import StateSynchronizer
from src.domain.risk import AdvancedRiskManager, RiskLimits
from src.monitoring.monitor import MonitoringSystem, MetricType, AlertSeverity


# ==============================
# Конфиг live-торговли
# ==============================
@dataclass
class LiveTradeConfig:
    pair: str                      # EXMO формат, например: DOGE_EUR
    qty_base: Optional[Decimal] = None   # фиксированный размер позиции в базовой валюте
    qty_quote: Optional[Decimal] = None  # фиксированный бюджет в котировочной валюте (например EUR)
    take_liquidity_bps: int = 0          # 0 = лимитки у лучших цен, >0 = агрессия (цена +/- bps)
    fee_bps: int = 10                     # комиссия (базово 0.1% = 10 bps)
    slip_bps: int = 2                     # учёт проскальзывания (для расчётов)
    loop_sleep_s: float = 2.0             # пауза между итерациями
    dry_run: bool = False                 # торговля без фактического размещения ордеров
    dust_sweep: bool = False              # «сметать пыль» (микроостатки) после сделки
    min_trade_value_quote: Decimal = Decimal("1.0")  # минимальный номинал сделки в котировочной
    risk_limits: RiskLimits = RiskLimits()
    start_cash_quote: Optional[Decimal] = None  # начальный капитал (для risk-report; если None — возьмём с биржи)
    metrics_http_bind: Optional[str] = None     # "127.0.0.1:9103" — экспорт /metrics
    telegram_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None


# ==============================
# Вспомогательные утилиты
# ==============================
def _D(x: Any) -> Decimal:
    """Безопасное приведение к Decimal с нормальными ошибками."""
    try:
        return ExchangeDataValidator.to_decimal(x)
    except ValidationError as e:
        raise ValueError(str(e)) from e


def _fmt_price(d: Decimal) -> str:
    """Формат цены в строку: до 10 знаков без хвостовых нулей."""
    s = f"{d:.10f}"
    s = s.rstrip("0").rstrip(".")
    return s if s else "0"


def _fmt_qty(d: Decimal) -> str:
    """Формат количества в строку: до 10 знаков без хвостовых нулей."""
    s = f"{d:.10f}"
    s = s.rstrip("0").rstrip(".")
    return s if s else "0"


def _bps_to_mult(bps: int) -> Decimal:
    return Decimal("1") + (Decimal(bps) / Decimal("10000"))


# ==============================
# Основной класс LiveTrader
# ==============================
class LiveTrader:
    def __init__(self, exmo: ExmoPrivate, cfg: LiveTradeConfig):
        self.cfg = cfg
        self.exmo = exmo
        self.safe = SafeExmoWrapper(exmo)
        self.orders = ImprovedOrderManager(exmo)
        self.sync = StateSynchronizer(exmo, cfg.pair, state_path="data/bot_state.json")

        # Риск-менеджмент
        start_quote = (cfg.start_cash_quote if cfg.start_cash_quote is not None else
                       self._get_quote_balance_fallback())
        self.risk = AdvancedRiskManager(limits=cfg.risk_limits, initial_capital=start_quote)

        # Мониторинг
        self.mon = MonitoringSystem(
            bot_name="tradinng_bot",
            telegram_token=cfg.telegram_token,
            telegram_chat_id=cfg.telegram_chat_id,
            metrics_http_bind=cfg.metrics_http_bind,
        )
        self._setup_health_checks()

        # Границы остановки (SIGINT/SIGTERM)
        self._is_running = True
        signal.signal(signal.SIGINT, self._graceful_stop)
        signal.signal(signal.SIGTERM, self._graceful_stop)

    # ---------- lifecycle ----------
    def _setup_health_checks(self) -> None:
        # health: EXMO ping через user_info (валидатор уже поймает мусор)
        def _exmo_ok() -> bool:
            try:
                _ = self.safe.get_validated_balances()
                return True
            except Exception:
                return False

        self.mon.add_health_check("exmo", _exmo_ok, interval=60)

    def _graceful_stop(self, *_args) -> None:
        logger.info("stop requested — finishing current iteration...")
        self._is_running = False

    # ---------- balances ----------
    def _get_quote_balance_fallback(self) -> Decimal:
        """Попытка аккуратно получить баланс котировочной валюты (без аварий)."""
        bal = self.safe.get_validated_balances()
        _, quote = self.cfg.pair.split("_", 1)
        return bal.get(quote, None).free if bal.get(quote) else Decimal("0")

    # ---------- ticker ----------
    def _get_mid_bid_ask(self) -> Tuple[Decimal, Decimal, Decimal]:
        """
        Получить (mid, bid, ask). Валидация внутри SafeExmoWrapper.
        """
        t = self.safe.get_validated_ticker(self.cfg.pair)
        if not t:
            raise RuntimeError("ticker unavailable")
        self.mon.record_metric("spread_bps",
                               float((t.ask - t.bid) / max(Decimal("1e-8"), t.last) * Decimal("10000")),
                               MetricType.GAUGE, labels={"pair": self.cfg.pair})
        mid = (t.bid + t.ask) / Decimal("2")
        return mid, t.bid, t.ask

    # ---------- sizing ----------
    def _decide_qty(self, entry_price: Decimal) -> Decimal:
        """
        Определяет количество в базовой валюте из конфигурации.
        - Если задан qty_base — используем его.
        - Если задан qty_quote — переводим в базовую: qty_quote / price.
        - Иначе — ноль (ничего не делаем).
        """
        if self.cfg.qty_base and self.cfg.qty_base > 0:
            return self.cfg.qty_base

        if self.cfg.qty_quote and self.cfg.qty_quote > 0:
            q = self.cfg.qty_quote / max(entry_price, Decimal("1e-12"))
            return q

        return Decimal("0")

    # ---------- order/trade ----------
    def _place_limit(self, side: str, price: Decimal, qty: Decimal) -> Tuple[bool, Optional[str], Optional[str]]:
        if self.cfg.dry_run:
            logger.info("[dry_run] %s %s @ %s", side.upper(), _fmt_qty(qty), _fmt_price(price))
            return True, "DRYRUN", None
        return self.orders.place_order_with_retry(self.cfg.pair, side.lower(), float(price), float(qty), max_retries=3)

    def _wait_and_finalize(self, order_id: str, side: str) -> Dict[str, Any]:
        """
        Дожидается исполнения или отменяет по таймауту.
        Корректный фоллбэк sold_qty: считаем по order_trades, а не эвристиками.
        """
        if order_id == "DRYRUN":
            # смоделируем мгновенное исполнение
            return {"status": "filled", "filled": float(self._last_qty), "avg_price": float(self._last_price)}

        st = self.orders.wait_for_fill(order_id, timeout=8.0)

        # Исполнение частично/полностью — сверим по trades (исправление бага sold_qty)
        try:
            tr = self.exmo.order_trades(order_id) or {}
            trades = tr.get("trades")
            if trades:
                total_filled = sum(_D(t.get("quantity", 0)) for t in trades)
                avg = (sum(_D(t.get("quantity", 0)) * _D(t.get("price", 0)) for t in trades) /
                       max(total_filled, Decimal("1e-18")))
                st["status"] = "filled"
                st["filled"] = float(total_filled)
                st["avg_price"] = float(avg)
        except Exception as e:
            logger.warning("order_trades fallback failed for %s: %s", order_id, e)

        return st

    def _maybe_dust_sweep(self, side_just_done: str) -> None:
        """
        Если включено dust_sweep — смахиваем микрорезидуалы в базовой валюте.
        Для SELL — проверяем, не осталась ли «пылинка» в базе; для BUY — наоборот, в котировочной.
        """
        if not self.cfg.dust_sweep:
            return

        base, quote = self.cfg.pair.split("_", 1)
        ex = self.safe.get_validated_balances()

        dust_threshold_base = Decimal("0.00001")  # условный минимум
        dust_threshold_quote = Decimal("0.01")

        if side_just_done.lower() == "sell":
            # после продажи могли остаться микро-DOGE
            free_base = ex.get(base, None).free if ex.get(base) else Decimal("0")
            if free_base > 0 and free_base < dust_threshold_base:
                # пристраиваем пыль маркет-лимитом на bid
                try:
                    _, bid, _ask = self._get_mid_bid_ask()
                    qty = free_base
                    price = bid * Decimal("0.999")  # чуть ниже для мгновенного подбора
                    ok, oid, err = self._place_limit("sell", price, qty)
                    if ok and oid:
                        self.orders.wait_for_fill(oid, timeout=5.0)
                        logger.info("dust sweep (sell base) done: %s %s", base, _fmt_qty(qty))
                except Exception as e:
                    logger.warning("dust sweep (sell base) failed: %s", e)

        elif side_just_done.lower() == "buy":
            # после покупки могли остаться копейки EUR
            free_quote = ex.get(quote, None).free if ex.get(quote) else Decimal("0")
            if free_quote > 0 and free_quote < dust_threshold_quote:
                logger.info("tiny %s remainder after BUY: %s — ignored", quote, _fmt_qty(free_quote))

    # ---------- main loop ----------
    def run_once(self) -> None:
        """
        Одна итерация: загрузка тикера, риск-проверка, размещение сделки (пример).
        Здесь нет конкретной стратегии — оставлена минимальная демонстрация цикла сделки (BUY -> SELL),
        чтобы показать безопасную интеграцию. Свяжи это место со своей сигнализацией.
        """
        # 1) синхронизация
        self.sync.sync()

        # 2) получаем котировки
        mid, bid, ask = self._get_mid_bid_ask()

        # 3) примерная логика: если спред относительно маленький — попробуем открыть «быстрый» round-trip
        spread_bps = (ask - bid) / max(mid, Decimal("1e-8")) * Decimal("10000")

        # --- ТУТ ДОЛЖНА БЫТЬ ТВОЯ СТРАТЕГИЯ ---
        should_trade = spread_bps > 5  # пример: торгуем только если есть спред > 5 bps (как заглушка)
        if not should_trade:
            return

        # 4) размер позиции
        qty = self._decide_qty(ask)
        if qty <= 0:
            return

        # минимальный номинал сделки
        min_notional = self.cfg.min_trade_value_quote
        if qty * ask < min_notional:
            logger.info("skip: notional too small: %s < %s", _fmt_qty(qty * ask), _fmt_qty(min_notional))
            return

        # 5) риск-проверка перед покупкой
        eq_quote = self._get_equity_quote_approx()
        ok, reason = self.risk.pre_trade_check("buy", qty, ask, self.sync.local.pos_qty, eq_quote)
        if not ok:
            logger.info("risk block (BUY): %s", reason)
            return

        # 6) выставляем BUY около ask (учтём агрессию, если задана)
        buy_price = ask * (_bps_to_mult(self.cfg.take_liquidity_bps))
        self._last_qty, self._last_price = qty, buy_price  # для DRYRUN завершения
        ok, order_id, err = self._place_limit("buy", buy_price, qty)
        if not ok or not order_id:
            logger.warning("buy placement failed: %s", err)
            return

        st_buy = self._wait_and_finalize(order_id, "buy")
        if st_buy.get("status") != "filled":
            logger.info("buy not filled (status=%s) — stop", st_buy.get("status"))
            return

        filled_qty = _D(st_buy.get("filled", 0))
        avg_buy = _D(st_buy.get("avg_price", buy_price))
        fee = filled_qty * avg_buy * (Decimal(self.cfg.fee_bps) / Decimal("10000"))

        # обновляем состояние, мониторинг
        self.sync.update_after_trade("BUY", filled_qty, avg_buy, fee=fee)
        self.mon.record_trade(self.cfg.pair, "BUY", float(filled_qty), float(avg_buy), success=True)

        # 7) после покупки — риск-проверка перед продажей (take небольшого профита как демонстрация)
        #    (в реальном коде сюда встанет твой выход по сигналу)
        tp = avg_buy * Decimal("1.0015")  # 15 bps профит-таргет (пример)
        ok, reason = self.risk.pre_trade_check("sell", filled_qty, tp, self.sync.local.pos_qty, eq_quote)
        if not ok:
            logger.info("risk block (SELL): %s", reason)
            return

        sell_price = max(bid, tp) / _bps_to_mult(self.cfg.take_liquidity_bps)  # чуть «внутрь», чтобы забрали
        self._last_qty, self._last_price = filled_qty, sell_price
        ok, order_id, err = self._place_limit("sell", sell_price, filled_qty)
        if not ok or not order_id:
            logger.warning("sell placement failed: %s", err)
            return

        st_sell = self._wait_and_finalize(order_id, "sell")
        if st_sell.get("status") != "filled":
            logger.info("sell not filled (status=%s) — stop", st_sell.get("status"))
            return

        sold_qty = _D(st_sell.get("filled", filled_qty))  # ИСПРАВЛЕНО: корректный фоллбэк через order_trades уже выше
        avg_sell = _D(st_sell.get("avg_price", sell_price))
        fee2 = sold_qty * avg_sell * (Decimal(self.cfg.fee_bps) / Decimal("10000"))

        # pnl и обновление risk/state
        pnl = (avg_sell - avg_buy) * sold_qty - (fee + fee2)
        self.risk.update_after_trade(pnl, self._get_equity_quote_approx(), is_win=(pnl >= 0))
        self.sync.update_after_trade("SELL", sold_qty, avg_sell, fee=fee2)
        self.mon.record_trade(self.cfg.pair, "SELL", float(sold_qty), float(avg_sell), pnl=float(pnl), success=True)

        # dust sweep по желанию
        self._maybe_dust_sweep("sell")

        # мониторинг
        self.mon.record_metric("last_roundtrip_pnl", float(pnl), MetricType.GAUGE, labels={"pair": self.cfg.pair})

    def run(self) -> None:
        logger.info("live trade started for %s (dry_run=%s, dust_sweep=%s)",
                    self.cfg.pair, self.cfg.dry_run, self.cfg.dust_sweep)
        while self._is_running:
            try:
                self.run_once()
            except Exception as e:
                self.mon.record_error(type(e).__name__, str(e), critical=False)
                logger.exception("iteration error: %s", e)
            time.sleep(self.cfg.loop_sleep_s)
        logger.info("live trade stopped")

    # ---------- helpers ----------
    def _get_equity_quote_approx(self) -> Decimal:
        """
        Примерная оценка текущего капитала в котировочной валюте:
        cash_quote + pos_qty * mid.
        """
        try:
            mid, _bid, _ask = self._get_mid_bid_ask()
        except Exception:
            mid = Decimal("0")
        return (self.sync.local.cash_eur + self.sync.local.pos_qty * mid).copy_abs()


# ==============================
# Пользовательская функция запуска
# ==============================
def run_live_trade(
    pair: str,
    qty_base: Optional[str] = None,
    qty_quote: Optional[str] = None,
    take_liquidity_bps: int = 0,
    fee_bps: int = 10,
    slip_bps: int = 2,
    loop_sleep_s: float = 2.0,
    dry_run: bool = False,
    dust_sweep: bool = False,  # ИСПРАВЛЕНО: флаг поддержан и передаётся
    min_trade_value_quote: str = "1.0",
    metrics_http_bind: Optional[str] = None,
    telegram_token: Optional[str] = None,
    telegram_chat_id: Optional[str] = None,
) -> None:
    """
    Универсальный запуск live-торговли с безопасными компонентами.
    Ключи EXMO подхватываются из окружения/хранилища в ExmoPrivate.
    """
    # EXMO клиент (внутри — thread-safe nonce, circuit-breaker, уникальный client_id)
    exmo = ExmoPrivate()

    cfg = LiveTradeConfig(
        pair=pair,
        qty_base=(_D(qty_base) if qty_base else None),
        qty_quote=(_D(qty_quote) if qty_quote else None),
        take_liquidity_bps=int(take_liquidity_bps),
        fee_bps=int(fee_bps),
        slip_bps=int(slip_bps),
        loop_sleep_s=float(loop_sleep_s),
        dry_run=bool(dry_run),
        dust_sweep=bool(dust_sweep),
        min_trade_value_quote=_D(min_trade_value_quote),
        metrics_http_bind=metrics_http_bind,
        telegram_token=telegram_token,
        telegram_chat_id=telegram_chat_id,
    )

    trader = LiveTrader(exmo, cfg)
    trader.run()


# ==============================
# CLI (опциональный)
# ==============================
def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser("live-trade")
    p.add_argument("--pair", required=True, help="EXMO pair, e.g. DOGE_EUR")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--qty-base", type=str, default=None, help="position size in base asset (e.g. 100)")
    g.add_argument("--qty-quote", type=str, default=None, help="budget in quote ccy (e.g. 50.0)")
    p.add_argument("--take-liquidity-bps", type=int, default=0, help=">0 to cross the spread")
    p.add_argument("--fee-bps", type=int, default=10)
    p.add_argument("--slip-bps", type=int, default=2)
    p.add_argument("--loop-sleep-s", type=float, default=2.0)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--dust-sweep", action="store_true", help="enable dust sweeping")
    p.add_argument("--min-trade-value-quote", type=str, default="1.0")
    p.add_argument("--metrics-http-bind", type=str, default=None, help="host:port for /metrics")
    p.add_argument("--telegram-token", type=str, default=None)
    p.add_argument("--telegram-chat-id", type=str, default=None)
    return p


def main(argv: Optional[list[str]] = None) -> None:
    args = _build_argparser().parse_args(argv)
    run_live_trade(
        pair=args.pair,
        qty_base=args.qty_base,
        qty_quote=args.qty_quote,
        take_liquidity_bps=args.take_liquidity_bps,
        fee_bps=args.fee_bps,
        slip_bps=args.slip_bps,
        loop_sleep_s=args.loop_sleep_s,
        dry_run=bool(args.dry_run),
        dust_sweep=bool(args.dust_sweep),
        min_trade_value_quote=args.min_trade_value_quote,
        metrics_http_bind=args.metrics_http_bind,
        telegram_token=args.telegram_token,
        telegram_chat_id=args.telegram_chat_id,
    )


if __name__ == "__main__":
    # Пример запуска:
    #   python -m src.presentation.live_trade --pair DOGE_EUR --qty-quote 25 --dry-run --dust-sweep
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    main()
