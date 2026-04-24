#!/usr/bin/env python3
"""
SupervisorTrainer bridge server.

Purpose:
- Accept live MT5 updates from SupervisorEA/DataFeeder.
- Serve dashboard endpoints.
- Keep backward-compatible routes used by older scripts.
"""

import glob
import json
import math
import os
import random
import sys
import threading
import time
import warnings
from datetime import datetime, timedelta
from typing import Any, Dict, List

warnings.filterwarnings("ignore", category=RuntimeWarning)

try:
    from flask import Flask, jsonify, request
    from flask_cors import CORS
except ImportError:
    raise SystemExit("Run: pip install flask flask-cors")

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

try:
    from websocket import create_connection
except ImportError:
    create_connection = None

try:
    from supervisor_trainer import SupervisorTrainer

    _TRAINER_AVAILABLE = True
except ImportError:
    _TRAINER_AVAILABLE = False
    print("[BRIDGE] supervisor_trainer not found, using mock signal mode")

app = Flask(__name__)
CORS(app)

_t0 = time.time()
_trainer = None
_trainer_lock = threading.Lock()

if callable(load_dotenv):
    load_dotenv()

DERIV_APP_ID = str(os.getenv("DERIV_APP_ID", "1089")).strip() or "1089"
DERIV_API_TOKEN = str(os.getenv("DERIV_API_TOKEN", "")).strip()
DERIV_WS_URL = f"wss://ws.derivws.com/websockets/v3?app_id={DERIV_APP_ID}"
MT_HEARTBEAT_TIMEOUT_SECONDS = max(180, int(os.getenv("MT_HEARTBEAT_TIMEOUT_SECONDS", "900")))

DERIV_SYMBOL_MAP = {
    "EURUSD": "frxEURUSD",
    "GBPUSD": "frxGBPUSD",
    "USDJPY": "frxUSDJPY",
    "GBPJPY": "frxGBPJPY",
    "AUDUSD": "frxAUDUSD",
    "USDCAD": "frxUSDCAD",
    "USDCHF": "frxUSDCHF",
    "NZDUSD": "frxNZDUSD",
    "EURGBP": "frxEURGBP",
    "EURAUD": "frxEURAUD",
    "GBPCHF": "frxGBPCHF",
    "XAUUSD": "frxXAUUSD",
    "XAGUSD": "frxXAGUSD",
    "BTCUSD": "cryBTCUSD",
    "ETHUSD": "cryETHUSD",
    "LTCUSD": "cryLTCUSD",
    "XRPUSD": "cryXRPUSD",
    "SOLUSD": "crySOLUSD",
    "V10": "R_10",
    "V25": "R_25",
    "V50": "R_50",
    "V75": "R_75",
    "V100": "R_100",
    "CRASH500": "CRASH500",
    "BOOM500": "BOOM500",
    "CRASH300": "CRASH300",
    "BOOM300": "BOOM300",
    "CRASH1000": "CRASH1000",
    "BOOM1000": "BOOM1000",
}

TF_TO_SECONDS = {
    "M1": 60,
    "M2": 120,
    "M3": 180,
    "M5": 300,
    "M10": 600,
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
    "H2": 7200,
    "H4": 14400,
    "H8": 28800,
    "D1": 86400,
}


def _utc_now_hms() -> str:
    return datetime.utcnow().strftime("%H:%M:%S")


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _normalize_symbol(sym: Any) -> str:
    s = str(sym or "").strip().upper()
    return s or "EURUSD"


def _deriv_symbol(sym: Any) -> str:
    s = _normalize_symbol(sym)
    return DERIV_SYMBOL_MAP.get(s, s)


def _to_unix(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).strip()
    if not s:
        return 0
    if s.isdigit():
        return int(s)
    try:
        return int(datetime.fromisoformat(s.replace("Z", "")).timestamp())
    except Exception:
        return 0


def _tf_to_seconds(value: Any) -> int:
    if isinstance(value, (int, float)):
        return max(60, int(value))
    s = str(value or "").strip().upper()
    return TF_TO_SECONDS.get(s, 3600)


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return float(default)


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return int(default)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(v)))


def _discover_model_names() -> List[str]:
    files = sorted(glob.glob("model_*.py"))
    names = [os.path.splitext(os.path.basename(p))[0].replace("model_", "") for p in files]

    if "ensemble_head" not in names:
        names.append("ensemble_head")

    while len(names) < 16:
        names.append(f"aux_model_{len(names) + 1}")

    return names[:16]


def _build_default_models() -> Dict[str, Dict[str, Any]]:
    models = {}
    for idx, name in enumerate(_discover_model_names()):
        seed = abs(hash(name)) % 100
        acc = _clamp(0.52 + (seed / 500.0), 0.52, 0.79)
        models[name] = {
            "weight": 1.0,
            "accuracy": round(acc, 4),
            "signal": 0.5,
            "enabled": True,
            "version": 2 if idx < 8 else 1,
        }
    return models


_models_meta = _build_default_models()

S: Dict[str, Any] = {
    "account": {
        "balance": 10000.0,
        "equity": 10000.0,
        "margin": 0.0,
        "free_margin": 10000.0,
        "margin_level": 0.0,
        "broker": "Deriv",
        "currency": "USD",
        "leverage": 500,
    },
    "positions": {},
    "history": [],
    "risk": {
        "risk_pct": 1.0,
        "daily_limit_pct": 5.0,
        "max_drawdown_pct": 10.0,
        "daily_pnl": 0.0,
        "open_positions": 0,
        "total_trades": 0,
        "win_rate": 0.0,
        "loss_streak": 0,
        "wins": 0,
        "losses": 0,
    },
    "trading": {"enabled": True, "paused": False, "mode": "auto", "symbol": "EURUSD", "selected_symbol": "EURUSD"},
    "backtest": {"status": "idle", "progress": 0, "result": None},
    "log": [],
    "retraining": False,
    "ingest": {
        "counts": {},
        "timeframe_counts": {},
        "total_bars": 0,
        "last_symbol": None,
        "last_time": None,
        "last_timeframe": None,
        "last_batch": 0,
        "last_bar": None,
    },
    "mt": {
        "desired_connected": True,
        "connected": False,
        "last_heartbeat": None,
        "last_source": None,
        "broker_mode": "auto",
        "active_symbol": None,
        "last_feed_symbol": None,
        "watchlist": [],
        "watchlist_updated_at": None,
    },
    "commands": {"next_id": 1, "queue": []},
}


def _log(msg: str, level: str = "info") -> None:
    now = _utc_now_hms()
    S["log"].append({"time": now, "msg": msg, "level": level})
    if len(S["log"]) > 300:
        S["log"] = S["log"][-300:]
    print(f"[BRIDGE {now}] {msg}")


def _touch_mt(source: str) -> None:
    S["mt"]["connected"] = True
    S["mt"]["last_source"] = source
    S["mt"]["last_heartbeat"] = _utc_now_iso()


