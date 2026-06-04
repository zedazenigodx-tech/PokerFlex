"""
PokerFlex Voice Module — Integrated voice capture for the Grok session.

Usage from inside the agent:
    from voice import capture_voice
    text = capture_voice()   # blocks until user holds Space, speaks, releases

This is designed so you can trigger it with /voice and it feels native.
"""

import time
import tempfile
import os
from typing import Optional

import numpy as np
import keyboard
import sounddevice as sd
import soundfile as sf
from win32gui import GetForegroundWindow, GetWindowText
from faster_whisper import WhisperModel

# ====================== CONFIG ======================
MODEL_SIZE = "small"
LANGUAGE = "en"
SAMPLE_RATE = 16000
CHANNELS = 1
TERMINAL_KEYWORDS = ["powershell", "cmd", "terminal", "command prompt", "grok", "python", "windows terminal", "ps>", "administrator", "mingw", "git bash"]

_model: Optional[WhisperModel] = None


def _is_terminal_focused() -> bool:
    """Check if a terminal-like window is currently focused."""
    try:
        title = GetWindowText(GetForegroundWindow()).lower()
        return any(kw in title for kw in TERMINAL_KEYWORDS)
    except Exception:
        return True


def _get_whisper_model() -> WhisperModel:
    global _model
    if _model is None:
        print("[Voice] Loading Whisper model (first time only)...")
        _model = WhisperModel(MODEL_SIZE, device="auto", compute_type="auto")
        print("[Voice] Model ready.\n")
    return _model


def capture_voice(
    instruction: str = "Hold SPACE and speak your prompt. Release SPACE when done.",
    timeout: float = 60.0
) -> str:
    """
    Push-to-talk voice capture.

    - User holds SPACE (while this terminal is focused)
    - Records while held
    - On release: transcribes and returns the text
    - If nothing captured or timeout, returns empty string
    """
    print(f"\n[VOICE] Voice capture active")
    print(f"   {instruction}")
    print("   (Press ESC to cancel)\n")

    audio_frames = []
    recording = False
    start_time = time.time()

    def audio_callback(indata, frames, time_info, status):
        if recording:
            audio_frames.append(indata.copy())

    try:
        while True:
            if time.time() - start_time > timeout:
                print("[Voice timeout]")
                return ""

            if keyboard.is_pressed("esc"):
                print("[Voice capture cancelled]")
                return ""

            focused = _is_terminal_focused()

            if keyboard.is_pressed("space") and focused and not recording:
                # Start recording
                recording = True
                audio_frames = []

                try:
                    stream = sd.InputStream(
                        samplerate=SAMPLE_RATE,
                        channels=CHANNELS,
                        callback=audio_callback,
                        dtype="float32"
                    )
                    stream.start()
                    print("[Recording] keep holding Space...", end="", flush=True)
                except Exception as e:
                    print(f"\n[ERROR] Could not open microphone: {e}")
                    return ""

                # Wait for release
                while keyboard.is_pressed("space") and _is_terminal_focused():
                    time.sleep(0.03)

                # Stop
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass

                recording = False
                print(" [stopped]")

                if not audio_frames:
                    print("[No audio captured — try again]")
                    time.sleep(0.3)
                    continue

                # Transcribe
                audio_data = np.concatenate(audio_frames, axis=0)
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    wav_path = tmp.name
                sf.write(wav_path, audio_data, SAMPLE_RATE)

                print("[Transcribing...]")
                model = _get_whisper_model()
                segments, _ = model.transcribe(
                    wav_path,
                    language=LANGUAGE,
                    beam_size=5,
                    vad_filter=True,
                )
                text = " ".join(s.text.strip() for s in segments).strip()

                try:
                    os.unlink(wav_path)
                except Exception:
                    pass

                if text:
                    print(f"\n[Heard]: {text}\n")
                    return text
                else:
                    print("[No speech detected]")
                    time.sleep(0.3)
                    continue

            elif keyboard.is_pressed("space") and not focused:
                print("[Warning] Terminal not focused — switch back to this window")
                time.sleep(0.2)
            else:
                time.sleep(0.05)

    except KeyboardInterrupt:
        print("\n[Voice capture interrupted]")
        return ""


if __name__ == "__main__":
    # Allow running standalone for testing
    result = capture_voice()
    if result:
        print("Final transcription:")
        print(result)
