#!/usr/bin/env python
"""
PokerFlex Standalone Packaging Script (PyInstaller)

Produces a self-contained PokerFlex.exe (one-file or one-dir) that bundles:
- Python runtime + all dependencies (from the current env)
- The A1 brain, run_brain, vision, notes, ICM, hotkeys, live listener, etc.
- launch_assistant behavior via the entry (supports --background --live --tray etc)
- equity_matrix.json data file

Usage (from project root, after `pip install -r requirements.txt && pip install -e .` and optionally `pip install pystray pyinstaller`):
    python build_exe.py
    python build_exe.py --onefile --noconsole   # pure tray-friendly no console window (tray still works; Show Console limited)
    python build_exe.py --onedir

Output: dist/PokerFlex.exe   (or dist/PokerFlex/PokerFlex.exe + folder for onedir)

The resulting exe supports EVERYTHING the source does:
  PokerFlex.exe --help
  PokerFlex.exe --background --live --simulate-vision --pos BTN --stack 100 --auto-capture
  PokerFlex.exe --tray --live --simulate-vision     # <-- recommended for "set and forget" tray UX
  PokerFlex.exe --tray --live --real-vision ...     # real ClubGG (tesseract still required on the target machine PATH)

Tesseract note (critical for real vision/OCR):
- The packaged exe does NOT bundle the native tesseract-ocr binary (license + size + platform reasons).
- For --real-vision / live real table reading on the target PC:
  1. Install tesseract from https://github.com/UB-Mannheim/tesseract/wiki (Windows 5.x recommended)
  2. Add its install folder (e.g. C:\Program Files\Tesseract-OCR) to the SYSTEM PATH
  3. Restart any consoles / re-launch the .exe
- Verify on target: tesseract --version   (or the exe will still run, but real captures use fallback/low-conf + templates)
- --simulate-vision and all non-vision features (hotkeys, notes, ICM, manual/json, tray) work 100% without tesseract.
- The exe writes/reads clubgg_*.json + logs in the CWD from which you launch it (portable session).

Dev / source remains unchanged:
  pip install -e .
  python -m pokerflex ...
  launch_assistant.bat

Cross-platform note: PyInstaller .exe is Windows. For Linux/mac users the source + `python -m` + optional pystray is the way (tray code is crossplat).

Build env tips:
- Use a clean venv with the exact deps you want bundled.
- `pip install pyinstaller pystray` (pystray optional at runtime but recommended for tray in the exe).
- If building --noconsole, tray "Show Console" will only be able to popup guidance (no real console to attach); use the console build + --tray hide for best of both.
- Large onefile may take time + antivirus false positives sometimes (common for PyInstaller); onedir is faster/smaller updates.

After build, you can copy dist/PokerFlex.exe (and any .bat wrapper you make) anywhere. Double-clicking an exe built for tray will show the chip icon in tray immediately.
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
DIST = HERE / "dist"
BUILD = HERE / "build"

def main():
    import argparse
    p = argparse.ArgumentParser(description="Build PokerFlex standalone exe with PyInstaller")
    p.add_argument("--onefile", action="store_true", default=True, help="Produce single PokerFlex.exe (default)")
    p.add_argument("--onedir", action="store_true", help="Produce a PokerFlex/ folder with exe + deps (faster updates, smaller delta)")
    p.add_argument("--noconsole", "--windowed", action="store_true", help="No console window (good for pure tray; Show Console limited). Use with --tray.")
    p.add_argument("--name", default="PokerFlex", help="Output exe/folder name")
    p.add_argument("--clean", action="store_true", default=True, help="Clean previous build/dist (default)")
    args = p.parse_args()

    if args.onedir:
        args.onefile = False

    if args.clean:
        for d in (DIST, BUILD):
            if d.exists():
                print(f"Cleaning {d}...")
                shutil.rmtree(d, ignore_errors=True)

    # Ensure equity data is findable (package_data)
    equity_src = HERE / "pokerflex" / "equity_matrix.json"
    if not equity_src.exists():
        # fallback for root copy in some dev states
        equity_src = HERE / "equity_matrix.json"
    if not equity_src.exists():
        print("WARNING: equity_matrix.json not found next to build; it may be missing in the exe (non-fatal for non-equity paths).")

    # PyInstaller command
    pyinstaller = [sys.executable, "-m", "PyInstaller"]

    entry = "pokerflex/__main__.py"  # the documented zero-touch entry (delegates to run_brain with full flags)

    common = [
        "--name", args.name,
        "--add-data", f"{equity_src};pokerflex" if os.name == "nt" else f"{equity_src}:pokerflex",
        # Include package as needed; PyInstaller usually auto-discovers .py but we are explicit for data
        "--hidden-import", "pokerflex",
        "--hidden-import", "pokerflex.run_brain",
        "--hidden-import", "pokerflex.capture",
        "--hidden-import", "pokerflex.advisor",
        "--hidden-import", "pokerflex.poker_engine",
        "--hidden-import", "pokerflex.models",
        # Tray (optional at runtime but bundle if present so --tray works in exe without user pip)
        "--hidden-import", "pystray",
        "--hidden-import", "pystray._win32",
        # Common runtime things that are sometimes missed
        "--hidden-import", "PIL",
        "--hidden-import", "PIL.Image",
        "--hidden-import", "PIL.ImageDraw",
        "--hidden-import", "PIL.ImageFont",
        "--collect-all", "pystray",  # safe even if not installed (will just skip)
        "--log-level", "WARN",
    ]

    if args.onefile:
        common.append("--onefile")
    else:
        common.append("--onedir")

    if args.noconsole:
        common.append("--noconsole")
        common.append("--windowed")  # alias some versions use

    # Icon: try to generate a simple .ico on the fly using Pillow (already a dep)
    icon_arg = []
    try:
        from PIL import Image, ImageDraw, ImageFont
        ico_path = HERE / "_tmp_pokerflex_icon.ico"
        size = 256
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        m = 8
        draw.ellipse([m, m, size-m, size-m], fill=(180, 20, 20, 255), outline=(255, 230, 210, 255), width=6)
        im2 = size // 4
        draw.ellipse([im2, im2, size-im2, size-im2], fill=(255, 250, 250, 235), outline=(130, 10, 10, 220), width=2)
        cx = cy = size // 2
        import math
        for ang in range(0, 360, 36):
            rad = math.radians(ang)
            r1, r2 = size * 0.34, size * 0.45
            x1 = cx + int(r1 * math.cos(rad))
            y1 = cy + int(r1 * math.sin(rad))
            x2 = cx + int(r2 * math.cos(rad))
            y2 = cy + int(r2 * math.sin(rad))
            draw.line([(x1, y1), (x2, y2)], fill=(180, 20, 20, 255), width=5)
        try:
            fnt = ImageFont.truetype("arial.ttf", size // 4)
        except:
            fnt = ImageFont.load_default()
        txt = "PF"
        bbox = draw.textbbox((0, 0), txt, font=fnt)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(((size - tw) // 2, (size - th) // 2 - 4), txt, fill=(30, 10, 10, 255), font=fnt)
        img.save(ico_path, format="ICO", sizes=[(256,256), (128,128), (64,64), (32,32), (16,16)])
        icon_arg = ["--icon", str(ico_path)]
        print(f"Generated temp icon: {ico_path}")
    except Exception as ex:
        print(f"(icon gen skipped or failed: {ex}; exe will use default icon)")

    cmd = pyinstaller + common + icon_arg + [entry]
    print("Running PyInstaller:")
    print("  " + " ".join(cmd))
    print()

    # Run
    try:
        subprocess.check_call(cmd, cwd=HERE)
    except subprocess.CalledProcessError as ex:
        print(f"\nPyInstaller failed with code {ex.returncode}")
        sys.exit(ex.returncode)

    # Post steps
    exe_name = args.name + (".exe" if os.name == "nt" else "")
    if args.onefile:
        out = DIST / exe_name
        print(f"\n✓ Built: {out}")
    else:
        out_dir = DIST / args.name
        out = out_dir / exe_name
        print(f"\n✓ Built: {out} (onedir at {out_dir})")

    print("""
Next steps / notes for the built artifact:
- Copy the exe (and the whole onedir if used) to your play machine.
- For **tray background** (recommended "set and forget"):
    Double-click the exe, or create a shortcut with target:
      "C:\\path\\to\\PokerFlex.exe" --tray --live --simulate-vision
    (or --tray --live --real-vision after tesseract setup + table visible)
- The exe honors launch_assistant-style defaults when you use --tray.
- Tesseract (real vision only): install separately on the target machine and add to PATH.
  Without it: --simulate-vision + all other features (notes/explo/ICM/hotkeys/tray/live sim/json) are fully functional.
- Logs when using --tray: pokerflex_tray.log next to where you run the exe (or in CWD).
- To persist at login: run the exe with --tray once, then use the tray menu "Run at startup" toggle
  (it creates an editable .bat in your Windows Startup folder).
- Source / dev flow untouched: pip install -e . ; python -m pokerflex still perfect.
- Rebuild after source changes: just re-run this script (clean helps).

Enjoy the invisible co-pilot!
""")

if __name__ == "__main__":
    main()