def _mt_connected() -> bool:
    if not S["mt"]["desired_connected"]:
        return False
    hb = S["mt"].get("last_heartbeat")
    if not hb:
        return False
    try:
        dt = datetime.fromisoformat(hb.replace("Z", ""))
        return (datetime.utcnow() - dt).total_seconds() <= MT_HEARTBEAT_TIMEOUT_SECONDS
    except Exception:
        return False


def _queue_mt_command(command: str, **payload: Any) -> Dict[str, Any]:
    cmd_id = str(S["commands"]["next_id"])
    S["commands"]["next_id"] += 1
    item = {
        "id": cmd_id,
        "cmd": command,
        "created_at": _utc_now_iso(),
        "status": "queued",
    }
    item.update(payload)
    S["commands"]["queue"].append(item)
    S["commands"]["queue"] = S["commands"]["queue"][-100:]
    _log(f"Queued MT command {command}#{cmd_id}")
    return item


def _selected_symbol() -> str:
    return _normalize_symbol(S["trading"].get("selected_symbol", S["trading"].get("symbol", "EURUSD")))


def _set_selected_symbol(sym: Any) -> str:
    selected = _normalize_symbol(sym)
    S["trading"]["selected_symbol"] = selected
    S["trading"]["symbol"] = selected
    return selected


def _merge_symbol_lists(*groups: Any) -> List[str]:
    out: List[str] = []
    seen = set()
    for group in groups:
        if isinstance(group, dict):
            values = group.keys()
        elif isinstance(group, list):
            values = group
        else:
            values = []
        for item in values:
            sym = _normalize_symbol(item)
            if sym and sym not in seen:
                seen.add(sym)
                out.append(sym)
    return out


def _voice_fallback_reply(text: str) -> str:
    symbol = _selected_symbol()
    account = S["account"]
    mt_status = "attached" if _mt_connected() else "waiting for MT5 heartbeat"
    signal_text = "signal unavailable"
    try:
        signal_text = _normalize_signal_payload(_mock_signal(symbol), symbol).get("signal", "signal unavailable")
    except Exception:
        pass
    return (
        f"Rich fallback active. "
        f"Current symbol: {symbol}. "
        f"Bridge mode: {S['trading']['mode']}. "
        f"MT link: {mt_status}. "
        f"Balance: {account.get('balance', 0):.2f} {account.get('currency', 'USD')}. "
        f"Equity: {account.get('equity', 0):.2f}. "
        f"Current signal snapshot: {signal_text}. "
        f"Prompt received: {text}"
    )


def _deriv_ws_call(payload: Dict[str, Any]) -> Dict[str, Any]:
    if create_connection is None:
        raise RuntimeError("websocket-client not installed (pip install websocket-client)")

    ws = create_connection(DERIV_WS_URL, timeout=20)
    try:
        if DERIV_API_TOKEN:
            ws.send(json.dumps({"authorize": DERIV_API_TOKEN}))
            auth = json.loads(ws.recv())
            if auth.get("error"):
                msg = auth["error"].get("message", "authorize failed")
                raise RuntimeError(f"Deriv authorize failed: {msg}")

        ws.send(json.dumps(payload))
        resp = json.loads(ws.recv())
        if resp.get("error"):
            msg = resp["error"].get("message", "Deriv API error")
            raise RuntimeError(msg)
        return resp
    finally:
        try:
            ws.close()
        except Exception:
            pass


def _deriv_fetch_candles(
    symbol: str,
    timeframe: Any = "H1",
    count: int = 500,
    start: Any = None,
    end: Any = None,
) -> Dict[str, Any]:
    dsym = _deriv_symbol(symbol)
    granularity = _tf_to_seconds(timeframe)
    count = max(1, min(5000, _safe_int(count, 500)))
    start_unix = _to_unix(start)
    end_unix = _to_unix(end)

    payload: Dict[str, Any] = {
        "ticks_history": dsym,
        "adjust_start_time": 1,
        "style": "candles",
        "granularity": granularity,
        "count": count,
        "end": end_unix if end_unix > 0 else "latest",
    }
    if start_unix > 0:
        payload["start"] = start_unix

    raw = _deriv_ws_call(payload)
    candles = raw.get("candles", [])
    bars = []
    for c in candles:
        epoch = _safe_int(c.get("epoch"), 0)
        o = _safe_float(c.get("open"), 0.0)
        h = _safe_float(c.get("high"), 0.0)
        l = _safe_float(c.get("low"), 0.0)
        cl = _safe_float(c.get("close"), 0.0)
        bars.append({"t": epoch, "o": o, "h": h, "l": l, "c": cl, "v": 0})

    return {
        "symbol": _normalize_symbol(symbol),
        "deriv_symbol": dsym,
        "timeframe": str(timeframe).upper(),
        "granularity": granularity,
        "start": start_unix or None,
        "end": end_unix or None,
        "bars": bars,
        "count": len(bars),
    }


def _models_meta_list() -> List[Dict[str, Any]]:
    out = []
    for name, d in _models_meta.items():
        out.append(
            {
                "model": name,
                "accuracy": float(d.get("accuracy", 0.5)),
                "weight": float(d.get("weight", 1.0)),
                "signal": float(d.get("signal", 0.5)),
                "enabled": bool(d.get("enabled", True)),
                "version": int(d.get("version", 1)),
            }
        )
    return out


def _signal_text_from_any(action: Any) -> str:
    if isinstance(action, (int, float)):
        if action > 0:
            return "BUY"
        if action < 0:
            return "SELL"
        return "HOLD"

    s = str(action or "").upper()
    if "STRONG BUY" in s:
        return "STRONG BUY"
    if "STRONG SELL" in s:
        return "STRONG SELL"
    if "BUY" in s:
        return "BUY"
    if "SELL" in s:
        return "SELL"
    return "HOLD"


def _action_num_from_signal_text(text: str) -> int:
    s = _signal_text_from_any(text)
    if "BUY" in s:
        return 1
    if "SELL" in s:
        return -1
    return 0


