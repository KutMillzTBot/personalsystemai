#!/usr/bin/env python3
"""
gpt_explainer.py — Trade Signal Explainer
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Supports TWO backends — pick one in .env:

  MODE=ollama   → FREE, runs locally, no internet needed
                  Uses Ollama: https://ollama.com
                  Models: llama3, mistral, gemma2, phi3, deepseek

  MODE=openai   → Paid, highest quality
                  Requires OPENAI_API_KEY in .env

OLLAMA QUICK SETUP:
  1. Download: https://ollama.com/download
  2. Run:  ollama pull llama3
  3. Set:  MODE=ollama in .env
  4. Done! Fully offline, totally free.
"""

import os, json, requests
from datetime import datetime

# ── Config ────────────────────────────────────────────────────
MODE          = os.getenv("GPT_MODE", "ollama").lower()       # "ollama" or "openai"
OLLAMA_URL    = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL  = os.getenv("OLLAMA_MODEL", "llama3")           # or mistral, gemma2, phi3
OPENAI_KEY    = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL  = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
BRIDGE_URL    = os.getenv("BRIDGE_URL", "http://127.0.0.1:5050")

SYSTEM_PROMPT = """You are a senior ICT trading analyst assistant.
Given a JSON trade signal from an AI ensemble, write a concise 3-sentence explanation of WHY this signal was generated.
Always mention:
1. The key technical reason (OB, FVG, BOS, liquidity sweep, displacement, etc.)
2. Which AI models agreed and why that creates confluence
3. The risk context (RR ratio, session, SL distance)
Be direct. Sound like a professional prop trader, not a textbook.
Keep it under 80 words."""


# ══════════════════════════════════════════════════════════════
#  OLLAMA BACKEND (FREE / LOCAL)
# ══════════════════════════════════════════════════════════════
def explain_with_ollama(signal_data: dict) -> str:
    """Call local Ollama server — zero cost, full privacy."""
    user_msg = _build_prompt(signal_data)
    payload  = {
        "model":  OLLAMA_MODEL,
        "prompt": f"{SYSTEM_PROMPT}\n\nSignal Data:\n{user_msg}",
        "stream": False,
        "options": {
            "temperature": 0.4,
            "num_predict": 200
        }
    }
    try:
        r = requests.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=60)
        if r.ok:
            return r.json().get("response", "No response from Ollama.").strip()
        return f"Ollama error {r.status_code}. Is Ollama running? Run: ollama serve"
    except requests.exceptions.ConnectionError:
        return ("❌ Ollama not running. Start it:\n"
                "  Windows: Open Ollama app\n"
                "  Mac/Linux: ollama serve\n"
                "  Then: ollama pull llama3")
    except Exception as e:
        return f"Ollama error: {e}"


def list_ollama_models() -> list:
    """List all locally available Ollama models."""
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        if r.ok:
            return [m["name"] for m in r.json().get("models", [])]
        return []
    except Exception:
        return []


def check_ollama_running() -> bool:
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        return r.ok
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════
#  OPENAI BACKEND (PAID / CLOUD)
# ══════════════════════════════════════════════════════════════
def explain_with_openai(signal_data: dict) -> str:
    """Call OpenAI API — best quality, requires API key + internet."""
    if not OPENAI_KEY:
        return "⚠️ Set OPENAI_API_KEY in .env to use OpenAI backend."
    user_msg = _build_prompt(signal_data)
    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_KEY}"},
            json={
                "model": OPENAI_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": user_msg}
                ],
                "max_tokens":  200,
                "temperature": 0.4
            }, timeout=20
        )
        if r.ok:
            return r.json()["choices"][0]["message"]["content"].strip()
        return f"OpenAI error {r.status_code}: {r.text[:120]}"
    except Exception as e:
        return f"OpenAI error: {e}"


# ══════════════════════════════════════════════════════════════
#  UNIFIED INTERFACE
# ══════════════════════════════════════════════════════════════
def explain_signal(signal_data: dict) -> str:
    """
    Explain a trade signal using whichever backend is configured.
    MODE=ollama → free local LLM
    MODE=openai → paid GPT-4
    """
    if MODE == "openai":
        return explain_with_openai(signal_data)
    else:
        return explain_with_ollama(signal_data)


def explain_latest(symbol: str = None) -> dict:
    """Fetch latest signal from bridge + explain it."""
    url = f"{BRIDGE_URL}/signal"
    if symbol:
        url += f"?symbol={symbol.upper()}"
    try:
        data = requests.get(url, timeout=5).json()
    except Exception:
        data = {}

    if not data:
        return {
            "signal":      "N/A",
            "explanation": "Bridge not running. Start mq5_bridge_server.py first."
        }

    explanation = explain_signal(data)
    return {**data, "explanation": explanation}


