#!/usr/bin/env python3
import json
import os
import threading
import time
from datetime import date

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
ACCESS_CODE = os.getenv("TELEGRAM_ACCESS_CODE", "TRADE2025").strip()
BRIDGE_URL = os.getenv("BRIDGE_URL", "http://127.0.0.1:5050").rstrip("/")
STATE_FILE = "telegram_state.json"
BASE = f"https://api.telegram.org/bot{TOKEN}"

MAIN_KEYBOARD = {
    "keyboard": [
        ["/status", "/signal", "/account"],
        ["/trades", "/closeall", "/voice"],
        ["/models", "/risk", "/backteststatus"],
        ["/menu", "/help", "/snapshot"],
    ],
    "resize_keyboard": True,
    "is_persistent": True,
}


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            pass
    return {"authorized": []}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)


STATE = load_state()


def send(chat_id, text, reply_markup=None):
    try:
        requests.post(
            f"{BASE}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "reply_markup": MAIN_KEYBOARD if reply_markup is None else reply_markup,
            },
            timeout=15,
        )
    except Exception as exc:
        print(f"TG send error: {exc}")


def register_bot_commands():
    commands = [
        {"command": "start", "description": "Open bot welcome panel"},
        {"command": "activate", "description": "Unlock bot with your access code"},
        {"command": "menu", "description": "Show the main command center"},
        {"command": "status", "description": "Live system and account status"},
        {"command": "signal", "description": "Current trade signal"},
        {"command": "account", "description": "Balance, equity and broker"},
        {"command": "trades", "description": "List open trades"},
        {"command": "history", "description": "Recent trade history"},
        {"command": "closeall", "description": "Close all active trades"},
        {"command": "backteststatus", "description": "Last backtest status"},
        {"command": "models", "description": "Model confidence and weights"},
        {"command": "risk", "description": "Risk control summary"},
        {"command": "voice", "description": "Ask Rich through Telegram"},
        {"command": "snapshot", "description": "Compact mobile dashboard card"},
        {"command": "help", "description": "Show help"},
        {"command": "ping", "description": "Check bridge latency"},
    ]
    try:
        requests.post(f"{BASE}/setMyCommands", json={"commands": commands}, timeout=15)
    except Exception as exc:
        print(f"TG command registration error: {exc}")


def bridge(endpoint, method="GET", data=None):
    try:
        url = f"{BRIDGE_URL}{endpoint}"
        if method == "GET":
            res = requests.get(url, timeout=8)
        else:
            res = requests.post(url, json=data or {}, timeout=8)
        if not res.ok:
            return None
        return res.json()
    except Exception:
        return None


def is_auth(chat_id):
    return chat_id in STATE["authorized"]


def pct(v):
    return f"{float(v or 0) * 100:.1f}%"


def usd(v):
    return f"${float(v or 0):,.2f}"


def sgn(v):
    return "+" if float(v or 0) >= 0 else ""


def require_auth(fn):
    def wrapper(chat_id, args, msg):
        if not is_auth(chat_id):
            send(chat_id, "Access denied. Use /activate YOURCODE")
            return
        return fn(chat_id, args, msg)
    return wrapper


def cmd_start(chat_id, args, msg):
    name = msg.get("from", {}).get("first_name", "Trader")
    if is_auth(chat_id):
        send(
            chat_id,
            "🛰️ <b>Supervisor Control Link Active</b>\n"
            f"Welcome back <b>{name}</b>.\n\n"
            "Use the command keyboard below for quick actions or open /menu for the full control board.",
        )
        return
    send(
        chat_id,
        "🛰️ <b>SupervisorTrainer Telegram Console</b>\n"
        f"Hello <b>{name}</b>.\n\n"
        "This bot can read signals, close trades, run voice prompts, and monitor your bridge.\n"
        "Activate with:\n<code>/activate YOURCODE</code>",
    )


def cmd_activate(chat_id, args, msg):
    code = (args[0].strip() if args else "")
    if code.upper() != ACCESS_CODE.upper():
        send(chat_id, "Wrong activation code.")
        return
    if chat_id not in STATE["authorized"]:
        STATE["authorized"].append(chat_id)
        save_state(STATE)
    send(
        chat_id,
        "✅ <b>Access granted</b>\n"
        "Your command keyboard is now active.\n"
        "Try /status, /signal, /trades, or /voice hey rich give me a market summary",
    )


@require_auth
def cmd_menu(chat_id, args, msg):
    send(
        chat_id,
        "🧭 <b>Supervisor Menu</b>\n\n"
        "<b>Core</b>\n"
        "/status  /signal  /account  /snapshot\n\n"
        "<b>Trades</b>\n"
        "/trades  /history  /closeall  /backteststatus\n\n"
        "<b>AI</b>\n"
        "/models  /risk  /voice\n\n"
        "<b>Support</b>\n"
        "/ping  /help",
    )