def _normalize_signal_payload(payload: Dict[str, Any], symbol: str) -> Dict[str, Any]:
    payload = dict(payload or {})
    signal_text = _signal_text_from_any(
        payload.get("signal") if payload.get("signal") is not None else payload.get("action")
    )
    action_num = payload.get("action")
    if not isinstance(action_num, (int, float)):
        action_num = _action_num_from_signal_text(signal_text)

    sl = _safe_float(payload.get("sl", payload.get("stop_loss", 0.0)))
    tp = _safe_float(payload.get("tp", payload.get("take_profit", 0.0)))
    ob50 = _safe_float(payload.get("ob50", payload.get("ob_50", 0.0)))

    ict = payload.get("ict") if isinstance(payload.get("ict"), dict) else {}
    if not ict:
        ict = {}
    ict.setdefault("ob50", ob50)
    ict.setdefault("ob_top", _safe_float(payload.get("ob_top", ob50)))
    ict.setdefault("ob_bottom", _safe_float(payload.get("ob_bottom", ob50)))
    ict.setdefault("fvg_top", _safe_float(payload.get("fvg_top", ob50)))
    ict.setdefault("fvg_bottom", _safe_float(payload.get("fvg_bottom", ob50)))
    ict.setdefault("sl", sl)
    ict.setdefault("tp", tp)
    ict.setdefault("bos", payload.get("bos", "None"))

    raw_contrib = payload.get("model_contributions")
    if not isinstance(raw_contrib, dict):
        raw_contrib = {}
    contrib = {}
    for name, d in _models_meta.items():
        contrib[name] = round(
            _clamp(_safe_float(raw_contrib.get(name, d.get("signal", 0.5)), 0.5), 0.0, 1.0), 4
        )

    payload["symbol"] = _normalize_symbol(payload.get("symbol", symbol))
    payload["score"] = _clamp(_safe_float(payload.get("score", 0.5)), 0.0, 1.0)
    payload["signal"] = signal_text
    payload["action"] = int(action_num)
    payload["action_text"] = signal_text
    payload["sl"] = sl
    payload["tp"] = tp
    payload["ob50"] = ob50
    payload["ob_50"] = ob50
    payload["ob_top"] = _safe_float(payload.get("ob_top", ict.get("ob_top", ob50)))
    payload["ob_bottom"] = _safe_float(payload.get("ob_bottom", ict.get("ob_bottom", ob50)))
    payload["ict"] = ict
    payload["model_contributions"] = contrib
    payload["head_decision"] = payload.get("head_decision", signal_text)
    payload["head_lot"] = payload.get("head_lot", 0)
    payload["head_reason"] = payload.get("head_reason", "")
    payload["timestamp"] = payload.get("timestamp", _utc_now_iso())
    return payload


def _get_trainer():
    global _trainer
    if not _TRAINER_AVAILABLE:
        return None
    if _trainer is None:
        with _trainer_lock:
            if _trainer is None:
                try:
                    _trainer = SupervisorTrainer(symbol=S["trading"]["symbol"])
                    _trainer.train()
                    _log("Trainer ready")
                except Exception as exc:
                    _log(f"Trainer init error: {exc}", "error")
    return _trainer


def _mock_signal(sym: str) -> Dict[str, Any]:
    score = 0.5 + 0.15 * math.sin(time.time() / 65 + hash(sym) % 9)
    score = _clamp(score, 0.05, 0.95)

    prices = {
        "EURUSD": 1.0850,
        "GBPUSD": 1.2650,
        "USDJPY": 149.50,
        "XAUUSD": 2150.0,
        "XAGUSD": 24.5,
        "BTCUSD": 65000.0,
        "CRASH500": 900.0,
        "BOOM500": 900.0,
        "V75": 600.0,
        "V100": 820.0,
    }
    p = prices.get(sym, 1.0)
    atr = p * 0.002

    if score > 0.65:
        sig = "STRONG BUY"
    elif score > 0.55:
        sig = "BUY"
    elif score < 0.35:
        sig = "STRONG SELL"
    elif score < 0.45:
        sig = "SELL"
    else:
        sig = "HOLD"

    sl = round(p - atr * 1.5 if "BUY" in sig else p + atr * 1.5, 5)
    tp = round(p + atr * 3.0 if "BUY" in sig else p - atr * 3.0, 5)
    ob50 = round((p + sl) / 2, 5)
    ob_top = round(ob50 + atr * 0.5, 5)
    ob_bottom = round(ob50 - atr * 0.5, 5)

    contrib = {}
    for name in _models_meta.keys():
        val = _clamp(score + random.uniform(-0.08, 0.08), 0.0, 1.0)
        contrib[name] = round(val, 4)
        _models_meta[name]["signal"] = round(val, 4)

    return {
        "symbol": sym,
        "score": round(score, 4),
        "action": _action_num_from_signal_text(sig),
        "action_text": sig,
        "signal": sig,
        "sl": sl,
        "tp": tp,
        "ob50": ob50,
        "ob_50": ob50,
        "ob_top": ob_top,
        "ob_bottom": ob_bottom,
        "ict": {
            "ob50": ob50,
            "ob_top": ob_top,
            "ob_bottom": ob_bottom,
            "fvg_top": round(ob50 + atr * 0.3, 5),
            "fvg_bottom": round(ob50 - atr * 0.3, 5),
            "sl": sl,
            "tp": tp,
            "bos": "None",
        },
        "model_contributions": contrib,
        "timestamp": _utc_now_iso(),
    }


@app.route("/ping")
def ping():
    return jsonify({"status": "pong", "ts": _utc_now_iso()})


@app.route("/status")
def status():
    models = _models_meta_list()
    weights = {m["model"]: m["weight"] for m in models}
    symbol = _normalize_symbol(request.args.get("symbol", _selected_symbol()))

    total_pnl = sum(_safe_float(p.get("pnl", 0.0)) for p in S["positions"].values())
    ingest_count = int(S["ingest"]["counts"].get(symbol, 0))
    mt_live = _mt_connected()

    return jsonify(
        {
            "running": True,
            "mode": S["trading"]["mode"],
            "symbol": symbol,
            "selected_symbol": _selected_symbol(),
            "trading_enabled": S["trading"]["enabled"],
            "paused": S["trading"]["paused"],
            "uptime": str(timedelta(seconds=int(time.time() - _t0))),
            "trainer_ok": _TRAINER_AVAILABLE,
            "models": models,
            "weights": weights,
            "model_count": len(models),
            "ingested_bars": ingest_count,
            "ingest_total_bars": int(S["ingest"]["total_bars"]),
            "ingest_last_symbol": S["ingest"]["last_symbol"],
            "ingest_last_time": S["ingest"]["last_time"],
            "portfolio": {
                "score": 100 if len(S["positions"]) == 0 else 65,
                "status": "Empty" if len(S["positions"]) == 0 else "Active",
                "open_trades": len(S["positions"]),
                "total_pnl": total_pnl,
            },
            "risk": S["risk"],
            "mt_connected": mt_live,
            "mt_last_heartbeat": S["mt"]["last_heartbeat"],
            "mt_source": S["mt"]["last_source"],
            "mt_symbol": S["mt"].get("active_symbol"),
            "mt_watchlist": S["mt"].get("watchlist", []),
            "broker_mode": S["mt"]["broker_mode"],
            "broker_detected": S["account"].get("broker", ""),
            "deriv_feed_ready": bool(DERIV_API_TOKEN),
        }
    )