# ══════════════════════════════════════════════════════════════
#  HELPER: Build prompt string from signal dict
# ══════════════════════════════════════════════════════════════
def _build_prompt(d: dict) -> str:
    sig    = d.get("signal", "HOLD")
    sym    = d.get("symbol", "UNKNOWN")
    score  = d.get("score",  0.5)
    ob50   = d.get("ob50",   0)
    sl     = d.get("sl",     0)
    tp     = d.get("tp",     0)
    ict    = d.get("ict",    {})
    models = d.get("model_contributions", {})
    top3   = sorted(models.items(), key=lambda x: x[1], reverse=True)[:3]
    rr     = abs(tp - ob50) / max(abs(ob50 - sl), 1e-8)

    return json.dumps({
        "symbol":       sym,
        "signal":       sig,
        "confidence":   f"{score*100:.1f}%",
        "entry_ob50":   ob50,
        "stop_loss":    sl,
        "take_profit":  tp,
        "rr_ratio":     f"1:{rr:.1f}",
        "bos":          ict.get("bos", "None"),
        "fvg_range":    f"{ict.get('fvg_top',0):.5f} – {ict.get('fvg_bottom',0):.5f}",
        "top_models":   {m: f"{s*100:.0f}%" for m, s in top3},
        "session":      _current_session()
    }, indent=2)


def _current_session() -> str:
    h = datetime.utcnow().hour
    if  0 <= h <  8: return "Asian Session"
    if  8 <= h < 12: return "London Open"
    if 12 <= h < 17: return "New York Session"
    return "Off-Hours"


# ══════════════════════════════════════════════════════════════
#  OLLAMA SETUP WIZARD (run standalone)
# ══════════════════════════════════════════════════════════════
def setup_wizard():
    print("\n" + "="*60)
    print("  🦙 OLLAMA SETUP WIZARD — SupervisorTrainer")
    print("="*60)

    running = check_ollama_running()
    if not running:
        print("\n❌ Ollama is NOT running.")
        print("\nSTEP 1: Download Ollama")
        print("  👉 https://ollama.com/download")
        print("  Windows: Run the .exe installer")
        print("  Mac:     Run the .dmg installer")
        print("  Linux:   curl -fsSL https://ollama.com/install.sh | sh")
        print("\nSTEP 2: Start Ollama")
        print("  Windows: Launch Ollama from Start Menu")
        print("  Mac:     Launch Ollama from Applications")
        print("  Linux:   ollama serve")
        print("\nSTEP 3: Pull a model (pick one):")
        print("  ollama pull llama3        ← Recommended (4.7GB, very smart)")
        print("  ollama pull mistral       ← Great for trading analysis (4.1GB)")
        print("  ollama pull gemma2        ← Google model, fast (5.4GB)")
        print("  ollama pull phi3          ← Tiny but capable (2.3GB)")
        print("  ollama pull deepseek-r1   ← Best reasoning (4.7GB)")
        print("\nSTEP 4: Set in .env:")
        print("  GPT_MODE=ollama")
        print(f"  OLLAMA_MODEL=llama3")
        print("\nThen run: python gpt_explainer.py")
    else:
        print("\n✅ Ollama is RUNNING!")
        models = list_ollama_models()
        if models:
            print(f"\n📦 Available models ({len(models)}):")
            for m in models:
                tag = " ← ACTIVE" if m.startswith(OLLAMA_MODEL) else ""
                print(f"  • {m}{tag}")
        else:
            print("\n⚠️  No models downloaded yet. Run:")
            print("  ollama pull llama3")

        print(f"\n⚙️  Current config:")
        print(f"  MODE  : {MODE.upper()}")
        print(f"  MODEL : {OLLAMA_MODEL}")
        print(f"  URL   : {OLLAMA_URL}")
        print("\n✅ Ready! Explaining latest signal...")
        result = explain_latest()
        sig = result.get("signal", "N/A")
        sym = result.get("symbol", "?")
        exp = result.get("explanation", "Bridge offline.")
        print(f"\n{'─'*60}")
        print(f"  Signal: {sig} — {sym}")
        print(f"{'─'*60}")
        print(f"  {exp}")

    print("\n" + "="*60 + "\n")


# ══════════════════════════════════════════════════════════════
#  SUPPORTED OLLAMA MODELS REFERENCE
# ══════════════════════════════════════════════════════════════
RECOMMENDED_MODELS = {
    "llama3":       {"size": "4.7GB", "quality": "⭐⭐⭐⭐⭐", "speed": "Fast",   "note": "Best overall"},
    "mistral":      {"size": "4.1GB", "quality": "⭐⭐⭐⭐",  "speed": "Fast",   "note": "Great for analysis"},
    "gemma2":       {"size": "5.4GB", "quality": "⭐⭐⭐⭐",  "speed": "Medium", "note": "Google model"},
    "phi3":         {"size": "2.3GB", "quality": "⭐⭐⭐",   "speed": "Very Fast","note": "Tiny but solid"},
    "deepseek-r1":  {"size": "4.7GB", "quality": "⭐⭐⭐⭐⭐", "speed": "Medium", "note": "Best reasoning"},
    "llama3.1":     {"size": "4.7GB", "quality": "⭐⭐⭐⭐⭐", "speed": "Fast",   "note": "Latest Llama"},
    "codellama":    {"size": "3.8GB", "quality": "⭐⭐⭐",   "speed": "Fast",   "note": "Code-focused"},
}


if __name__ == "__main__":
    setup_wizard()