@require_auth
def cmd_help(chat_id, args, msg):
    send(
        chat_id,
        "💡 <b>How To Use This Bot</b>\n\n"
        "1. Use /status for your live account state.\n"
        "2. Use /signal for the current system trade idea.\n"
        "3. Use /trades to see open trades.\n"
        "4. Use /closeall to send a real close request through the MT bridge.\n"
        "5. Use /voice hey rich ... to forward a prompt to your Rich service.\n"
        "6. Use /snapshot for a compact mobile dashboard card.",
    )


@require_auth
def cmd_ping(chat_id, args, msg):
    t0 = time.time()
    ok = bridge("/ping")
    if not ok:
        send(chat_id, "Bridge offline.")
        return
    send(chat_id, f"PONG {int((time.time() - t0) * 1000)}ms")


@require_auth
def cmd_status(chat_id, args, msg):
    st = bridge("/status") or {}
    acc = bridge("/account") or {}
    risk = bridge("/risk/summary") or {}
    send(
        chat_id,
        "📡 <b>SYSTEM STATUS</b>\n"
        f"Engine: {'🟢 Running' if st.get('running') else '🔴 Stopped'}\n"
        f"Mode: <b>{str(st.get('mode', '?')).upper()}</b>\n"
        f"Symbol: <b>{st.get('symbol', '?')}</b>\n"
        f"Broker: <b>{acc.get('broker', '?')}</b>\n\n"
        f"Balance: <b>{usd(acc.get('balance', 0))}</b>\n"
        f"Equity: <b>{usd(acc.get('equity', 0))}</b>\n"
        f"Open Positions: <b>{risk.get('open_positions', 0)}</b>\n"
        f"Daily PnL: <b>{sgn(risk.get('daily_pnl', 0))}{usd(risk.get('daily_pnl', 0))}</b>",
    )


@require_auth
def cmd_signal(chat_id, args, msg):
    symbol = args[0].upper() if args else ""
    payload = bridge(f"/signal?symbol={symbol}" if symbol else "/signal") or {}
    if not payload:
        send(chat_id, "No signal available.")
        return
    send(
        chat_id,
        f"🎯 <b>{payload.get('signal', 'HOLD')}</b>  {payload.get('symbol', '?')}\n"
        f"Confidence: <b>{pct(payload.get('score', 0))}</b>\n"
        f"OB50: <code>{float(payload.get('ob50', 0)):.5f}</code>\n"
        f"SL: <code>{float(payload.get('sl', 0)):.5f}</code>\n"
        f"TP: <code>{float(payload.get('tp', 0)):.5f}</code>",
    )


@require_auth
def cmd_account(chat_id, args, msg):
    acc = bridge("/account") or {}
    send(
        chat_id,
        "<b>ACCOUNT</b>\n"
        f"Balance: <b>{usd(acc.get('balance', 0))}</b>\n"
        f"Equity: <b>{usd(acc.get('equity', 0))}</b>\n"
        f"Margin: {usd(acc.get('margin', 0))}\n"
        f"Free Margin: {usd(acc.get('free_margin', 0))}\n"
        f"Broker: {acc.get('broker', '?')}",
    )


@require_auth
def cmd_trades(chat_id, args, msg):
    data = bridge("/positions") or {}
    if not data:
        send(chat_id, "No open positions.")
        return
    lines = [f"<b>OPEN POSITIONS ({len(data)})</b>"]
    for ticket, trade in data.items():
        lines.append(
            f"{trade.get('symbol', '?')} #{ticket} {trade.get('type', '?')} "
            f"{trade.get('lot', 0)}  <b>{sgn(trade.get('pnl', 0))}{usd(trade.get('pnl', 0))}</b>"
        )
    send(chat_id, "\n".join(lines))


@require_auth
def cmd_history(chat_id, args, msg):
    rows = bridge("/history?limit=10") or []
    if not rows:
        send(chat_id, "No trade history yet.")
        return
    lines = ["<b>LAST 10 TRADES</b>"]
    for trade in rows[-10:]:
        lines.append(
            f"{trade.get('date', '?')}  {trade.get('symbol', '?')}  "
            f"{trade.get('type', '?')}  <b>{sgn(trade.get('pnl', 0))}{usd(trade.get('pnl', 0))}</b>"
        )
    send(chat_id, "\n".join(lines))


@require_auth
def cmd_closeall(chat_id, args, msg):
    res = bridge("/trades/close_all", method="POST") or {}
    send(
        chat_id,
        f"🧯 <b>Close-All Sent</b>\n"
        f"Local closed: <b>{res.get('closed', 0)}</b>\n"
        f"MT queued: <b>{'YES' if res.get('queued_mt') else 'NO'}</b>\n"
        f"PnL: <b>{sgn(res.get('total_pnl', 0))}{usd(res.get('total_pnl', 0))}</b>",
    )


@require_auth
def cmd_backteststatus(chat_id, args, msg):
    data = bridge("/backtest/status") or {}
    result = data.get("result") or {}
    send(
        chat_id,
        "🧪 <b>BACKTEST STATUS</b>\n"
        f"Status: {data.get('status', 'idle')}\n"
        f"Progress: {float(data.get('progress', 0)):.0f}%\n"
        f"Symbol: {result.get('symbol', '-')}\n"
        f"Trades: {result.get('trades', '-')}\n"
        f"Win Rate: {pct(result.get('win_rate', 0))}",
    )


