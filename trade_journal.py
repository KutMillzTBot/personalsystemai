#!/usr/bin/env python3
"""trade_journal.py — FIXED: all missing closing brackets restored."""
import os, csv, time, requests
from datetime import datetime

BRIDGE_URL = os.getenv("BRIDGE_URL", "http://127.0.0.1:5050")
CSV_FILE   = "trades_journal.csv"
SHEETS_URL = os.getenv("GOOGLE_SHEETS_WEBHOOK", "")

HEADERS = [
    "Date","Time","Symbol","Direction","Lot","Entry","SL","TP",
    "Close_Price","PnL_USD","PnL_Pips","RR_Actual","Win",
    "Signal_Score","Models_Agreed","ICT_Setup","Session",
    "Duration_Min","Notes",
]

def init_csv():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE,"w",newline="") as f:
            csv.writer(f).writerow(HEADERS)

def _session():
    h = datetime.utcnow().hour
    if  0<=h< 8: return "Asian"
    if  8<=h<12: return "London"
    if 12<=h<17: return "New York"
    return "Off-Hours"

def log_trade(trade:dict):
    init_csv()
    entry  = trade.get("entry",0);   close  = trade.get("close_price",trade.get("close",0))
    sl     = trade.get("sl",0);      tp     = trade.get("tp",0)
    pnl    = trade.get("pnl",0);     direct = trade.get("type","BUY")
    lot    = trade.get("lot",0);     sym    = trade.get("symbol","?")
    dur    = trade.get("duration_min",0); score  = trade.get("signal_score",0)
    models = trade.get("models_agreed",0); ict = trade.get("ict_setup","OB+FVG")
    session= trade.get("session",_session())
    sl_dist= abs(entry-sl) if sl else 1e-8
    rr_act = abs(close-entry)/sl_dist
    win    = "YES" if pnl>0 else "NO"
    pips   = abs(close-entry)*(100 if "JPY" in sym else 10000)
    now    = datetime.utcnow()
    row = [
        now.strftime("%Y-%m-%d"),now.strftime("%H:%M"),
        sym,direct,lot,round(entry,5),round(sl,5),round(tp,5),
        round(close,5),round(pnl,2),round(pips,1),
        round(rr_act,2),win,round(score,3),
        models,ict,session,int(dur),"",
    ]
    with open(CSV_FILE,"a",newline="") as f:
        csv.writer(f).writerow(row)
    print(f"[JOURNAL] {sym} {direct}  PnL=${pnl:.2f} ({win})")
    if SHEETS_URL:
        try: requests.post(SHEETS_URL,json=dict(zip(HEADERS,row)),timeout=5)
        except Exception: pass

def journal_summary()->dict:
    init_csv()
    rows,wins,total_pnl=[],0,0.0
    try:
        with open(CSV_FILE) as f:
            for row in csv.DictReader(f):
                rows.append(row)
                pnl=float(row.get("PnL_USD",0) or 0)
                total_pnl+=pnl
                if row.get("Win")=="YES": wins+=1
    except Exception: pass
    n=len(rows)
    return {
        "total_trades":n,"wins":wins,"losses":n-wins,
        "win_rate":round(wins/n,4) if n else 0.0,
        "total_pnl":round(total_pnl,2),"avg_pnl":round(total_pnl/n,2) if n else 0.0,
    }

_seen_tickets:set=set()

def watch_and_log():
    init_csv()
    print(f"[JOURNAL] Watching → {CSV_FILE}")
    while True:
        try:
            r=requests.get(f"{BRIDGE_URL}/history?limit=20",timeout=5)
            if r.ok:
                for t in r.json():
                    tid=t.get("ticket")
                    if tid and tid not in _seen_tickets:
                        _seen_tickets.add(tid); log_trade(t)
        except Exception: pass
        time.sleep(30)

if __name__=="__main__":
    watch_and_log()