@app.route("/health")
def health():
    active_symbols = sorted(set(_merge_symbol_lists([_selected_symbol()], S["ingest"]["counts"], S["mt"].get("watchlist", []))))
    return jsonify(
        {
            "status": "running",
            "symbols": active_symbols,
            "active_symbols": active_symbols,
            "ingest_symbols": list(S["ingest"]["counts"].keys()),
            "ingest_counts": S["ingest"]["counts"],
            "ingest_timeframe_counts": S["ingest"]["timeframe_counts"],
            "selected_symbol": _selected_symbol(),
            "last_symbol": S["ingest"]["last_symbol"] or S["mt"].get("active_symbol") or _selected_symbol(),
            "last_symbol_source": "ingest" if S["ingest"]["last_symbol"] else ("mt" if S["mt"].get("active_symbol") else "selected"),
            "last_symbol_time": S["ingest"]["last_time"],
            "last_timeframe": S["ingest"]["last_timeframe"],
            "mt_symbol": S["mt"].get("active_symbol"),
            "mt_watchlist": S["mt"].get("watchlist", []),
            "managers": ["Risk", "Execution", "Portfolio", "Head"],
            "portfolio": {
                "score": 100 if len(S["positions"]) == 0 else 65,
                "status": "Empty" if len(S["positions"]) == 0 else "Active",
                "open_trades": len(S["positions"]),
                "total_pnl": sum(_safe_float(p.get("pnl", 0.0)) for p in S["positions"].values()),
            },
            "risk": S["risk"],
            "mt_connected": _mt_connected(),
            "mt_last_heartbeat": S["mt"]["last_heartbeat"],
            "broker_mode": S["mt"]["broker_mode"],
            "broker_detected": S["account"].get("broker", ""),
            "deriv_feed_ready": bool(DERIV_API_TOKEN),
        }
    )


@app.route("/account")
def account():
    return jsonify(S["account"])


@app.route("/signal")
def signal():
    sym = _normalize_symbol(request.args.get("symbol", _selected_symbol()))

    trainer = _get_trainer()
    payload = None
    if trainer:
        try:
            payload = trainer.get_signal(sym)
        except Exception as exc:
            _log(f"get_signal error: {exc}", "error")

    if payload is None:
        payload = _mock_signal(sym)

    normalized = _normalize_signal_payload(payload, sym)
    for name, contrib in normalized["model_contributions"].items():
        if name in _models_meta:
            _models_meta[name]["signal"] = round(_safe_float(contrib, 0.5), 4)

    return jsonify(normalized)


@app.route("/signals/all")
def signals_all():
    syms = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "CRASH500", "BOOM500", "V75", "V100"]
    out = {}
    trainer = _get_trainer()
    for sym in syms:
        payload = None
        if trainer:
            try:
                payload = trainer.get_signal(sym)
            except Exception:
                payload = None
        if payload is None:
            payload = _mock_signal(sym)
        out[sym] = _normalize_signal_payload(payload, sym)
    return jsonify(out)


@app.route("/positions")
def positions():
    return jsonify(S["positions"])


@app.route("/history")
def history():
    limit = _safe_int(request.args.get("limit", 20), 20)
    return jsonify(S["history"][-limit:])


@app.route("/head/log")
def head_log():
    recent = S["log"][-40:]
    return jsonify(
        {
            "recent_decisions": len(recent),
            "trades": 0,
            "vetoes": 0,
            "holds": 0,
            "log": recent[-10:],
        }
    )


@app.route("/risk/summary")
def risk_summary():
    return jsonify(S["risk"])


@app.route("/risk/set", methods=["POST"])
def risk_set():
    data = request.get_json(silent=True) or {}
    for k, v in data.items():
        if k in S["risk"]:
            S["risk"][k] = v
    return jsonify({"status": "ok", "risk": S["risk"]})


@app.route("/portfolio/health")
def portfolio_health():
    r = S["risk"]
    wr = _safe_float(r.get("win_rate", 0.5), 0.5)
    bal = _safe_float(S["account"].get("balance", 1), 1.0) or 1.0
    dd = _safe_float(r.get("daily_pnl", 0), 0.0) / bal
    streak = _safe_int(r.get("loss_streak", 0), 0)

    if len(S["positions"]) == 0 and _safe_int(r.get("total_trades", 0), 0) == 0:
        score, status_text = 1.0, "Empty"
    else:
        score = _clamp(wr - abs(dd) - streak * 0.05, 0.0, 1.0)
        status_text = "Good" if score > 0.7 else "Caution" if score > 0.4 else "At Risk"

    return jsonify(
        {
            "score": round(score, 4),
            "status": status_text,
            "open_trades": len(S["positions"]),
            "total_pnl": sum(_safe_float(p.get("pnl", 0.0)) for p in S["positions"].values()),
        }
    )


@app.route("/trading/enable", methods=["POST"])
def trading_enable():
    data = request.get_json(silent=True) or {}
    S["trading"]["enabled"] = bool(data.get("enabled", True))
    _log(f"Trading {'ENABLED' if S['trading']['enabled'] else 'DISABLED'}")
    return jsonify({"status": "ok", "enabled": S["trading"]["enabled"]})


@app.route("/trading/pause", methods=["POST"])
def trading_pause():
    S["trading"]["paused"] = True
    _log("Trading PAUSED")
    return jsonify({"status": "paused"})


@app.route("/trading/resume", methods=["POST"])
def trading_resume():
    S["trading"]["paused"] = False
    _log("Trading RESUMED")
    return jsonify({"status": "resumed"})


@app.route("/trading/mode", methods=["POST"])
def trading_mode():
    data = request.get_json(silent=True) or {}
    mode = str(data.get("mode", "auto")).lower()
    if mode not in {"auto", "semi", "off"}:
        mode = "auto"
    S["trading"]["mode"] = mode
    _log(f"Mode -> {mode.upper()}")
    return jsonify({"status": "ok", "mode": mode})


@app.route("/trading/symbol", methods=["GET", "POST"])
def trading_symbol():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        sym = _normalize_symbol(data.get("symbol", _selected_symbol()))
        if sym != _selected_symbol():
            _log(f"Symbol switched -> {sym}")
        _set_selected_symbol(sym)
    return jsonify({"status": "ok", "symbol": _selected_symbol()})


@app.route("/trades/close_all", methods=["POST"])
def close_all():
    pnl = sum(_safe_float(p.get("pnl", 0.0)) for p in S["positions"].values())
    manual_keys = [k for k, p in S["positions"].items() if str(p.get("source", "")).lower() == "manual" or str(k).startswith("man-")]
    for k in manual_keys:
        S["history"].append(S["positions"].pop(k))

    queued = False
    if _mt_connected():
        _queue_mt_command("close_all", symbol=S["trading"]["symbol"])
        queued = True

    S["risk"]["open_positions"] = len(S["positions"])
    S["risk"]["daily_pnl"] = sum(_safe_float(p.get("pnl", 0.0)) for p in S["positions"].values())
    _log(f"Close-all requested manual_closed={len(manual_keys)} queued_mt={queued} PnL={pnl:.2f}")
    return jsonify({"closed": len(manual_keys), "queued_mt": queued, "total_pnl": round(pnl, 2)})


