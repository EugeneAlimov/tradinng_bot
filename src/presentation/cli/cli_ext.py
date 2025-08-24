# src/presentation/cli/cli_ext.py
from __future__ import annotations

import argparse
import inspect
from typing import Any, Dict

from src.config.settings import get_settings
from src.domain.risk.risk_service import RiskService, RiskCfg
from src.infrastructure.notify.telegram import TelegramNotifier
from src.application.engine.integration import EngineIntegration


def extend_arg_parser(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """
    Добавляет флаги Risk/Alerts/Reconcile к уже существующему парсеру.
    Просто вызови это из своего app.py после создания ArgumentParser.
    """
    p.add_argument("--max-position-pct", type=float, default=None,
                   help="Max position fraction of equity, e.g. 0.25")
    p.add_argument("--stop-loss-bps", type=int, default=None,
                   help="Stop loss in bps, e.g. 300 = 3%")
    p.add_argument("--reconcile-threshold-qty", type=float, default=None,
                   help="Reconcile threshold on position qty delta")

    p.add_argument("--tg-token", type=str, default=None,
                   help="Telegram bot token")
    p.add_argument("--tg-chat", type=str, default=None,
                   help="Telegram chat id (user/channel)")

    return p


def build_runtime_components(args: argparse.Namespace):
    """
    Собирает Settings + Notifier + RiskService + EngineIntegration.
    Возвращает кортеж (settings, notifier, risk_service, integration).
    """
    s = get_settings()

    max_position_pct = args.max_position_pct if args.max_position_pct is not None else s.max_position_pct
    stop_loss_bps = args.stop_loss_bps if args.stop_loss_bps is not None else s.stop_loss_bps
    reconcile_threshold_qty = (
        args.reconcile_threshold_qty
        if args.reconcile_threshold_qty is not None
        else s.reconcile_threshold_qty
    )

    tg_token = args.tg_token if args.tg_token is not None else s.tg_token
    tg_chat = args.tg_chat if args.tg_chat is not None else s.tg_chat

    notifier = TelegramNotifier(tg_token, tg_chat)
    risk_service = RiskService(RiskCfg(
        max_position_pct=max_position_pct,
        stop_loss_bps=stop_loss_bps,
        max_daily_loss_bps=None,  # при необходимости добавишь флаг
    ))

    integration = EngineIntegration(
        notifier=notifier,
        risk=risk_service,
        reconcile_threshold_qty=reconcile_threshold_qty,
    )

    return s, notifier, risk_service, integration


def safe_instantiate_trade_engine(TradeEngineCls: Any, **kwargs) -> Any:
    """
    Безопасно создаёт TradeEngine, передавая только те kwargs,
    которые реально есть в его сигнатуре конструктора.
    Это позволяет не ломать существующий конструктор.
    """
    sig = inspect.signature(TradeEngineCls.__init__)
    allowed = {k: v for k, v in kwargs.items() if k in sig.parameters}
    return TradeEngineCls(**allowed)


def attach_if_supported(engine: Any, integration: EngineIntegration) -> None:
    """
    Пытается присоединить notifier/risk/reconcile_threshold прямо к engine (если у него есть такие поля).
    Это «мягкая» интеграция — ничего не сломает, если полей нет.
    """
    integration.attach(engine)


def wire_parser_and_components(p: argparse.ArgumentParser, args: argparse.Namespace, engine: Any) -> Dict[str, Any]:
    """
    Удобный «одноточечный» вызов: расширяет парсер и подключает компоненты к engine.
    Возвращает словарь с объектами на случай, если их нужно где‑то ещё использовать.
    """
    _, notifier, risk_service, integration = build_runtime_components(args)
    attach_if_supported(engine, integration)
    return {
        "notifier": notifier,
        "risk_service": risk_service,
        "integration": integration,
    }
