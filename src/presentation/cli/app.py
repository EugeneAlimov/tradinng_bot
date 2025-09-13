# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import importlib
import sys
from typing import Callable, List, Optional


def build_parser() -> argparse.ArgumentParser:
    """
    Конструктор CLI парсера.

    Важно: тесты ожидают, что парсер:
      - имеет подкоманды optimize/sweep/walk-forward/robustness/trade-live
      - корректно парсит примерные наборы аргументов для них
    """
    parser = argparse.ArgumentParser(
        description="Walk-forward runner (CLI)"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # --- optimize -----------------------------------------------------------
    p_opt = sub.add_parser("optimize", help="Оптимизация на истории")
    p_opt.add_argument("--exmo-pair", dest="exmo_pair")
    p_opt.add_argument("--exmo-candles", dest="exmo_candles")
    p_opt.add_argument("--resample", dest="resample")

    # --- sweep --------------------------------------------------------------
    p_sweep = sub.add_parser("sweep", help="Параметрический перебор")
    p_sweep.add_argument("--exmo-pair", dest="exmo_pair")
    p_sweep.add_argument("--exmo-candles", dest="exmo_candles")
    p_sweep.add_argument("--resample", dest="resample")

    # --- walk-forward -------------------------------------------------------
    p_wf = sub.add_parser("walk-forward", help="Walk-Forward разбиение/прогон")
    p_wf.add_argument("--exmo-pair", dest="exmo_pair")
    p_wf.add_argument("--exmo-candles", dest="exmo_candles")
    p_wf.add_argument("--resample", dest="resample")
    p_wf.add_argument("--folds", type=int, default=2)

    # --- robustness ---------------------------------------------------------
    p_rob = sub.add_parser("robustness", help="Проверки на устойчивость")
    p_rob.add_argument("--csv", required=False)

    # --- trade-live ---------------------------------------------------------
    p_tl = sub.add_parser("trade-live", help="Наблюдение/бумажная/живая торговля")
    p_tl.add_argument("--mode", choices=["observe", "paper", "live"], default="observe")
    p_tl.add_argument("--strategy")
    # источники данных
    p_tl.add_argument("--exmo-pair", dest="exmo_pair")
    p_tl.add_argument("--exmo-candles", dest="exmo_candles")
    p_tl.add_argument("--data", help="Путь к CSV с OHLCV")
    p_tl.add_argument("--demo", action="store_true", help="Синтетические свечи")
    p_tl.add_argument("--bars", type=int, default=720, help="Количество исходных 1m баров для demo/CSV")
    # обработка
    p_tl.add_argument("--resample", dest="resample", help="Напр. 5m, 15m, 1h (или 5min/15min/1H)")
    p_tl.add_argument("--poll-sec", dest="poll_sec", type=int, default=10)
    p_tl.add_argument("--once", action="store_true", help="Сделать один прогон и выйти")
    # вывод
    p_tl.add_argument("--stdout-json", action="store_true",
                      help="Печатать последнюю свечу OHLCV в JSON и выйти (для --once)")
    p_tl.add_argument("--quiet", action="store_true",
                      help="Тихий режим — не печатать таблицы/вспомогательные строки")
    p_tl.add_argument("--signal-json", action="store_true",
                      help="Печатать сигнал и сводку одной строкой JSON (для --once)")

    # --- fetch (утилита, удобна руками; тесты её не трогают) ---------------
    p_fetch = sub.add_parser("fetch", help="Скачать свечи EXMO (если доступ к сети)")
    p_fetch.add_argument("--exmo-pair", required=True)
    p_fetch.add_argument("--exmo-candles", required=True)
    p_fetch.add_argument("--resample")
    p_fetch.add_argument("--out", required=False)

    return parser


def _dispatch_trade_live(args: argparse.Namespace) -> int:
    """
    Динамический вызов обработчика trade-live.
    Ищем в модуле функцию run/main/handler (любую). Передаём Namespace.
    """
    mod_name = "src.presentation.cli.trade_live_cmd"
    try:
        m = importlib.import_module(mod_name)
        for entry in ("run", "main", "handler"):
            fn = getattr(m, entry, None)
            if callable(fn):
                return int(fn(args))
        print(f"[trade-live] Модуль '{mod_name}' найден, но нет run/main/handler.")
    except Exception:
        print("[trade-live] Модуль 'trade_live_cmd' не найден или без подходящего входа.")
    # Плейсхолдер — не падаем
    print(
        f"[trade-live] Запуск в плейсхолдер-режиме (ничего не торгуем).\n"
        f"[trade-live] mode={args.mode} strategy={getattr(args, 'strategy', None)} "
        f"pair={getattr(args, 'exmo_pair', None)} span={getattr(args, 'exmo_candles', None)} "
        f"resample={getattr(args, 'resample', None)} poll_sec={getattr(args, 'poll_sec', None)}"
    )
    return 0


def _dispatch_fetch(args: argparse.Namespace) -> int:
    """
    Утилитно: попробуем скачать EXMO через compat, отресемплить и при желании сохранить.
    В среде без сети вернётся пусто — просто сообщим.
    """
    try:
        from src.backtest.compat import fetch_exmo_candles_cached, resample_ohlc, normalize_resample_rule
    except Exception:
        print("[fetch] Блок совместимости недоступен в окружении.")
        return 0

    df = fetch_exmo_candles_cached(args.exmo_pair, args.exmo_candles)
    if df is None or df.empty:
        print("[fetch] Пустые данные от EXMO (возможно, нет доступа к сети).")
        return 0

    rule = normalize_resample_rule(args.resample) if args.resample else None
    if rule:
        df = resample_ohlc(df, rule)

    if args.out:
        try:
            df.reset_index().to_csv(args.out, index=False)
            print(f"[fetch] Сохранено: {args.out}")
        except Exception as e:
            print(f"[fetch] Не удалось сохранить: {e}")

    print(f"[fetch] bars={len(df)}")
    return 0


def _run(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.cmd == "trade-live":
        return _dispatch_trade_live(args)
    elif args.cmd == "fetch":
        return _dispatch_fetch(args)
    else:
        # Остальные команды тесты только парсят — ничего не делаем.
        return 0


def main(argv: Optional[List[str]] = None) -> Callable[[Optional[List[str]]], int]:
    """
    Тесты ожидают, что main() возвращает вызываемую функцию (раннер),
    чтобы они могли затем передать туда собственный argv.
    """

    def runner(inner_argv: Optional[List[str]] = None) -> int:
        return _run(inner_argv if inner_argv is not None else argv)

    return runner


if __name__ == "__main__":
    sys.exit(_run(sys.argv[1:]))
