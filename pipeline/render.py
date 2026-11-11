"""Render a plan into a finished 9:16 reel."""
import colorsys
import json
import math
import shutil
from pathlib import Path

from . import graphics, sound
from .brand import FONTS_DIR, load_style
from .media import ensure_dir, loudness, run
from .timeline import FPS, Timeline


def _zoom_expr(keys, ramp_frames=8):
    """Piecewise zoom: increases snap, decreases ease out over `ramp_frames`."""
    ramp = ramp_frames / FPS
    segs = []
    for i, (t, z) in enumerate(keys):
        prev = keys[i - 1][1] if i else z
        nxt = keys[i + 1][0] if i + 1 < len(keys) else 9999
        if z < prev:
            segs.append((t, t + ramp, prev, z))
            segs.append((t + ramp, nxt, z, z))
        else:
            segs.append((t, nxt, z, z))
    expr = "1"
    for a, b, z0, z1 in reversed(segs):
        val = f"{z0}" if z0 == z1 else f"({z0}+({z1}-{z0})*(T-{a:.4f})/{b - a:.4f})"
        expr = f"if(lt(T,{b:.4f}),{val},{expr})"
    return expr.replace("T", f"(in/{FPS:.5f})")


def _grade(style):
    g = style["grade"]
    r, gg, b = colorsys.hsv_to_rgb(g["shadows"]["hue_deg"] / 360, 1, 1)
    mean = (r + gg + b) / 3
    k = g["shadows"]["saturation_pct"] / 100 * 0.8
    return (f"colorbalance=rs={(r-mean)*k:.3f}:gs={(gg-mean)*k:.3f}:bs={(b-mean)*k:.3f},"
            f"eq=contrast={1 + g['contrast']/100:.2f}:saturation={g['saturation']/100:.2f}")


def base(plan, tl, style, work: Path):
    """Cut the keeps, punch in on the zoom keys, grade, scale to 1080x1920. Writes base.mp4 + voice_raw.wav."""
    parts, labels = [], ""
    for i, (s, e) in enumerate(tl.keeps):
        d = e - s
        parts.append(f"[0:v]trim=start={s}:end={e},setpts=PTS-STARTPTS[v{i}]")
        parts.append(f"[0:a]atrim=start={s}:end={e},asetpts=PTS-STARTPTS,afade=t=in:d=0.012,afade=t=out:st={d - 0.014:.3f}:d=0.014[a{i}]")
        labels += f"[v{i}][a{i}]"
    parts.append(f"{labels}concat=n={len(tl.keeps)}:v=1:a=1[vc][ac]")
    keys = sorted([(round(tl.to_edit(s), 4), z) for s, z in plan.get("zoom", [[plan['keeps'][0][0], 1.0]])])
    if keys[0][0] > 0:
        keys.insert(0, (0.0, 1.0))
    ay = plan.get("zoom_anchor_y", 0.22)
    parts.append(f"[vc]zoompan=z='{_zoom_expr(keys)}':x='(iw-iw/zoom)/2':y='(ih-ih/zoom)*{ay}':d=1:s=1080x1920:fps=30000/1001,"
                 f"{_grade(style)},format=yuv420p[vout]")
    (work / "base.filter").write_text(";\n".join(parts), encoding="utf-8")
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", plan["source"], "-/filter_complex", "base.filter",
         "-map", "[vout]", "-c:v", "libx264", "-preset", "medium", "-crf", "14", "-r", "30000/1001", "base.mp4",
         "-map", "[ac]", "-c:a", "pcm_s16le", "-ar", "48000", "voice_raw.wav"], cwd=work)


