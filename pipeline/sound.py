"""Original music bed, brand sound cues, voice chain and loudness master."""
import json
import wave
from pathlib import Path

import numpy as np

from .media import run

SR = 48000


def _lp(x, fc):
    """One-pole low-pass; fc may vary per sample."""
    a = np.exp(-2 * np.pi * np.broadcast_to(np.asarray(fc, dtype=float), x.shape) / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc = (1 - a[i]) * x[i] + a[i] * acc
        y[i] = acc
    return y


def _hp(x, fc):
    return x - _lp(x, fc)


def _put(buf, start, sig):
    i = int(start * SR)
    if 0 <= i < len(buf):
        sig = sig[: len(buf) - i]
        buf[i:i + len(sig)] += sig


def _write(path, mono, width=0.0):
    left, right = mono, mono
    if width:
        d = int(0.011 * SR)
        right = np.concatenate([np.zeros(d), mono[:-d]]) * (1 - width) + mono * width
    st = np.stack([left, right], 1)
    st = st / (np.abs(st).max() + 1e-9) * 0.89
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((st * 32767).astype(np.int16).tobytes())


def music_bed(path, total, drop, hats_from, bpm=100, seed=7):
    """A-minor pad + sub + kick/hat. Dark and filtered before `drop`, riser into it, beat after."""
    rng = np.random.default_rng(seed)
    n = int((total + 0.05) * SR)
    t = np.arange(n) / SR
    beat, chords = 60 / bpm, [(57, 60, 64), (53, 57, 60), (48, 52, 55), (55, 59, 62)]
    bar = 4 * beat
    note = lambda m: 440 * 2 ** ((m - 69) / 12)
    pad, bass, drums = np.zeros(n), np.zeros(n), np.zeros(n)
    for b in range(int(np.ceil(total / bar)) + 1):
        st, ch = b * bar, chords[b % 4]
        ln = int((bar + 0.3) * SR)
        env = np.ones(ln)
        env[: int(0.35 * SR)] = np.linspace(0, 1, int(0.35 * SR))
        env[-int(0.5 * SR):] *= np.linspace(1, 0, int(0.5 * SR))
        tt = np.arange(ln) / SR
        s = sum(np.sin(2 * np.pi * note(m) * (1 + det) * h * tt) / h * (1 if h == 1 else 0.6)
                for m in ch for det in (-0.0012, 0.0012) for h in range(1, 9))
        _put(pad, st, s * env * 0.05)
        e = np.exp(-np.arange(int(0.7 * SR)) / SR * 4)
        for k in (0, 2):
            _put(bass, st + k * beat, np.sin(2 * np.pi * note(ch[0] - 24) * np.arange(len(e)) / SR) * e * 0.35)
    pad = _lp(pad, np.where(t < drop, 700.0, 2600.0))
    kt = np.arange(int(0.22 * SR)) / SR
    kick = np.sin(2 * np.pi * (45 + 75 * np.exp(-kt * 30)) * kt) * np.exp(-kt * 14) * 0.9
    hl = int(0.05 * SR)
    hat = _hp(rng.standard_normal(hl), 7000) * np.exp(-np.arange(hl) / SR * 90) * 0.18
    for i in range(int(total / beat) + 1):
        if i * beat >= drop - 0.01:
            _put(drums, i * beat, kick)
        if i * beat + beat / 2 >= hats_from:
            _put(drums, i * beat + beat / 2, hat)
    r0 = max(0.0, drop - 0.8)
    rn = int((drop - r0) * SR)
    if rn > 0:
        rt = np.arange(rn) / SR
        _put(drums, r0, _hp(rng.standard_normal(rn), 1500 + 6000 * rt / rt[-1]) * (rt / rt[-1]) ** 2 * 0.22)
    bed = pad + bass + drums
    f = int(0.35 * SR)
    bed[-f:] *= np.linspace(1, 0, f)
    _write(path, bed / (np.abs(bed).max() + 1e-9), width=0.5)


def sound_cues(path, total, cues, seed=11):
    """Brand cue sheet: click (tracking lock), thump (depth fill), zip (tape), tick (scan wipe), chime (CTA done)."""
    rng = np.random.default_rng(seed)
    n = int((total + 0.05) * SR)
    out = np.zeros(n)
    def tt(sec): return np.arange(int(sec * SR)) / SR
    def click():
        t = tt(0.03); return (np.sin(2 * np.pi * 2200 * t) * 0.5 + _hp(rng.standard_normal(len(t)), 3000) * 0.5) * np.exp(-t * 180) * 0.6
    def thump():
        t = tt(0.35); return np.sin(2 * np.pi * (40 + 30 * np.exp(-t * 12)) * t) * np.exp(-t * 9)
    def zip_():
        t = tt(0.09); return _lp(_hp(rng.standard_normal(len(t)), 2000 + 5000 * t / t[-1]), 9000) * np.sin(np.pi * t / t[-1]) * 0.35
    def tick():
        t = tt(0.13); return np.sin(2 * np.pi * np.cumsum(800 + 1800 * t / t[-1]) / SR) * np.sin(np.pi * t / t[-1]) * 0.35
    def chime():
        t = tt(0.9); return (np.sin(2 * np.pi * 1318.5 * t) + 0.6 * np.sin(2 * np.pi * 1975.5 * t) * (t > 0.08)) * np.exp(-t * 5) * 0.35
    gen = {"click": click, "thump": thump, "zip": zip_, "tick": tick, "chime": chime}
    for kind, at in cues:
        _put(out, at, gen[kind]())
    f = int(0.05 * SR)
    out[-f:] *= np.linspace(1, 0, f)
    _write(path, out if out.any() else out + 1e-6)


def mix_and_master(work: Path, style: dict):
    """Voice chain + ducked bed + cues, then a two-pass loudnorm to the brand target."""
    a = style["audio"]
    duck = (f"[0:a]highpass=f=80,afftdn=nf=-28,deesser=i=0.4,acompressor=threshold=-24dB:ratio=3:attack=5:release=90:makeup=3,"
            f"loudnorm=I=-16:TP=-2:LRA=5,aresample={SR},asplit[vm][vs];"
            f"[1:a]loudnorm=I=-25:TP=-6,aresample={SR}[b0];[b0][vs]sidechaincompress=threshold=0.02:ratio=4:attack=10:release=300[bd];"
            f"[2:a]volume=-9dB[sx];[vm][bd][sx]amix=inputs=3:normalize=0:duration=first[m]")
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", "voice_raw.wav", "-i", "bed.wav", "-i", "sfx.wav",
         "-filter_complex", duck, "-map", "[m]", "-ar", str(SR), "-c:a", "pcm_s24le", "premix.wav"], cwd=work)
    target = f"I={a['integrated_lufs']}:TP={a['true_peak_dbtp']}:LRA=7"
    err = run(["ffmpeg", "-hide_banner", "-i", "premix.wav", "-af", f"loudnorm={target}:print_format=json", "-f", "null", "-"], cwd=work).stderr
    m = json.loads(err[err.rfind("{"): err.rfind("}") + 1])
    measured = (f"measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
                f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}")
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", "premix.wav", "-af",
         f"loudnorm={target}:{measured}:linear=true,aresample={SR}", "-c:a", "pcm_s24le", "master.wav"], cwd=work)
