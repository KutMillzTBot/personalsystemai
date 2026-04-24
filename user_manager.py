#!/usr/bin/env python3
"""user_manager.py — FIXED: PERMISSIONS dict brackets all restored."""
import json,sys,os,hashlib,secrets
from datetime import datetime

USERS_FILE="users.json"

PERMISSIONS={
    "admin":"all",
    "trader":[
        "menu","status","ping","account","balance","equity","margin",
        "daily","weekly","signal","signalsall","confidence","models","ict",
        "trades","history","pnl","closeall","closesymbol","closeticket",
        "starttrading","stoptrading","pause","resume",
        "modeauto","modesemi","modeoff","risk","setrisk",
        "setdailylimit","setdrawdown","lotcalc","drawdown",
        "modelstatus","retrain","modelon","modeloff","accuracy",
        "backtest","backteststatus","lastbacktest",
        "alerts","alertson","alertsoff","subscribe","unsubscribe",
        "symbols","deriv","help","version","changelog",
    ],
    "viewer":[
        "menu","status","account","balance","equity","daily","weekly",
        "signal","signalsall","confidence","models","ict",
        "trades","history","pnl","risk","drawdown","accuracy",
        "lastbacktest","symbols","deriv","help","version","changelog",
        "alerts","subscribe","unsubscribe",
    ],
}

def _load()->dict:
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE) as f: return json.load(f)
        except Exception: pass
    return {}

def _save(u:dict):
    with open(USERS_FILE,"w") as f: json.dump(u,f,indent=2)

def _hash(code:str)->str:
    return hashlib.sha256(code.strip().encode()).hexdigest()

def add_user(chat_id,level,code):
    u=_load(); level=level.lower()
    if level not in PERMISSIONS: print(f"Bad level: {level}"); return
    u[str(chat_id)]={"level":level,"code_hash":_hash(code),"created":str(datetime.utcnow()),"active":True}
    _save(u); print(f"Added {chat_id} as {level.upper()}")

def remove_user(chat_id):
    u=_load()
    if str(chat_id) in u: del u[str(chat_id)]; _save(u); print(f"Removed {chat_id}")
    else: print("Not found")

def list_users():
    u=_load()
    for cid,d in u.items(): print(f"  {'✅' if d.get('active') else '🚫'}  {cid:15s}  {d['level'].upper()}")

def verify_user(chat_id:int,code:str):
    u=_load(); d=u.get(str(chat_id))
    if not d or not d.get("active"): return None
    if d["code_hash"]==_hash(code):
        d["last_seen"]=str(datetime.utcnow()); _save(u); return d["level"]
    return None

def can_use_command(chat_id:int,command:str)->bool:
    u=_load(); d=u.get(str(chat_id))
    if not d or not d.get("active"): return False
    allowed=PERMISSIONS.get(d.get("level","viewer"),[])
    return True if allowed=="all" else command in allowed

def generate_code(n:int=10)->str:
    abc="ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(abc) for _ in range(n))

def reset_codes():
    u=_load()
    for cid,d in u.items():
        c=generate_code(); d["code_hash"]=_hash(c); print(f"  {cid}  {d['level'].upper()}  {c}")
    _save(u)

if __name__=="__main__":
    if len(sys.argv)<2: sys.exit(0)
    cmd=sys.argv[1].lower()
    if cmd=="add_user"    and len(sys.argv)>=5: add_user(sys.argv[2],sys.argv[3],sys.argv[4])
    elif cmd=="remove_user" and len(sys.argv)>=3: remove_user(sys.argv[2])
    elif cmd=="list_users":  list_users()
    elif cmd=="reset_codes": reset_codes()
    elif cmd=="gen_code":    print(generate_code())
