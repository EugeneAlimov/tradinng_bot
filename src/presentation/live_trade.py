# src/presentation/live_trade.py
from __future__ import annotations

"""
Live-trade оркестратор.

Задачи файла:
- стабильные абсолютные импорты через `src.*`
- безопасная загрузка ключей (через src.security.credentials, с fallback на ENV)
- создание EXMO API клиента; обёртка SafeExmoWrapper (валидация)
- синхронизация состояния (StateSynchronizer)
- базовый цикл «наблюдения» (без изменений вашей стратегии), чтобы модуль импортировался и запускался
- минимальные точки интеграции с риск-менеджером/мониторингом при наличии

Важно: логика открытия/закрытия позиций намеренно упрощена — основной фокус на исправлении импортов
и согласованности слоёв. Ваши торговые решения/стратегия могут вызываться из этого цикла.
"""

import os
import sys
import time
import signal
import logging
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Optional, Dict, Any

# --- Логи ---
logger = logging.getLogger(__name__)
if not logger.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(_h)
logger.setLevel(logging.INFO)

# --- Абсолютные импорты наших модулей ---

# Безопасные креды (менеджер + удобная обёртка)
try:
    from src.security.credentials import load_secure_credentials
except Exception as e:
    logger.warning("secure.credentials not available, will fallback to ENV: %s", e)


    def load_secure_credentials() -> tuple[str, str]:
        key = os.environ.get("EXMO_KEY") or os.environ.get("EXMO_API_KEY") or ""
        secret = os.environ.get("EXMO_SECRET") or os.environ.get("EXMO_API_SECRET") or ""
        if not key or not secret:
            raise RuntimeError("No EXMO credentials in environment variables.")
        return key, secret

# EXMO API: пытаемся использовать улучшенный класс, иначе — оригинальный
_exmo_cls = None
try:
    from src.integrations.exmo_private import ImprovedExmoPrivate as _ExmoClient

    _exmo_cls = _ExmoClient
except Exception:
    try:
        from src.integrations.exmo_private import ExmoPrivate as _ExmoClient

        _exmo_cls = _ExmoClient
    except Exception as e:
        logger.error("Cannot import EXMO client class: %s", e)
        _ExmoClient = None  # type: ignore

# Обёртка с валидацией и валидатор
from src.infrastructure.exchange.validator import SafeExmoWrapper, ExchangeDataValidator

# Менеджер ордеров (улучшенный)
try:
    from src.infrastructure.exchange.order_manager import ImprovedOrderManager
except Exception:
    # на случай, если файл ещё переименован/не влит — даём понятную ошибку при использовании
    ImprovedOrderManager = None  # type: ignore

# Синхронизация с биржей
from src.application.state_sync import StateSynchronizer

# Риск-менеджмент (опционально)
try:
    from src.domain.risk.advanced_risk import AdvancedRiskManager, RiskLimits
except Exception:
    AdvancedRiskManager = None  # type: ignore
    RiskLimits = None  # type: ignore

# Мониторинг (опционально)
try:
    from src.monitoring.monitor import MonitoringSystem, AlertSeverity
except Exception:
    MonitoringSystem = None  # type: ignore
    AlertSeverity = None  # type: ignore


# ------------------------------
# Конфигурация live-торговли
# ------------------------------

@dataclass
class LiveTradeConfig:
    pair: str = "DOGE_EUR"
    state_path: str = "data/live_state.json"
    poll_sec: float = 3.0
    start_eur: Decimal = Decimal("1000")
    # лимиты риска — подхватываются при наличии AdvancedRiskManager
    max_position_pct: Decimal = Decimal("30")  # %
    max_daily_loss_pct: Decimal = Decimal("5")  # %
    # включение мониторинга
    enable_monitoring: bool = True


# ------------------------------
# Вспомогательные функции
# ------------------------------

def _make_exmo_client() -> Any:
    """Создаёт EXMO клиент по защищённым кредам."""
    if _ExmoClient is None:
        raise RuntimeError("EXMO client class is not available")

    api_key, api_secret = load_secure_credentials()
    logger.info("EXMO credentials loaded (safe).")
    return _ExmoClient(api_key, api_secret)


def _get_pair_ticker_validated(safe: SafeExmoWrapper, pair: str) -> Optional[Dict[str, Any]]:
    """Безопасно тянем тикер пары, с валидацией. Возвращает dict с Decimal-значениями либо None."""
    vt = safe.get_validated_ticker(pair)
    if vt is None:
        return None
    return {
        "pair": vt.pair,
        "bid": vt.bid,
        "ask": vt.ask,
        "last": vt.last,
        "volume_24h": vt.volume_24h,
        "high_24h": vt.high_24h,
        "low_24h": vt.low_24h,
    }


