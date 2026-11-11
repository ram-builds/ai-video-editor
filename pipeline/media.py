"""FFmpeg helpers: running commands, probing, and a speech-energy envelope."""
import json
import subprocess
from pathlib import Path

import numpy as np


def run(cmd, cwd=None):
    """Run a command; raise with its stderr tail on failure."""
    p = subprocess.run([str(c) for c in cmd], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed ({p.returncode}):\n" + p.stderr[-3000:])
    return p


def probe(path) -> dict:
    out = run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path]).stdout
    return json.loads(out)


def duration(path) -> float:
    return float(probe(path)["format"]["duration"])


def energy_db(path, hop=0.02, sr=16000):
    """Per-hop RMS level in dBFS of the clip's audio (mono, 16 kHz)."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768
    n = int(hop * sr)
    frames = x[: len(x) // n * n].reshape(-1, n)
    return 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-9), hop


def loudness(path) -> dict:
    """Integrated loudness, LRA and true peak of a file."""
    err = run(["ffmpeg", "-hide_banner", "-i", path, "-af", "ebur128=peak=true", "-vn", "-f", "null", "-"]).stderr
    summary = err[err.rfind("Summary:"):]
    vals = {}
    for key, tag in (("I", "I:"), ("LRA", "LRA:"), ("peak", "Peak:")):
        line = [l for l in summary.splitlines() if l.strip().startswith(tag)]
        if line:
            vals[key] = float(line[-1].split()[1])
    return vals


def ensure_dir(p) -> Path:
    p = Path(p)
    p.mkdir(parents=True, exist_ok=True)
    return p
