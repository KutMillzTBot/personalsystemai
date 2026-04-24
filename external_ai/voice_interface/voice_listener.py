"""
Wake-word listener entrypoint.
Uses voice_runner implementation for microphone + fallback console mode.
"""

try:
    from voice_interface.voice_runner import main
except ModuleNotFoundError:
    # Allow direct script execution without package context.
    from voice_runner import main


class VoiceListener:
    def __init__(self, wake_phrase: str = "hey rich"):
        self.wake_phrase = wake_phrase.lower()

    def detect(self, transcript: str) -> bool:
        return transcript.lower().startswith(self.wake_phrase)


if __name__ == "__main__":
    main()