def _setup_risk_manager(cfg: LiveTradeConfig, equity: Decimal) -> Optional[AdvancedRiskManager]:
    if AdvancedRiskManager is None:
        logger.info("AdvancedRiskManager is not available – skipping advanced risk.")
        return None
    limits = RiskLimits(
        max_position_pct=cfg.max_position_pct,
        max_daily_loss_pct=cfg.max_daily_loss_pct,
    )
    return AdvancedRiskManager(limits=limits, initial_capital=equity)


def _setup_monitoring() -> Optional[MonitoringSystem]:
    if MonitoringSystem is None:
        logger.info("MonitoringSystem is not available – skipping monitoring.")
        return None
    mon = MonitoringSystem(bot_name="tradinng_bot")
    # Простая health-проверка: “жив ли процесс”
    mon.add_health_check("live_loop", lambda: True, interval=30)
    return mon


# ------------------------------
# Основной цикл live-торговли
# ------------------------------

def run_live_trade(cfg: LiveTradeConfig) -> None:
    """
    Базовый бесконечный цикл:
    - создаёт клиентов
    - синхронизирует состояние
    - периодически читает тикер и баланс, пишет метрики (если включён мониторинг)
    - (точки расширения) — здесь легко подключить вашу стратегию/сигналы/ордера
    """
    logger.info("Starting live trading: pair=%s", cfg.pair)

    # Ctrl+C / SIGTERM
    stop_flag = {"stop": False}

    def _stop_handler(signum, frame):
        stop_flag["stop"] = True
        logger.info("Stop signal (%s) received, finishing loop...", signum)

    signal.signal(signal.SIGINT, _stop_handler)
    signal.signal(signal.SIGTERM, _stop_handler)

    # EXMO client + safe wrapper
    exmo = _make_exmo_client()
    safe = SafeExmoWrapper(exmo)

    # Первичная синхронизация
    state = StateSynchronizer(exchange_api=exmo, pair=cfg.pair, state_path=cfg.state_path)
    ex_state = state.sync_with_exchange(force=True)

    # Equity оценки — грубая оценка: EUR-кэш + позиция*last
    start_eur = cfg.start_eur
    mon = _setup_monitoring() if cfg.enable_monitoring else None
    risk = _setup_risk_manager(cfg, start_eur)

    # Главный цикл
    while not stop_flag["stop"]:
        try:
            # тикер
            vt = _get_pair_ticker_validated(safe, cfg.pair)
            if not vt:
                logger.warning("Ticker is not available for %s", cfg.pair)
                time.sleep(cfg.poll_sec)
                continue

            base_ccy, quote_ccy = cfg.pair.split("_")
            # обновим синхронизацию c некоторой периодичностью (внутри есть own throttling)
            ex_state = state.sync_with_exchange(force=False)

            # оценим приблизительный equity в quote
            pos_qty = state.local_state.pos_qty  # Decimal
            last = vt["last"]  # Decimal
            # Если у нас хранится EUR-кэш — он уже в LocalState; если нет — оценим из биржевого баланса
            cash_eur = state.local_state.cash_eur
            if cash_eur == 0 and quote_ccy in ex_state.balances:
                cash_eur = ex_state.balances[quote_ccy]

            est_equity = (pos_qty * last) + cash_eur

            # мониторинг (по желанию)
            if mon:
                mon.record_metric("equity_eur", float(est_equity))
                mon.record_metric("position_qty", float(pos_qty))
                mon.record_metric("last_price", float(last))

            # точки интеграции стратегии:
            # - сюда можно воткнуть генератор сигналов
            # - и менеджер ордеров
            # Ниже — заглушка «ничего не делаем», только логируем состояние
            logger.info(
                "Tick %s: last=%.8f pos=%s %s equity≈%.2f %s",
                cfg.pair, float(last), str(pos_qty), base_ccy, float(est_equity), quote_ccy
            )

            time.sleep(cfg.poll_sec)

        except Exception as e:
            logger.exception("Live loop error: %s", e)
            if mon:
                mon.record_error(type(e).__name__, str(e), critical=False)
            time.sleep(max(1.0, cfg.poll_sec))

    logger.info("Live trading gracefully stopped.")


# ------------------------------
# CLI совместимость (ручной запуск)
# ------------------------------

def _parse_env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")


def _main_from_cli() -> None:
    """
    Небольшой CLI для прямого запуска модуля:
      $ python -m src.presentation.live_trade
    или
      $ python src/presentation/live_trade.py
    """
    pair = os.environ.get("PAIR", "DOGE_EUR")
    state_path = os.environ.get("STATE_PATH", "data/live_state.json")
    poll_sec = float(os.environ.get("POLL_SEC", "3.0"))
    start_eur = Decimal(os.environ.get("START_EUR", "1000"))
    enable_mon = _parse_env_bool("ENABLE_MONITORING", True)

    cfg = LiveTradeConfig(
        pair=pair,
        state_path=state_path,
        poll_sec=poll_sec,
        start_eur=start_eur,
        enable_monitoring=enable_mon,
    )
    run_live_trade(cfg)


if __name__ == "__main__":
    _main_from_cli()
