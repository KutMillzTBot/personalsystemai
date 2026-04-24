#!/usr/bin/env python3
"""retrain_scheduler.py — FIXED: indentation errors corrected throughout."""
import os,time,requests,threading
from datetime import datetime,timedelta

BRIDGE_URL     = os.getenv("BRIDGE_URL","http://127.0.0.1:5050")
SCHEDULE_DAY   = int(os.getenv("RETRAIN_DAY","6"))
SCHEDULE_HOUR  = int(os.getenv("RETRAIN_HOUR","2"))
MIN_WIN_RATE   = float(os.getenv("RETRAIN_WIN_RATE","0.45"))
MIN_NEW_TRADES = int(os.getenv("RETRAIN_TRADES","50"))
CHECK_INTERVAL = 300

last_retrain         = None
trades_since_retrain = 0

def bridge(endpoint,method="GET",data=None):
    try:
        if method=="GET":
            r=requests.get(f"{BRIDGE_URL}{endpoint}",timeout=5)
        else:
            r=requests.post(f"{BRIDGE_URL}{endpoint}",json=data or {},timeout=5)
        return r.json() if r.ok else None
    except Exception:
        return None

def do_retrain(reason):
    global last_retrain,trades_since_retrain
    print(f"[RETRAIN] Starting — reason: {reason}")
    result=bridge("/retrain","POST",{"reason":reason,"timestamp":str(datetime.utcnow())})
    if result:
        print("[RETRAIN] ✅ Triggered")
        last_retrain=datetime.utcnow()
        trades_since_retrain=0
    else:
        print("[RETRAIN] ❌ Bridge not responding")

def check_win_rate_trigger():
    data=bridge("/risk/summary")
    if not data: return False
    wr=data.get("win_rate",1.0); trades=data.get("total_trades",0)
    if wr<MIN_WIN_RATE and trades>=20:
        print(f"[RETRAIN] Low WR {wr*100:.1f}% — trigger"); return True
    return False

def check_trade_count_trigger():
    global trades_since_retrain
    data=bridge("/risk/summary")
    if not data: return False
    total=data.get("total_trades",0)
    prev=getattr(check_trade_count_trigger,"_prev",0)
    check_trade_count_trigger._prev=total
    trades_since_retrain+=total-prev
    if trades_since_retrain>=MIN_NEW_TRADES:
        print(f"[RETRAIN] {MIN_NEW_TRADES} new trades — trigger"); return True
    return False

def is_scheduled_time():
    now=datetime.utcnow()
    if now.weekday()!=SCHEDULE_DAY: return False
    if now.hour!=SCHEDULE_HOUR: return False
    if last_retrain and (now-last_retrain)<timedelta(hours=20): return False
    return True

def scheduler_loop():
    print(f"[RETRAIN] Scheduler started  day={SCHEDULE_DAY} hour={SCHEDULE_HOUR} UTC")
    while True:
        try:
            if is_scheduled_time():           do_retrain("scheduled_weekly")
            elif check_win_rate_trigger():    do_retrain("low_win_rate")
            elif check_trade_count_trigger(): do_retrain("trade_count")
        except Exception as e:
            print(f"[RETRAIN] Error: {e}")
        time.sleep(CHECK_INTERVAL)

if __name__=="__main__":
    scheduler_loop()