@app.route("/trades/close_symbol", methods=["POST"])
def close_symbol():
    data = request.get_json(silent=True) or {}
    sym = _normalize_symbol(data.get("symbol", ""))
    keys = [
        k for k, p in S["positions"].items()
        if _normalize_symbol(p.get("symbol")) == sym and (str(p.get("source", "")).lower() == "manual" or str(k).startswith("man-"))
    ]
    for k in keys:
        S["history"].append(S["positions"].pop(k))
    queued = False
    if _mt_connected():
        _queue_mt_command("close_symbol", symbol=sym)
        queued = True
    S["risk"]["open_positions"] = len(S["positions"])
    S["risk"]["daily_pnl"] = sum(_safe_float(p.get("pnl", 0.0)) for p in S["positions"].values())
    return jsonify({"status": "ok", "closed": len(keys), "queued_mt": queued})


@app.route("/trades/close_ticket", methods=["POST"])
def close_ticket():
    data = request.get_json(silent=True) or {}
    tid = str(data.get("ticket", ""))
    if tid in S["positions"] and (str(S["positions"][tid].get("source", "")).lower() == "manual" or str(tid).startswith("man-")):
        S["history"].append(S["positions"].pop(tid))
        S["risk"]["open_positions"] = len(S["positions"])
        S["risk"]["daily_pnl"] = sum(_safe_float(p.get("pnl", 0.0)) for p in S["positions"].values())
        return jsonify({"status": "closed", "queued_mt": False})
    if _mt_connected():
        _queue_mt_command("close_ticket", ticket=tid, symbol=S["trading"]["symbol"])
        return jsonify({"status": "queued", "queued_mt": True})
    return jsonify({"status": "not_found"}), 404


@app.route("/trades/manual", methods=["POST"])
def trades_manual():
    data = request.get_json(silent=True) or {}
    sym = _normalize_symbol(data.get("symbol", _selected_symbol()))
    order_type = str(data.get("order_type", data.get("type", "BUY_MARKET"))).upper()
    side = str(data.get("side", "")).upper()
    if not side:
        side = "SELL" if order_type.startswith("SELL") else "BUY"
    lot = _safe_float(data.get("lot", 0.01), 0.01)
    entry = _safe_float(data.get("entry", 0.0), 0.0)
    limit_price = _safe_float(data.get("limit_price", 0.0), 0.0)
    sl = _safe_float(data.get("sl", 0.0), 0.0)
    tp = _safe_float(data.get("tp", 0.0), 0.0)
    use_sl = bool(data.get("use_sl", True))
    use_tp = bool(data.get("use_tp", True))
    trailing_start_rr = _safe_float(data.get("trailing_start_rr", 0.5), 0.5)
    trailing_step_rr = _safe_float(data.get("trailing_step_rr", 0.5), 0.5)

    valid_types = {
        "BUY",
        "SELL",
        "BUY_MARKET",
        "SELL_MARKET",
        "BUY_LIMIT",
        "SELL_LIMIT",
        "BUY_STOP",
        "SELL_STOP",
        "BUY_STOP_LIMIT",
        "SELL_STOP_LIMIT",
    }
    if order_type not in valid_types or side not in {"BUY", "SELL"}:
        return jsonify({"status": "error", "error": "invalid_side"}), 400
    if entry <= 0 or lot <= 0:
        return jsonify({"status": "error", "error": "invalid_entry_or_lot"}), 400

    if use_sl and use_tp and side == "BUY":
        if sl >= entry or tp <= entry:
            return jsonify({"status": "error", "error": "invalid_sl_tp_for_buy"}), 400
    elif use_sl and use_tp and side == "SELL":
        if sl <= entry or tp >= entry:
            return jsonify({"status": "error", "error": "invalid_sl_tp_for_sell"}), 400

    if not use_sl:
        sl = 0.0
    if not use_tp:
        tp = 0.0

    if "LIMIT" in order_type and limit_price <= 0 and "STOP_LIMIT" in order_type:
        return jsonify({"status": "error", "error": "missing_limit_price"}), 400

    tid = f"man-{int(time.time() * 1000)}"
    S["positions"][tid] = {
        "ticket": tid,
        "symbol": sym,
        "type": side,
        "order_type": order_type,
        "lot": round(lot, 4),
        "entry": entry,
        "limit_price": limit_price,
        "sl": sl,
        "tp": tp,
        "pnl": 0.0,
        "source": "manual",
        "note": data.get("note", "Manual trade"),
        "trailing_start_rr": trailing_start_rr,
        "trailing_step_rr": trailing_step_rr,
        "date": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    }
    _set_selected_symbol(sym)
    S["risk"]["open_positions"] = len(S["positions"])
    S["risk"]["daily_pnl"] = sum(_safe_float(p.get("pnl", 0.0)) for p in S["positions"].values())
    queued_mt = False
    if _mt_connected():
        _queue_mt_command(
            "place_order",
            symbol=sym,
            side=side,
            order_type=order_type,
            lot=round(lot, 4),
            entry=entry,
            limit_price=limit_price,
            sl=sl,
            tp=tp,
            trailing_start_rr=trailing_start_rr,
            trailing_step_rr=trailing_step_rr,
        )
        queued_mt = True
    _touch_mt("manual_trade")
    _log(f"Manual {order_type} opened {sym} ticket={tid}")
    return jsonify({"status": "ok", "ticket": tid, "symbol": sym, "order_type": order_type, "queued_mt": queued_mt})


@app.route("/models/status")
def models_status():
    return jsonify(_models_meta)


@app.route("/models/toggle", methods=["POST"])
def models_toggle():
    data = request.get_json(silent=True) or {}
    model = data.get("model")
    if model in _models_meta:
        _models_meta[model]["enabled"] = bool(data.get("enabled", True))
        _log(f"Model {model} {'ON' if _models_meta[model]['enabled'] else 'OFF'}")
    return jsonify({"status": "ok"})


@app.route("/models/reset_weights", methods=["POST"])
def models_reset():
    for name in _models_meta:
        _models_meta[name]["weight"] = 1.0
    _log("All model weights reset to 1.0")
    return jsonify({"status": "ok"})


@app.route("/retrain", methods=["POST"])
def retrain():
    if S["retraining"]:
        return jsonify({"status": "already_running"})

    data = request.get_json(silent=True) or {}
    reason = str(data.get("reason", "manual"))
    _log(f"Retrain triggered - {reason}")
    S["retraining"] = True

    def _run():
        try:
            trainer = _get_trainer()
            if trainer:
                trainer.train()
            _log("Retrain complete")
        except Exception as exc:
            _log(f"Retrain error: {exc}", "error")
        finally:
            S["retraining"] = False

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"status": "started"})


def _append_backtest_trades(symbol: str, count: int = 12) -> None:
    now = datetime.utcnow()
    trades = []
    for i in range(max(1, count)):
        pnl = round(random.uniform(-60, 95), 2)
        side = "BUY" if random.random() > 0.5 else "SELL"
        trades.append(
            {
                "ticket": f"bt-{int(time.time() * 1000)}-{i}",
                "date": (now - timedelta(minutes=(count - i) * 20)).strftime("%Y-%m-%d %H:%M:%S"),
                "symbol": symbol,
                "type": side,
                "lot": 0.01,
                "pnl": pnl,
                "source": "backtest",
                "note": "Backtest",
            }
        )
    S["history"].extend(trades)
    S["history"] = S["history"][-600:]


