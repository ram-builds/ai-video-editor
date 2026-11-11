"""Tracking Marks motion graphics as ASS subtitles (rendered by libass inside FFmpeg).

Writes depth.ass (drawn under the person cutout) and fg.ass (everything on top), and returns
the edit-time schedule (sound cues, card, CTA) that the sound and storyboard steps use.
"""
from pathlib import Path

from .brand import (F_BLACK, F_FILLER, F_HEAVY, F_MONO, F_MONO_BOLD, ass_color, text_width)
from .timeline import FPS, Timeline

CROSS = "m 24 0 l 30 0 30 54 24 54 m 0 24 l 54 24 54 30 0 30"  # 54 px tracking cross
FULL = "m 0 0 l 1080 0 1080 1920 0 1920"


def _ts(t):
    cs = int(round(max(0.0, t) * 100))
    return "%d:%02d:%02d.%02d" % (cs // 360000, cs // 6000 % 60, cs // 100 % 60, cs % 100)


def _header(style):
    c, sz = style["colors"], style["captions"]["sizes_px"]
    raw = lambda h: ass_color(h).strip("&H")
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{F_HEAVY},{sz['caption']},&H00FFFFFF,&H00FFFFFF,&H70000000,&H50000000,0,0,0,0,100,100,0,0,1,2,4,1,0,0,0,1
Style: Fill,{F_FILLER},{sz['filler']},&H00{raw(c['filler'])},&H00FFFFFF,&H70000000,&H50000000,0,0,0,0,100,100,0,0,1,2,3,1,0,0,0,1
Style: Tape,{F_BLACK},{sz['keyword_tape']},&H00FFFFFF,&H00FFFFFF,&H00{raw(c['cobalt'])},&H00000000,0,0,0,0,100,100,0,0,3,14,0,1,0,0,0,1
Style: Num,{F_MONO_BOLD},{sz['number']},&H00FFFFFF,&H00FFFFFF,&H00000000,&H8C000000,0,0,0,0,100,100,0,0,1,0,4,1,0,0,0,1
Style: Slate,{F_MONO},{sz['slate']},&H00FFFFFF,&H00FFFFFF,&H47{raw(c['ink'])},&H00000000,0,0,0,0,100,100,4,0,3,12,0,7,0,0,0,1
Style: Depth,{F_BLACK},300,&HFF{raw(c['cobalt'])},&HFFFFFFFF,&H00FFFFFF,&H00000000,0,0,0,0,100,100,-6,0,1,5,0,8,0,0,0,1
Style: Draw,{F_MONO},30,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
Style: Mono,{F_MONO},30,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,2,0,1,0,0,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def build(plan: dict, tl: Timeline, style: dict, head_boxes: dict, out_dir: Path) -> dict:
    col = style["colors"]
    WHITE, FILLER, COBALT, MARKER, INK, PLATE = (ass_color(col[k]) for k in ("caption", "filler", "cobalt", "marker", "ink", "plate"))
    MUTED = ass_color("#585E6E")
    safe = style["safe_zone_px"]
    X0, XMAX, TOP = safe["left_margin"], 1080 - safe["right"], safe["top"]
    SZ = style["captions"]["sizes_px"]
    LEAD = style["captions"]["lead_frames"] / FPS
    KIND = {"w": ("Cap", F_HEAVY, SZ["caption"]), "f": ("Fill", F_FILLER, SZ["filler"]),
            "t": ("Tape", F_BLACK, SZ["keyword_tape"]), "n": ("Num", F_MONO_BOLD, SZ["number"])}
    E = tl.to_edit
    total = tl.total
    fg, depth, sfx = [], [], []

    def ev(lst, a, b, st, text, layer=1):
        if b > a:
            lst.append(f"Dialogue: {layer},{_ts(a)},{_ts(b)},{st},,0,0,0,,{text}")

    def appear(src_t):  # captions show LEAD before the word, never before their own segment
        a = E(src_t)
        return max(tl.segment_start(a), a - LEAD)

    cta = plan.get("cta")
    cta_start = round(total * cta.get("start_fraction", 0.75), 2) if cta else None
    card = plan.get("card")
    card_in, card_out = (E(card["in"]), E(card["out"])) if card else (None, None)

    # ---------- captions ----------
    chunks = sorted(plan.get("captions", []), key=lambda c: c["t"])
    shrunk = []
    for i, ch in enumerate(chunks):
        a = appear(ch["t"])
        b = appear(chunks[i + 1]["t"]) if i + 1 < len(chunks) else total
        if card_in is not None and a < card_in < b:
            b = card_in
        if card_in is not None and card_in <= a < card_out:
            continue
        bottom = 1115 if cta_start is not None and a >= cta_start - 0.01 else 1245
        y = bottom
        for line in reversed(ch["lines"]):
            kinds = [k for k, _ in line]
            main = max(KIND[k][2] for k in kinds)
            scale = 1.0
            while True:
                w = sum(text_width(t, KIND[k][1], round(KIND[k][2] * scale)) for k, t in line)
                w += (28 if "t" in kinds else 0) + (78 if "n" in kinds else 0)
                if X0 + w <= XMAX or scale < 0.7:
                    break
                scale -= 0.02
            if scale < 1:
                shrunk.append(" ".join(t for _, t in line))
            lh = round(main * scale)
            txt = "".join(("{\\rFill" if k == "f" else "{\\r" + KIND[k][0]) +
                          ("" if scale == 1 else f"\\fs{round(KIND[k][2] * scale)}") + "}" + t for k, t in line)
            if "t" in kinds:
                yb = y - 14
                w = text_width(line[0][1], F_BLACK, lh) + 28
                c0, c1 = f"\\clip({X0},{yb-lh-30},{X0},{yb+20})", f"\\clip({X0},{yb-lh-30},{X0+w+4},{yb+20})"
                ev(fg, a, b, "Tape", f"{{\\an1\\pos({X0+14},{yb}){c0}\\t(0,100,{c1})}}{txt}", 3)
                sfx.append(["zip", round(a + 0.02, 3)])
                y = yb - lh - 36
            elif "n" in kinds:
                ev(fg, a, b, "Num", f"{{\\an1\\pos({X0+78},{y})\\fscx92\\fscy92\\t(0,133,\\fscx100\\fscy100)}}{txt}", 2)
                cy = y - round(lh * 0.42)
                ev(fg, a, b, "Draw", f"{{\\an7\\pos({X0},{cy-27})\\p1\\c{MARKER}}}{CROSS}{{\\p0}}", 2)
                y -= lh + 6
            else:
                ev(fg, a, b, "Cap", f"{{\\an1\\pos({X0},{y})\\blur2}}{txt}", 2)
                y -= lh + 6

    # ---------- slates ----------
    slates = sorted(plan.get("slates", []), key=lambda s: s["at"])
    for i, s in enumerate(slates):
        a = E(s["at"]) if i else 0.0
        b = E(slates[i + 1]["at"]) if i + 1 < len(slates) else total
        w = text_width(f"{s['id']}  {s['name']}", F_MONO, SZ["slate"], 4) + 24
        ev(fg, a, b, "Slate", f"{{\\an7\\pos({X0+12},{TOP+12})\\clip({X0-14},200,{X0-14},300)\\t(0,133,\\clip({X0-14},200,{X0+w+14},300))}}"
                              f"{{\\c{MARKER}}}{s['id']}{{\\c{WHITE}}}  {s['name']}", 6)

    # ---------- depth title, drawn under the person cutout ----------
    d = plan.get("depth")
    depth_end = 0.0
    if d:
        depth_end = max(0.0, E(d["until"]) - LEAD)
        size = 300
        while text_width(d["word"], F_BLACK, size, -6) > 980:
            size -= 4
        ev(depth, 0.0, depth_end, "Depth", f"{{\\an8\\pos(540,300)\\fs{size}\\t(450,600,\\1a&H00&\\3a&HFF&)}}{d['word']}", 1)
        sfx.append(["thump", 0.45])

    # ---------- tracking lock that follows the head frame by frame ----------
    lock = plan.get("lock")
    if lock and head_boxes:
        names = sorted(head_boxes)
        fa, fb = int(lock[0] * FPS), int(lock[1] * FPS)
        raw = [head_boxes[names[min(i, len(names) - 1)]] for i in range(fa, fb + 1)]
        sm = [[sum(v[j] for v in raw[max(0, i - 2): i + 3]) / len(raw[max(0, i - 2): i + 3]) for j in range(4)] for i in range(len(raw))]
        for i, (x0, y0, x1, y1) in enumerate(sm):
            x0, y0, x1, y1 = x0 - 26, y0 - 26, x1 + 26, y1 + 26
            t0, t1 = (fa + i) / FPS, (fa + i + 1) / FPS
            k = min(1.0, i / 4)
            sc, al = round(240 - 140 * k), "%02X" % round(255 * (1 - k))
            for cx, cy in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
                ev(fg, t0, t1, "Draw", f"{{\\an5\\pos({cx:.0f},{cy:.0f})\\p1\\c{MARKER}\\fscx{sc}\\fscy{sc}\\alpha&H{al}&}}{CROSS}{{\\p0}}", 4)
            if k >= 1:
                ev(fg, t0, t1, "Mono", f"{{\\an7\\pos({x0:.0f},{y1+40:.0f})\\c{MARKER}\\fs28}}TRK 01 · LOCK", 4)
        sfx.append(["click", round(lock[0] + 0.03, 3)])

    # ---------- full-screen card behind a scan wipe ----------
    if card:
        ca, cb = card_in, card_out
        ev(fg, ca, cb, "Draw", f"{{\\an7\\pos(0,0)\\p1\\c{PLATE}\\clip(0,0,1080,0)\\t(0,200,\\clip(0,0,1080,1920))}}{FULL}{{\\p0}}", 5)
        ev(fg, ca, ca + 0.24, "Draw", f"{{\\an7\\move(0,-6,0,1914,0,200)\\p1\\c{MARKER}\\blur10\\alpha&H60&}}m 0 -8 l 1080 -8 1080 14 0 14{{\\p0}}", 7)
        ev(fg, ca, ca + 0.24, "Draw", f"{{\\an7\\move(0,0,0,1920,0,200)\\p1\\c{MARKER}}}m 0 0 l 1080 0 1080 6 0 6{{\\p0}}", 7)
        sfx.append(["tick", round(ca, 3)])
        if card.get("label"):
            ev(fg, ca + 0.12, cb, "Mono", f"{{\\an7\\pos({X0},560)\\c{MUTED}\\fs30}}{card['label']}", 6)
        if card.get("title"):
            ev(fg, ca + 0.12, cb, "Tape", f"{{\\an7\\pos({X0},600)\\rTape\\3a&HFF&\\bord0\\c{INK}\\fs104}}{card['title']}", 6)
        for j, row in enumerate(card.get("rows", [])):
            ra, y = max(ca + 0.12, E(row["at"])), 820 + j * 190
            rsz = 76
            while X0 + 80 + text_width(row["big"], F_BLACK, rsz) > XMAX:
                rsz -= 2
            c0, c1 = f"\\clip({X0},{y-10},{X0},{y+150})", f"\\clip({X0},{y-10},{XMAX+60},{y+150})"
            ev(fg, ra, cb, "Draw", f"{{\\an7\\pos({X0},{y+14}){c0}\\t(0,100,{c1})\\p1\\c{MARKER}}}{CROSS}{{\\p0}}", 6)
            ev(fg, ra, cb, "Tape", f"{{\\an7\\pos({X0+80},{y}){c0}\\t(0,100,{c1})\\rTape\\3a&HFF&\\bord0\\c{INK}\\fs{rsz}}}{row['big']}", 6)
            if row.get("small"):
                ev(fg, ra, cb, "Mono", f"{{\\an7\\pos({X0+82},{y+rsz+14}){c0}\\t(0,100,{c1})\\c{MUTED}\\fs32}}{row['small']}", 6)

    # ---------- render-queue CTA ----------
    if cta:
        qa, qb = cta_start, total
        QX0, QX1, QY0, QY1 = X0, XMAX, 1190, 1495
        ev(fg, qa, qb, "Draw", f"{{\\an7\\pos(0,0)\\p1\\c{INK}\\alpha&H14&\\bord3\\3c{WHITE}\\3a&HE0&\\clip({QX0-4},{QY0-4},{QX0-4},{QY1+4})"
                               f"\\t(0,100,\\clip({QX0-4},{QY0-4},{QX1+4},{QY1+4}))}}m {QX0} {QY0} l {QX1} {QY0} {QX1} {QY1} {QX0} {QY1}{{\\p0}}", 6)
        ev(fg, qa + 0.07, qb, "Mono", f"{{\\an7\\pos({QX0+32},{QY0+26})\\c{FILLER}\\fs28\\fsp4}}RENDER QUEUE", 7)
        ev(fg, qa + 0.07, qb, "Mono", f"{{\\an9\\pos({QX1-32},{QY0+26})\\c{FILLER}\\fs28\\fsp4}}1/1", 7)
        word = cta.get("word", "FOLLOW")
        fsz = 72
        fw = text_width(word, F_BLACK, fsz) + 28
        ev(fg, qa + 0.10, qb, "Tape", f"{{\\an7\\pos({QX0+46},{QY0+92})\\fs{fsz}}}{word}", 7)
        if cta.get("text"):
            ev(fg, qa + 0.10, qb, "Mono", f"{{\\an7\\pos({QX0+32+fw+22},{QY0+112})\\fs34}}{cta['text']}", 7)
        for j, row in enumerate(cta.get("rows", [])[:1]):
            sa, ry = max(qa + 0.1, E(row["at"])), QY0 + 196
            ev(fg, sa, qb, "Mono", f"{{\\an7\\pos({QX0+32},{ry})\\c{FILLER}\\fs32\\clip({QX0},{ry-16},{QX0},{ry+44})"
                                   f"\\t(0,100,\\clip({QX0},{ry-16},{QX1},{ry+44}))}}{row['text']}", 7)
        bar_y, done = QY1 - 34, max(qa + 0.6, total - 0.55)
        bar = f"m {QX0+32} {bar_y} l {QX1-32} {bar_y} {QX1-32} {bar_y+10} {QX0+32} {bar_y+10}"
        ev(fg, qa + 0.1, qb, "Draw", f"{{\\an7\\pos(0,0)\\p1\\c{WHITE}\\alpha&HE0&}}{bar}{{\\p0}}", 7)
        ev(fg, qa + 0.1, qb, "Draw", f"{{\\an7\\pos(0,0)\\p1\\c{MARKER}\\clip({QX0+32},{bar_y-2},{QX0+32},{bar_y+12})"
                                     f"\\t(0,{int((done-qa-0.1)*1000)},\\clip({QX0+32},{bar_y-2},{QX1-32},{bar_y+12}))}}{bar}{{\\p0}}", 8)
        sfx.append(["chime", round(done, 3)])

    head = _header(style)
    (out_dir / "fg.ass").write_text(head + "\n".join(fg) + "\n", encoding="utf-8")
    (out_dir / "depth.ass").write_text(head + "\n".join(depth) + "\n", encoding="utf-8")
    return {"total": total, "sfx": sorted(sfx, key=lambda s: s[1]), "depth_end": depth_end,
            "card": [card_in, card_out] if card else None, "cta_start": cta_start, "shrunk": shrunk, "events": len(fg)}