@require_auth
def cmd_models(chat_id, args, msg):
    data = bridge("/models/status") or {}
    if not data:
        send(chat_id, "No model data.")
        return
    lines = ["<b>MODELS</b>"]
    for name, info in sorted(data.items()):
        lines.append(
            f"{name}  sig={float(info.get('signal', 0.5)):.2f}  "
            f"acc={pct(info.get('accuracy', 0.5))}  w={float(info.get('weight', 1.0)):.2f}"
        )
    send(chat_id, "\n".join(lines))


@require_auth
def cmd_risk(chat_id, args, msg):
    risk = bridge("/risk/summary") or {}
    send(
        chat_id,
        "<b>RISK</b>\n"
        f"Risk/Trade: {risk.get('risk_pct', 1.0)}%\n"
        f"Daily Limit: {risk.get('daily_limit_pct', 5.0)}%\n"
        f"Max DD: {risk.get('max_drawdown_pct', 10.0)}%\n"
        f"Loss Streak: {risk.get('loss_streak', 0)}\n"
        f"Date: {date.today()}",
    )


@require_auth
def cmd_voice(chat_id, args, msg):
    text = " ".join(args).strip()
    if not text:
        send(chat_id, "Usage: /voice hey rich give me a market summary")
        return
    res = bridge("/integrations/voice/chat", method="POST", data={"text": text}) or {}
    if res.get("reply"):
        send(chat_id, f"<b>RICH</b>\n{res['reply']}")
        return
    send(chat_id, f"Voice upstream unavailable.\n{res.get('error', 'No reply')}")


@require_auth
def cmd_snapshot(chat_id, args, msg):
    data = bridge("/ui/snapshot") or {}
    if not data:
        send(chat_id, "Snapshot unavailable.")
        return
    account = data.get("account", {})
    bridge_data = data.get("bridge", {})
    mt = data.get("mt", {})
    portfolio = data.get("portfolio", {})
    send(
        chat_id,
        "📱 <b>MOBILE SNAPSHOT</b>\n"
        f"Bridge: <b>{bridge_data.get('url', BRIDGE_URL)}</b>\n"
        f"Symbol: <b>{bridge_data.get('symbol', '?')}</b>\n"
        f"Mode: <b>{str(bridge_data.get('mode', '?')).upper()}</b>\n"
        f"MT Link: <b>{'Attached' if mt.get('connected') else 'Waiting'}</b>\n"
        f"Balance: <b>{usd(account.get('balance', 0))}</b>\n"
        f"Equity: <b>{usd(account.get('equity', 0))}</b>\n"
        f"Open Trades: <b>{portfolio.get('open_trades', 0)}</b>\n"
        f"Float: <b>{sgn(portfolio.get('total_pnl', 0))}{usd(portfolio.get('total_pnl', 0))}</b>",
    )


COMMANDS = {
    "start": cmd_start,
    "activate": cmd_activate,
    "menu": cmd_menu,
    "ping": cmd_ping,
    "status": cmd_status,
    "signal": cmd_signal,
    "account": cmd_account,
    "trades": cmd_trades,
    "history": cmd_history,
    "closeall": cmd_closeall,
    "backteststatus": cmd_backteststatus,
    "models": cmd_models,
    "risk": cmd_risk,
    "voice": cmd_voice,
    "snapshot": cmd_snapshot,
    "help": cmd_help,
}


def handle_update(update):
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return
    chat_id = msg["chat"]["id"]
    text = (msg.get("text") or "").strip()
    aliases = {
        "status": "/status",
        "signal": "/signal",
        "account": "/account",
        "trades": "/trades",
        "close all": "/closeall",
        "backtest status": "/backteststatus",
        "models": "/models",
        "risk": "/risk",
        "menu": "/menu",
    }
    if not text.startswith("/"):
        mapped = aliases.get(text.lower())
        if not mapped:
            return
        text = mapped

    parts = text[1:].split(None, 1)
    cmd = parts[0].split("@")[0].lower()
    args = parts[1].split() if len(parts) > 1 else []
    handler = COMMANDS.get(cmd)
    if not handler:
        if is_auth(chat_id):
            send(chat_id, f"Unknown command: /{cmd}")
        return
    try:
        handler(chat_id, args, msg)
    except Exception as exc:
        send(chat_id, f"Command error: {exc}")


def run_polling():
    if not TOKEN:
        print("Set TELEGRAM_TOKEN in .env")
        return
    register_bot_commands()
    print(f"SupervisorTrainer Bot  ({len(COMMANDS)} commands)\n   Bridge : {BRIDGE_URL}")
    offset = 0
    while True:
        try:
            res = requests.get(
                f"{BASE}/getUpdates",
                params={"offset": offset, "timeout": 30},
                timeout=35,
            )
            if res.ok:
                for update in res.json().get("result", []):
                    offset = update["update_id"] + 1
                    threading.Thread(target=handle_update, args=(update,), daemon=True).start()
        except Exception as exc:
            print(f"TG error: {exc}")
            time.sleep(5)


if __name__ == "__main__":
    run_polling()