def matte(work: Path, until: float):
    """Cut the person out of the first `until` seconds (for the depth title) and track the head box."""
    from PIL import Image
    import numpy as np
    from rembg import new_session, remove
    frames, mdir = ensure_dir(work / "hook_frames"), ensure_dir(work / "matte")
    for f in list(frames.glob("*.png")) + list(mdir.glob("*.png")):
        f.unlink()
    n = int(math.ceil(until * FPS)) + 3
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", "base.mp4", "-frames:v", str(n), "hook_frames/f_%04d.png"], cwd=work)
    sess = new_session("u2net_human_seg")
    boxes = {}
    for f in sorted(frames.glob("f_*.png")):
        im = Image.open(f).convert("RGB")
        mask = remove(im.resize((720, 1280), Image.LANCZOS), session=sess, only_mask=True).resize(im.size, Image.LANCZOS)
        out = im.convert("RGBA")
        out.putalpha(mask)
        out.save(mdir / f.name)
        m = np.array(mask) > 128
        ys = np.where(m.any(axis=1))[0]
        if len(ys):
            top = int(ys[0])
            xs = np.where(m[top:top + 260].any(axis=0))[0]
            boxes[f.name] = [int(xs[0]), top, int(xs[-1]), top + 260]
    (mdir / "head_boxes.json").write_text(json.dumps(boxes))
    return boxes


def render(plan: dict, work: Path, exports: Path, log=print) -> Path:
    style = load_style()
    work, exports = ensure_dir(work), ensure_dir(exports)
    tl = Timeline(plan["keeps"])
    log(f"[1/6] cut + zoom + grade  ({tl.total:.2f} s from {len(tl.keeps)} keeps)")
    base(plan, tl, style, work)

    boxes = {}
    depth = plan.get("depth")
    if depth or plan.get("lock"):
        until = max(tl.to_edit(depth["until"]) if depth else 0, (plan.get("lock") or [0, 0])[1])
        log(f"[2/6] person matte for the first {until:.2f} s")
        boxes = matte(work, until)
    else:
        log("[2/6] no depth title, skipping matte")

    log("[3/6] motion graphics")
    sched = graphics.build(plan, tl, style, boxes, work)
    (work / "timeline.json").write_text(json.dumps(sched, indent=1), encoding="utf-8")
    fonts = ensure_dir(work / "fonts")
    for f in FONTS_DIR.glob("*.ttf"):
        shutil.copy(f, fonts / f.name)
    over = "[d][p]overlay=eof_action=pass:enable='lt(t,{:.3f})'[dp];[dp]".format(sched["depth_end"]) if depth else "[d]"
    fc = "[0:v]subtitles=depth.ass:fontsdir=fonts[d];" + ("[1:v]format=rgba[p];" if depth else "") + over + "subtitles=fg.ass:fontsdir=fonts,format=yuv420p[v]"
    inputs = ["-i", "base.mp4"] + (["-framerate", "30000/1001", "-start_number", "1", "-i", "matte/f_%04d.png"] if depth else [])
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs, "-filter_complex", fc, "-map", "[v]",
         "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-profile:v", "high", "-r", "30000/1001", "gfx.mp4"], cwd=work)

    log("[4/6] music bed + sound cues")
    music = plan.get("music", {})
    cuts = [c for c in tl.cut_points() if c >= 2.5]
    drop = tl.to_edit(music["drop"]) if music.get("drop") is not None else (cuts[0] if cuts else min(4.0, tl.total / 4))
    slates = sorted(plan.get("slates", []), key=lambda s: s["at"])
    hats = tl.to_edit(slates[1]["at"]) if len(slates) > 1 else drop + 2.2
    sound.music_bed(work / "bed.wav", tl.total, drop, hats, bpm=music.get("bpm", 100))
    sound.sound_cues(work / "sfx.wav", tl.total, sched["sfx"])

    log("[5/6] voice chain, duck, master")
    sound.mix_and_master(work, style)

    name = plan.get("name", Path(plan["source"]).stem)
    out = exports / f"{name}_tracking-marks.mp4"
    log(f"[6/6] export -> {out}")
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", "gfx.mp4", "-i", "master.wav", "-map", "0:v", "-map", "1:a",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-shortest", "-movflags", "+faststart", out], cwd=work)
    picks = "+".join(f"eq(n\\,{int(i * tl.total * FPS / 16)})" for i in range(16))
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", out, "-vf", f"select='{picks}',scale=270:480,tile=8x2:padding=6",
         "-frames:v", "1", work / "sheet.jpg"])
    lv = loudness(out)
    log(f"done: {tl.total:.2f} s · {lv.get('I')} LUFS · peak {lv.get('peak')} dBFS · {sched['events']} graphic events"
        + (f" · shrunk to fit: {', '.join(sched['shrunk'])}" if sched["shrunk"] else ""))
    return out
