import json
import os
import sys
import time
import urllib.request


WAKE_PHRASE = "hey rich"


def send_chat(text: str) -> str:
    base_url = os.getenv("RICH_API_URL", "http://127.0.0.1:5001").rstrip("/")
    url = f"{base_url}/chat"
    payload = json.dumps({"text": text}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    user = os.getenv("KM_USER", "") or os.getenv("KM_ACCESS_KEY", "")
    passwd = os.getenv("KM_PASS", "")
    if user:
        headers["X-KM-USER"] = user
    if passwd:
        headers["X-KM-PASS"] = passwd
    if user and passwd:
        headers["X-KM-KEY"] = f"{user}:{passwd}"
    req = urllib.request.Request(url, data=payload, headers=headers)
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.read().decode("utf-8")


def run_text_fallback():
    print("Voice libs not installed. Text fallback active. Type 'hey rich ...'")
    while True:
        line = input("> ").strip()
        if not line:
            continue
        if line.lower().startswith(WAKE_PHRASE):
            reply = send_chat(line)
            print(reply)


def run_voice():
    import speech_recognition as sr

    r = sr.Recognizer()
    mic = sr.Microphone()
    print("Voice listener active. Say 'Hey Twin RICH ...'")

    while True:
        with mic as source:
            r.adjust_for_ambient_noise(source, duration=0.4)
            audio = r.listen(source, phrase_time_limit=6)
        try:
            text = r.recognize_google(audio)
        except Exception:
            continue
        if text.lower().startswith(WAKE_PHRASE):
            reply = send_chat(text)
            print(reply)


def main():
    pid_path = os.path.join(os.path.dirname(__file__), "..", ".voice.pid")
    try:
        with open(pid_path, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except Exception:
        pass

    try:
        run_voice()
    except Exception:
        run_text_fallback()
    finally:
        try:
            os.remove(pid_path)
        except Exception:
            pass


if __name__ == "__main__":
    main()