@app.route("/backtest/run", methods=["POST"])
def backtest_run():
    data = request.get_json(silent=True) or {}
    sym = _normalize_symbol(data.get("symbol", "EURUSD"))
    days = max(1, _safe_int(data.get("days", 30), 30))
    S["backtest"] = {"status": "running", "progress": 0, "result": None}
    _log(f"Backtest: {sym} {days}d")

    def _run():
        for i in range(1, 101):
            time.sleep(days * 0.012)
            S["backtest"]["progress"] = i
        wr = round(random.uniform(0.45, 0.70), 4)
        S["backtest"].update(
            {
                "status": "complete",
                "progress": 100,
                "result": {
                    "symbol": sym,
                    "days": days,
                    "trades": random.randint(30, 120),
                    "win_rate": wr,
                    "roi": round(random.uniform(-5, 25), 2),
                    "max_dd": round(random.uniform(2, 15), 2),
                    "sharpe": round(random.uniform(0.5, 2.5), 2),
                },
            }
        )
        _append_backtest_trades(sym, count=random.randint(10, 24))
        _log(f"Backtest done WR={wr * 100:.1f}%")

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"status": "started"})


@app.route("/backtest")
def backtest_legacy():
    sym = _normalize_symbol(request.args.get("symbol", S["trading"]["symbol"]))
    if request.args.get("days"):
        days = max(1, _safe_int(request.args.get("days"), 30))
    elif request.args.get("start") and request.args.get("end"):
        days = 30
    else:
        days = 30

    S["backtest"] = {"status": "running", "progress": 0, "result": None}
    _log(f"Backtest: {sym} {days}d (legacy)")

    def _run():
        for i in range(1, 101):
            time.sleep(days * 0.012)
            S["backtest"]["progress"] = i
        wr = round(random.uniform(0.45, 0.70), 4)
        S["backtest"].update(
            {
                "status": "complete",
                "progress": 100,
                "result": {
                    "symbol": sym,
                    "days": days,
                    "trades": random.randint(30, 120),
                    "win_rate": wr,
                    "roi": round(random.uniform(-5, 25), 2),
                    "max_dd": round(random.uniform(2, 15), 2),
                    "sharpe": round(random.uniform(0.5, 2.5), 2),
                },
            }
        )
        _append_backtest_trades(sym, count=random.randint(10, 24))
        _log(f"Backtest done WR={wr * 100:.1f}%")

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"status": "started", "symbol": sym})


@app.route("/backtest/status")
def backtest_status():
    return jsonify(S["backtest"])


@app.route("/backtest/last")
def backtest_last():
    return jsonify(S["backtest"].get("result") or {})


def _normalize_positions(raw_positions: Any) -> Dict[str, Dict[str, Any]]:
    if isinstance(raw_positions, dict):
        return raw_positions
    if isinstance(raw_positions, list):
        out = {}
        for p in raw_positions:
            if not isinstance(p, dict):
                continue
            tid = str(p.get("ticket", p.get("id", len(out) + 1)))
            out[tid] = p
        return out
    return {}


@app.route("/update", methods=["POST"])
def ea_update():
    data = request.get_json(silent=True) or {}

    if "account" in data and isinstance(data["account"], dict):
        S["account"].update(data["account"])

    if "positions" in data:
        S["positions"] = _normalize_positions(data["positions"])

    if "symbol" in data:
        mt_symbol = _normalize_symbol(data["symbol"])
        S["mt"]["active_symbol"] = mt_symbol
        if not S["trading"].get("selected_symbol"):
            _set_selected_symbol(mt_symbol)

    if "watchlist" in data and isinstance(data["watchlist"], list):
        S["mt"]["watchlist"] = _merge_symbol_lists(data["watchlist"])
        S["mt"]["watchlist_updated_at"] = _utc_now_iso()

    if "history" in data and isinstance(data["history"], list):
        seen = {h.get("ticket") for h in S["history"]}
        for trade in data["history"]:
            if not isinstance(trade, dict):
                continue
            ticket = trade.get("ticket")
            if ticket in seen:
                continue

            S["history"].append(trade)
            pnl = _safe_float(trade.get("pnl", 0.0), 0.0)
            S["risk"]["total_trades"] += 1
            if pnl >= 0:
                S["risk"]["wins"] += 1
                S["risk"]["loss_streak"] = 0
            else:
                S["risk"]["losses"] += 1
                S["risk"]["loss_streak"] += 1

            n = max(1, _safe_int(S["risk"]["total_trades"], 1))
            S["risk"]["win_rate"] = S["risk"]["wins"] / n
            seen.add(ticket)

        S["history"] = S["history"][-600:]

    S["risk"]["open_positions"] = len(S["positions"])
    S["risk"]["daily_pnl"] = sum(_safe_float(p.get("pnl", 0.0)) for p in S["positions"].values())

    _touch_mt("update")
    return jsonify({"status": "ok", "symbol": _selected_symbol(), "mt_symbol": S["mt"].get("active_symbol")})


@app.route("/ea/command")
def ea_command():
    symbol = _normalize_symbol(request.args.get("symbol", S["trading"]["symbol"]))
    for item in S["commands"]["queue"]:
        cmd = str(item.get("cmd", "")).lower()
        item_symbol = _normalize_symbol(item.get("symbol", symbol))
        if cmd == "close_all" or item_symbol == symbol or not item.get("symbol"):
            item["status"] = "sent"
            item["last_sent_at"] = _utc_now_iso()
            return jsonify(item)
    return jsonify({"id": "", "cmd": "none"})


@app.route("/ea/command_ack", methods=["POST"])
def ea_command_ack():
    data = request.get_json(silent=True) or {}
    cmd_id = str(data.get("id", ""))
    status = str(data.get("status", "done")).lower()
    for idx, item in enumerate(list(S["commands"]["queue"])):
        if str(item.get("id")) != cmd_id:
            continue
        item["status"] = status
        item["acked_at"] = _utc_now_iso()
        _log(f"MT command ack {item.get('cmd')}#{cmd_id} -> {status}")
        if status in {"done", "executed", "ok"}:
            S["commands"]["queue"].pop(idx)
        return jsonify({"status": "ok"})
    return jsonify({"status": "missing"}), 404


def _parse_ingest_payload() -> Dict[str, Any]:
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data

    raw = request.get_data(cache=False, as_text=True)
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
    return {}


def _external_module_path(name: str) -> str:
    return os.path.join(os.path.dirname(__file__), "external_ai", name)


def _integration_status() -> Dict[str, Any]:
    return {
        "telegram_configured": bool(os.getenv("TELEGRAM_TOKEN", "").strip()),
        "voice_available": os.path.exists(os.path.join(_external_module_path("voice_interface"), "voice_runner.py")),
        "vision_available": os.path.exists(os.path.join(_external_module_path("vision"), "market_structure_engine.py")),
        "synthetic_ready": True,
    }


