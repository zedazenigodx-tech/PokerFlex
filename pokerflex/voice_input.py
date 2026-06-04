"""
Simple Voice Input for Grok session

Run this when you want to speak instead of type:

    python voice_input.py

Then:
- Hold SPACE and speak your prompt
- Release SPACE when done
- The text is printed + copied to your clipboard automatically

Just paste it into the Grok chat.

First run downloads the Whisper model (~500MB). After that it's fast.
"""

import time
import tempfile
import os
import sys

import numpy as np
import keyboard
import sounddevice as sd
import soundfile as sf
from faster_whisper import WhisperModel

# ====================== CONFIG ======================
MODEL_SIZE = "small"
LANGUAGE = "en"
SAMPLE_RATE = 16000
CHANNELS = 1

# Always ignore focus check - makes it way more reliable
FORCE = True

_model = None


def get_model():
    global _model
    if _model is None:
        print("[Voice] Loading speech model (first time only, ~1 min)...")
        _model = WhisperModel(MODEL_SIZE, device="auto", compute_type="auto")
        print("[Voice] Model ready.\n")
    return _model


def record_while_space_held():
    """Hold SPACE to record. Returns audio data or None."""
    audio_frames = []
    recording = False

    def callback(indata, frames, time_info, status):
        if recording:
            audio_frames.append(indata.copy())

    print("\n[READY] Hold SPACE and speak your prompt.")
    print("        Release SPACE when you're finished.")
    print("        (Press ESC to cancel)\n")

    try:
        while True:
            if keyboard.is_pressed("esc"):
                print("[Cancelled]")
                return None

            if keyboard.is_pressed("space") and not recording:
                recording = True
                audio_frames = []

                stream = sd.InputStream(
                    samplerate=SAMPLE_RATE,
                    channels=CHANNELS,
                    callback=callback,
                    dtype="float32"
                )
                stream.start()
                print("[RECORDING] Speaking now... (keep holding Space)")

                # Wait until they release Space
                while keyboard.is_pressed("space"):
                    time.sleep(0.03)

                stream.stop()
                stream.close()
                recording = False
                print("[STOPPED]")

                if audio_frames:
                    return np.concatenate(audio_frames, axis=0)
                else:
                    print("[No audio captured - try again]\n")
                    time.sleep(0.4)

            time.sleep(0.05)

    except KeyboardInterrupt:
        return None


def main():
    print(__doc__)

    # Show default mic so user knows what it's using
    try:
        devices = sd.query_devices()
        default_input = sd.default.device[0]
        if default_input is not None:
            print(f"[Mic] Using: {devices[default_input]['name']}\n")
    except Exception:
        pass

    audio = record_while_space_held()
    if audio is None:
        return

    # Save temp wav
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = tmp.name
    sf.write(wav_path, audio, SAMPLE_RATE)

    # Transcribe
    print("[Transcribing...]")
    model = get_model()
    segments, _ = model.transcribe(wav_path, language=LANGUAGE, beam_size=5, vad_filter=True)
    text = " ".join(s.text.strip() for s in segments).strip()

    try:
        os.unlink(wav_path)
    except Exception:
        pass

    if not text:
        print("[No speech detected]")
        return

    # Print clearly
    print("\n" + "=" * 70)
    print("TRANSCRIPTION:")
    print(text)
    print("=" * 70 + "\n")

    # Auto copy to clipboard
    try:
        import pyperclip
        pyperclip.copy(text)
        print("(Copied to clipboard - just paste it into the chat)\n")
    except Exception:
        print("(Install pyperclip if you want auto-copy: pip install pyperclip)\n")

    print("Done. You can close this window or run it again for another prompt.")


if __name__ == "__main__":
    main()