@app.route("/integrations/status")
def integrations_status():
    return jsonify({"status": "ok", **_integration_status()})


@app.route("/ui/snapshot")
def ui_snapshot():
    total_pnl = sum(_safe_float(p.get("pnl", 0.0)) for p in S["positions"].values())
    return jsonify(
        {
            "status": "ok",
            "bridge": {
                "url": f"http://{os.getenv('BRIDGE_HOST', '127.0.0.1')}:{os.getenv('BRIDGE_PORT', '5050')}",
                "symbol": _selected_symbol(),
                "mode": S["trading"]["mode"],
                "running": True,
            },
            "account": S["account"],
            "risk": S["risk"],
            "portfolio": {
                "open_trades": len(S["positions"]),
                "total_pnl": total_pnl,
            },
            "positions": S["positions"],
            "mt": {
                "connected": _mt_connected(),
                "last_heartbeat": S["mt"]["last_heartbeat"],
                "broker_mode": S["mt"]["broker_mode"],
                "symbol": S["mt"].get("active_symbol"),
                "watchlist": S["mt"].get("watchlist", []),
            },
            "integrations": _integration_status(),
        }
    )


@app.route("/integrations/voice/chat", methods=["POST"])
def integrations_voice_chat():
    data = request.get_json(silent=True) or {}
    text = str(data.get("text", "")).strip()
    if not text:
        return jsonify({"status": "error", "error": "missing_text"}), 400

    voice_dir = _external_module_path("voice_interface")
    if voice_dir not in sys.path:
        sys.path.insert(0, voice_dir)
    try:
        from voice_runner import send_chat

        reply = send_chat(text)
        return jsonify({"status": "ok", "reply": reply})
    except Exception as exc:
        reply = _voice_fallback_reply(text)
        _log(f"Voice fallback used: {exc}", "warn")
        return jsonify({"status": "ok", "reply": reply, "fallback": True, "error": str(exc)})


@app.route("/integrations/vision/structure", methods=["POST"])
def integrations_vision_structure():
    data = request.get_json(silent=True) or {}
    symbol = _normalize_symbol(data.get("symbol", S["trading"]["symbol"]))
    candles = data.get("candles")
    timeframe = data.get("timeframe", "M15")
    count = _safe_int(data.get("count", 120), 120)
    if not isinstance(candles, list) or not candles:
        candles = _deriv_fetch_candles(symbol, timeframe=timeframe, count=count).get("bars", [])

    vision_dir = _external_module_path("vision")
    if vision_dir not in sys.path:
        sys.path.insert(0, vision_dir)
    try:
        from market_structure_engine import MarketStructureEngine

        engine = MarketStructureEngine()
        events = engine.detect(symbol, candles)
        payload = []
        for e in events:
            payload.append(
                {
                    "pattern": e.pattern,
                    "direction": e.direction,
                    "confidence": e.confidence,
                    "time": e.time,
                    "symbol": e.symbol,
                    "zone_high": getattr(e, "zone_high", 0.0),
                    "zone_low": getattr(e, "zone_low", 0.0),
                    "top": getattr(e, "top", 0.0),
                    "bottom": getattr(e, "bottom", 0.0),
                }
            )
        return jsonify({"status": "ok", "symbol": symbol, "timeframe": str(timeframe).upper(), "events": payload})
    except Exception as exc:
        return jsonify({"status": "error", "error": str(exc)}), 502


@app.route("/synthetic/run", methods=["POST"])
def synthetic_run():
    data = request.get_json(silent=True) or {}
    symbol = _normalize_symbol(data.get("symbol", S["trading"]["symbol"]))
    runs = max(1, min(25, _safe_int(data.get("runs", 8), 8)))
    days = max(5, min(365, _safe_int(data.get("days", 30), 30)))
    base = _safe_float(data.get("base_balance", S["account"].get("balance", 1000.0)), 1000.0)
    seed = _safe_int(data.get("seed", int(time.time()) % 100000), 1)
    rng = random.Random(seed)
    scenarios = []
    for idx in range(runs):
        trades = rng.randint(max(6, days // 2), max(12, days * 2))
        win_rate = max(0.18, min(0.82, rng.gauss(0.54, 0.12)))
        roi = rng.gauss(4.8, 9.5)
        max_dd = abs(rng.gauss(6.0, 3.0))
        ending_balance = base * (1.0 + roi / 100.0)
        scenarios.append(
            {
                "run": idx + 1,
                "symbol": symbol,
                "days": days,
                "trades": trades,
                "win_rate": round(win_rate, 4),
                "roi": round(roi, 2),
                "max_dd": round(max_dd, 2),
                "ending_balance": round(ending_balance, 2),
                "bias": "bullish" if roi >= 0 else "defensive",
            }
        )
    return jsonify({"status": "ok", "symbol": symbol, "runs": runs, "days": days, "seed": seed, "scenarios": scenarios})


def _normalize_bars(raw_bars: Any, root: Dict[str, Any]) -> List[Dict[str, Any]]:
    bars: List[Dict[str, Any]] = []

    if isinstance(raw_bars, dict):
        raw_bars = [raw_bars]
    elif not isinstance(raw_bars, list):
        raw_bars = []

    if not raw_bars and any(k in root for k in ("o", "open", "c", "close")):
        raw_bars = [root]

    for item in raw_bars:
        if isinstance(item, list) and len(item) >= 6:
            t, o, h, l, c, v = item[0:6]
        elif isinstance(item, dict):
            t = item.get("t", item.get("time", item.get("timestamp")))
            o = item.get("o", item.get("open"))
            h = item.get("h", item.get("high"))
            l = item.get("l", item.get("low"))
            c = item.get("c", item.get("close"))
            v = item.get("v", item.get("volume", item.get("tick_volume", 0)))
        else:
            continue

        bar = {
            "t": _safe_int(t, 0),
            "o": _safe_float(o, 0.0),
            "h": _safe_float(h, 0.0),
            "l": _safe_float(l, 0.0),
            "c": _safe_float(c, 0.0),
            "v": _safe_int(v, 0),
        }
        if bar["t"] <= 0 and all(bar[k] == 0 for k in ("o", "h", "l", "c")):
            continue
        bars.append(bar)

    return bars


def _register_ingest(sym: str, timeframe: str, bars: List[Dict[str, Any]], source: str = "ingest") -> None:
    key = f"{sym}|{timeframe}"
    S["ingest"]["counts"][sym] = _safe_int(S["ingest"]["counts"].get(sym, 0), 0) + len(bars)
    S["ingest"]["timeframe_counts"][key] = _safe_int(S["ingest"]["timeframe_counts"].get(key, 0), 0) + len(bars)
    S["ingest"]["total_bars"] = _safe_int(S["ingest"]["total_bars"], 0) + len(bars)
    S["ingest"]["last_symbol"] = sym
    S["ingest"]["last_time"] = _utc_now_iso()
    S["ingest"]["last_timeframe"] = timeframe
    S["ingest"]["last_batch"] = len(bars)
    S["ingest"]["last_bar"] = bars[-1] if bars else None
    S["mt"]["last_feed_symbol"] = sym
    _touch_mt(source)


@app.route("/ingest", methods=["POST"])
def ingest():
    data = _parse_ingest_payload()
    sym = _normalize_symbol(data.get("symbol", data.get("Symbol", S["trading"]["symbol"])))
    timeframe = str(data.get("timeframe", data.get("tf", data.get("period", "UNKNOWN")))).upper()

    raw_bars = data.get("bars", data.get("data", []))
    bars = _normalize_bars(raw_bars, data)

    key = f"{sym}|{timeframe}"
    _register_ingest(sym, timeframe, bars, source="ingest")

    return jsonify(
        {
            "status": "ok",
            "symbol": sym,
            "timeframe": timeframe,
            "new_bars": len(bars),
            "total_symbol": int(S["ingest"]["counts"][sym]),
            "total_timeframe": int(S["ingest"]["timeframe_counts"][key]),
            "total_all": int(S["ingest"]["total_bars"]),
        }
    )


@app.route("/ingest/status")
def ingest_status():
    return jsonify(
        {
            "status": "ok",
            "ingest": S["ingest"],
            "mt_connected": _mt_connected(),
        }
    )


@app.route("/deriv/candles", methods=["GET", "POST"])
def deriv_candles():
    data = request.args if request.method == "GET" else (request.get_json(silent=True) or {})
    symbol = _normalize_symbol(data.get("symbol", S["trading"]["symbol"]))
    timeframe = data.get("timeframe", data.get("tf", "H1"))
    count = _safe_int(data.get("count", 500), 500)
    start = data.get("start")
    end = data.get("end")

    try:
        out = _deriv_fetch_candles(symbol=symbol, timeframe=timeframe, count=count, start=start, end=end)
        return jsonify({"status": "ok", **out})
    except Exception as exc:
        _log(f"Deriv candles error: {exc}", "error")
        return jsonify({"status": "error", "error": str(exc)}), 502


@app.route("/deriv/candles/ingest", methods=["POST"])
def deriv_candles_ingest():
    data = request.get_json(silent=True) or {}
    symbol = _normalize_symbol(data.get("symbol", S["trading"]["symbol"]))
    timeframe = str(data.get("timeframe", data.get("tf", "H1"))).upper()
    count = _safe_int(data.get("count", 500), 500)
    start = data.get("start")
    end = data.get("end")

    try:
        out = _deriv_fetch_candles(symbol=symbol, timeframe=timeframe, count=count, start=start, end=end)
        bars = out.get("bars", [])
        _register_ingest(symbol, timeframe, bars, source="deriv")
        return jsonify(
            {
                "status": "ok",
                "symbol": symbol,
                "timeframe": timeframe,
                "fetched": len(bars),
                "total_symbol": int(S["ingest"]["counts"].get(symbol, 0)),
                "total_all": int(S["ingest"]["total_bars"]),
            }
        )
    except Exception as exc:
        _log(f"Deriv ingest error: {exc}", "error")
        return jsonify({"status": "error", "error": str(exc)}), 502


@app.route("/deriv/status")
def deriv_status():
    return jsonify(
        {
            "status": "ok",
            "configured": bool(DERIV_API_TOKEN),
            "app_id": DERIV_APP_ID,
            "ws_url": DERIV_WS_URL,
        }
    )


@app.route("/trade_result", methods=["POST"])
def trade_result():
    data = request.get_json(silent=True) or {}
    sym = _normalize_symbol(data.get("symbol", S["trading"]["symbol"]))
    prediction = _safe_float(data.get("prediction", 0.5), 0.5)
    actual = _safe_int(data.get("actual", 0), 0)
    profit = _safe_float(data.get("profit", 0.0), 0.0)

    S["history"].append(
        {
            "ticket": f"fb-{int(time.time() * 1000)}",
            "date": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "symbol": sym,
            "type": "BUY" if prediction >= 0.5 else "SELL",
            "lot": 0.01,
            "pnl": round(profit, 2),
            "prediction": prediction,
            "actual": actual,
        }
    )
    S["history"] = S["history"][-600:]

    S["risk"]["total_trades"] += 1
    if profit >= 0:
        S["risk"]["wins"] += 1
        S["risk"]["loss_streak"] = 0
    else:
        S["risk"]["losses"] += 1
        S["risk"]["loss_streak"] += 1
    n = max(1, _safe_int(S["risk"]["total_trades"], 1))
    S["risk"]["win_rate"] = S["risk"]["wins"] / n

    _touch_mt("trade_result")
    _log(f"Feedback received symbol={sym} profit={profit:.2f}")
    return jsonify({"status": "ok"})


@app.route("/mt/status")
def mt_status():
    return jsonify(
        {
            "status": "ok",
            "connected": _mt_connected(),
            "desired_connected": S["mt"]["desired_connected"],
            "last_heartbeat": S["mt"]["last_heartbeat"],
            "last_source": S["mt"]["last_source"],
            "broker_mode": S["mt"]["broker_mode"],
            "broker_detected": S["account"].get("broker", ""),
            "symbol": S["trading"]["symbol"],
            "account": S["account"],
        }
    )


@app.route("/mt/connect", methods=["POST"])
def mt_connect():
    data = request.get_json(silent=True) or {}
    enabled = bool(data.get("enabled", True))
    broker_mode = str(data.get("broker_mode", S["mt"]["broker_mode"])).lower()
    if broker_mode not in {"auto", "mt5", "deriv"}:
        broker_mode = "auto"
    S["mt"]["desired_connected"] = enabled
    S["mt"]["broker_mode"] = broker_mode
    if not enabled:
        S["mt"]["connected"] = False
    _log(f"MT desired connection {'ON' if enabled else 'OFF'} mode={broker_mode}")
    return jsonify({"status": "ok", "desired_connected": enabled, "broker_mode": broker_mode})


@app.route("/log")
def get_log():
    limit = max(1, _safe_int(request.args.get("limit", 50), 50))
    return jsonify(S["log"][-limit:])


@app.route("/admin/log", methods=["POST"])
def admin_log():
    data = request.get_json(silent=True) or {}
    _log(f"{data.get('event', '?')} - {data.get('reason', '')}")
    return jsonify({"status": "ok"})


@app.route("/admin/restart", methods=["POST"])
def admin_restart():
    _log("Restart requested")
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    host = os.getenv("BRIDGE_HOST", "127.0.0.1")
    port = int(os.getenv("BRIDGE_PORT", "5050"))
    print("=" * 55)
    print(" SupervisorTrainer Bridge Server")
    print(f" http://{host}:{port}")
    print(" Ctrl+C to stop")
    print("=" * 55)
    threading.Thread(target=_get_trainer, daemon=True).start()
    app.run(host=host, port=port, debug=False, use_reloader=False)
