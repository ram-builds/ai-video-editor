"""Automatic edit plan: what to keep, captions, keywords, slates, zooms, card and CTA.

The plan is a JSON file in source-clip seconds, so it can be reviewed and edited before rendering.
"""
import re
from pathlib import Path

import numpy as np

from .brand import load_style
from .hinglish import (CTA_VERBS, DISFLUENCIES, FILLERS, HINDI_COMMON, LEADING_FILLERS, OUTRO, OUTRO_LEAD, REEL_VOCAB, fix_spelling,
                       has_devanagari, norm, script_caps, script_vocab, snap, snap_sound, to_latin)
from .media import duration, energy_db
from .timeline import Timeline
from .transcribe import prompt_from_script, transcribe, transcribe_window

MAX_PAUSE = 0.30      # brand: cut every pause longer than this
WORD_PAD = 0.12       # speech this close to a transcribed word counts as that word
UNHEARD_MIN = 0.50    # cut speech runs this long that Whisper could not transcribe


def _clean_words(words, script):
    vocab = script_vocab(script)
    caps = {k: v for k, v in vocab.items() if k in script_caps(script)}
    sound_vocab = sorted({v for k, v in vocab.items() if len(k) >= 4 and k not in FILLERS} | set(REEL_VOCAB))
    out = []
    for w in words:
        if has_devanagari(w["word"]):
            text = " ".join(to_latin(p) for p in w["word"].split())
            snapped = snap(text, vocab)
            text = snapped if snapped != text else snap_sound(text, sound_vocab)
        else:
            text = snap(w["word"], vocab)
            if text == w["word"] and len(norm(text)) >= 4:  # misheard proper nouns (comment -> COMEDK)
                text = snap(text, caps, cutoff=0.6)
        out.append({**w, "text": text, "n": norm(text)})
    out = fix_spelling([w for w in out if w["n"]])
    # "ser karen" -> "share karen": a word right before kar/karo/karein that sounds like a CTA verb
    for i in range(len(out) - 1):
        if out[i + 1]["n"].startswith("kar") and out[i]["n"] not in CTA_VERBS:
            fixed = snap_sound(out[i]["text"], list(CTA_VERBS), cutoff=0.66, min_skeleton=2)
            if fixed != out[i]["text"]:
                out[i] = {**out[i], "text": fixed, "n": norm(fixed)}
    return out


def _recover(raw, words, mask, hop, prompt, notes, log):
    """Re-transcribe speech the full pass skipped; anything still unclear is left for the cutter."""
    worded = np.zeros_like(mask)
    for w in words:
        worded[max(0, int((w["start"] - WORD_PAD) / hop)): int((w["end"] + WORD_PAD) / hop) + 1] = True
    added = []
    for a, b in _runs(mask & ~worded, hop):
        if b - a < UNHEARD_MIN:
            continue
        got = [w for w in transcribe_window(raw, a - 0.3, b + 0.3, prompt)
               if a - 0.15 <= (w["start"] + w["end"]) / 2 <= b + 0.15
               and not any(x["start"] < w["end"] and w["start"] < x["end"] for x in words)]
        conf = sum(w["prob"] for w in got) / len(got) if got else 0
        if got and conf >= 0.5:
            added += got
            notes.append(f"recovered {a:.2f}-{b:.2f}: '{' '.join(w['word'] for w in got)}' (confidence {conf:.2f})")
        else:
            notes.append(f"unclear speech {a:.2f}-{b:.2f}" + (f": '{' '.join(w['word'] for w in got)}' (confidence {conf:.2f})" if got else "") + " -> cut")
    if added:
        log(f"recovered {len(added)} words Whisper skipped")
    return sorted(words + added, key=lambda w: w["start"])


def _speech_mask(raw):
    db, hop = energy_db(raw)
    floor, top = np.percentile(db, 5), np.percentile(db, 98)
    on = db > floor + max(8.0, 0.3 * (top - floor))
    # close tiny gaps, drop blips
    for val, run_len in ((False, int(0.12 / hop)), (True, int(0.08 / hop))):
        i = 0
        while i < len(on):
            if on[i] == val:
                j = i
                while j < len(on) and on[j] == val:
                    j += 1
                if j - i < run_len and i > 0 and j < len(on):
                    on[i:j] = not val
                i = j
            else:
                i += 1
    return on, hop


def _runs(mask, hop):
    out, i = [], 0
    while i < len(mask):
        if mask[i]:
            j = i
            while j < len(mask) and mask[j]:
                j += 1
            out.append([i * hop, j * hop])
            i = j
        else:
            i += 1
    return out


def _cut_ranges(words, keep_outro, notes):
    cuts = []
    # leading fillers ("So,", "um")
    i = 0
    while i < len(words) - 1 and words[i]["n"] in LEADING_FILLERS:
        cuts.append((words[i]["start"] - 0.05, words[i + 1]["start"] - 0.03))
        notes.append(f"cut leading filler '{words[i]['text']}' at {words[i]['start']:.2f}")
        i += 1
    # disfluencies anywhere
    for w in words:
        if w["n"] in DISFLUENCIES:
            cuts.append((w["start"] - 0.03, w["end"] + 0.03))
            notes.append(f"cut '{w['text']}' at {w['start']:.2f}")
    # false starts: the same word again within 3 words, after a comma or pause
    for i in range(len(words)):
        for j in range(i + 1, min(i + 4, len(words))):
            if words[j]["n"] == words[i]["n"] and len(words[i]["n"]) > 1:
                prev = words[j - 1]
                short = words[j]["start"] - words[i]["start"] <= 1.6 and words[i]["end"] - words[i]["start"] <= 1.0
                if short and (prev["text"].endswith(",") or words[j]["start"] - prev["end"] >= 0.15 or j == i + 1):
                    span = " ".join(w["text"] for w in words[i:j])
                    cuts.append((words[i]["start"] - 0.04, words[j]["start"] - 0.04))
                    notes.append(f"cut repeat '{span}' at {words[i]['start']:.2f}")
                break
    # sign-off after the call to action
    if not keep_outro:
        text = " ".join(w["n"] for w in words)
        has_cta = any(w["n"] in CTA_VERBS for w in words)
        for pat in OUTRO:
            k = text.rfind(pat)
            if has_cta and k > len(text) * 0.6:
                idx = text[:k].count(" ")
                while idx > 0 and words[idx - 1]["n"] in OUTRO_LEAD:
                    idx -= 1
                start = words[idx - 1]["end"] + 0.05 if idx > 0 else words[idx]["start"]
                cuts.append((start, 1e9))
                notes.append(f"cut sign-off '{' '.join(w['text'] for w in words[idx:])}' from {start:.2f}")
                break
    return cuts


def _keeps(mask, hop, words, cuts):
    worded = np.zeros_like(mask)
    for w in words:
        worded[max(0, int((w["start"] - WORD_PAD) / hop)): int((w["end"] + WORD_PAD) / hop) + 1] = True
    keep = mask & worded
    for a, b in cuts:
        keep[max(0, int(a / hop)): int(min(b, len(keep) * hop) / hop) + 1] = False
    runs = _runs(keep, hop)
    # drop isolated scraps (a syllable left over between a cut and a pause)
    def scrap(k, r):
        touches_cut = any(abs(r[0] - cb) < 0.15 for ca, cb in cuts)  # leftovers appear right after a cut
        alone = (k == 0 or r[0] - runs[k - 1][1] >= 0.2) and (k + 1 == len(runs) or runs[k + 1][0] - r[1] >= 0.2)
        return r[1] - r[0] < 0.30 and touches_cut and alone
    runs = [r for k, r in enumerate(runs) if not scrap(k, r)]
    merged = []
    for a, b in runs:
        prev_end = merged[-1][1] if merged else None
        cut_between = prev_end is not None and any(ca < a + 0.02 and cb > prev_end - 0.02 for ca, cb in cuts)
        if merged and a - prev_end <= MAX_PAUSE and not cut_between:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    keeps = [[round(max(0, a - 0.04), 3), round(b + 0.04, 3)] for a, b in merged if b - a >= 0.15]
    return keeps


def _sentences(words, keeps, cuts):
    def kept(w):  # Whisper timings drift near cuts: accept any overlap, with a little slack at keep ends
        if any(ca <= w["start"] and w["end"] <= cb for ca, cb in cuts):
            return False
        return any(w["start"] < b + 0.1 and w["end"] > a + 0.05 for a, b in keeps)
    inside = [w for w in words if kept(w)]
    sents, cur = [], []
    for i, w in enumerate(inside):
        cur.append(w)
        nxt = inside[i + 1] if i + 1 < len(inside) else None
        end = w["text"][-1:] in ".?!" or nxt is None or nxt["start"] - w["end"] >= 0.45
        if end:
            sents.append(cur)
            cur = []
    return sents


def _keyword(sent, caps, used):
    best, score = None, 0
    for w in sent:
        n = w["n"]
        if n in FILLERS or len(n) < 3 or n.isdigit() or n in used:
            continue
        s = len(n) + (6 if n in caps else 0) + (5 if n in CTA_VERBS else 0) + (0 if re.search(r"\d", n) else 1)
        if s > score:
            best, score = w, s
    return best if len(sent) >= 3 else None


def _chunks(sent, kw):
    """Split a sentence into caption chunks: 1-3 words, filler words small, one keyword on tape."""
    out, cur = [], []
    def flush():
        if not cur:
            return
        lead = []
        while cur and cur[0]["n"] in FILLERS and len(cur) > 1:
            lead.append(cur.pop(0))
        lines = []
        if lead:
            lines.append([["f", " ".join(w["text"] for w in lead)]])
        if cur:
            if all(w["n"] in FILLERS for w in cur):
                lines.append([["f", " ".join(w["text"] for w in cur)]])
            elif any(re.search(r"\d", w["n"]) for w in cur) and len(cur) == 1:
                lines.append([["n", cur[0]["text"]]])
            else:
                body = " ".join(w["text"] for w in cur)
                lines.append([["w", body]])
        out.append({"t": round((lead or cur)[0]["start"], 3), "lines": lines})
        cur.clear()
    for i, w in enumerate(sent):
        if kw is not None and w is kw:
            lead = []
            while cur and cur[-1]["n"] in FILLERS and len(lead) < 2:
                lead.insert(0, cur.pop())
            flush()
            lines = ([[["f", " ".join(x["text"] for x in lead)]]] if lead else []) + [[["t", w["text"].strip(",.?!").upper()]]]
            out.append({"t": round((lead or [w])[0]["start"], 3), "lines": lines, "kw": True})
            continue
        gap = w["start"] - cur[-1]["end"] if cur else 0
        body_len = len(" ".join(x["text"] for x in cur + [w] if x["n"] not in FILLERS))
        if cur and (len(cur) >= 3 or body_len > 14 or gap > 0.25):
            flush()
        cur.append(w)
        if w["text"][-1:] in ",":
            if len(cur) >= 2:
                flush()
    flush()
    # a short tail right after a tape keyword sits under it ("STRATEGY / ka hai.")
    merged = []
    for c in out:
        if merged and merged[-1].get("kw") and len(merged[-1]["lines"]) == 1 and len(c["lines"]) == 1 and c["lines"][0][0][0] == "w" \
                and len(c["lines"][0][0][1]) <= 14 and c["t"] - merged[-1]["t"] < 1.2:
            merged[-1]["lines"].append(c["lines"][0])
            merged[-1]["kw"] = False
            continue
        merged.append(c)
    for c in merged:
        c.pop("kw", None)
    return merged


def make_plan(raw: Path, script=None, cta_text=None, card=None, keep_outro=False, log=print) -> dict:
    style = load_style()
    raw = Path(raw)
    cache = (raw.parent.parent / "exports" / ".work" / raw.stem) if raw.parent.name.lower() == "raw" else raw.parent / ".work"
    prompt = prompt_from_script(script)
    words = transcribe(raw, cache, prompt=prompt, log=log)
    if not words:
        raise SystemExit("No speech found in the clip.")
    notes = []
    mask, hop = _speech_mask(raw)
    words = _clean_words(_recover(raw, words, mask, hop, prompt, notes, log), script)
    cuts = _cut_ranges(words, keep_outro, notes)
    keeps = _keeps(mask, hop, words, cuts)
    tl = Timeline(keeps)
    log(f"keeps: {len(keeps)} ranges, {duration(raw):.1f} s -> {tl.total:.1f} s")

    caps = script_caps(script)
    sents = _sentences(words, keeps, cuts)
    captions, used, kw_times = [], set(), []
    for s in sents:
        kw = _keyword(s, caps, used)
        if kw is not None:
            used.add(kw["n"])
            kw_times.append((kw["start"], kw["n"]))
        captions += _chunks(s, kw)

    # chapters: hook / body / CTA
    cta_idx = next((i for i, s in enumerate(sents) if any(w["n"] in CTA_VERBS for w in s)
                    and tl.to_edit(s[0]["start"]) > tl.total * 0.5), None)
    body_idx = next((i for i, s in enumerate(sents) if tl.to_edit(s[0]["start"]) >= tl.total * 0.25), 1)
    def tape_in(i0, i1):
        for c in captions:
            if sents[i0][0]["start"] <= c["t"] < (sents[i1][0]["start"] if i1 < len(sents) else 1e9):
                for line in c["lines"]:
                    if line[0][0] == "t":
                        return line[0][1]
        return None
    slates = [{"at": keeps[0][0], "id": "SH010", "name": "HOOK"}]
    if body_idx < len(sents) and body_idx != cta_idx:
        slates.append({"at": sents[body_idx][0]["start"], "id": "SH020", "name": tape_in(body_idx, cta_idx or len(sents)) or "VALUE"})
    cta = None
    if cta_idx is not None:
        verb_w = next(w for w in sents[cta_idx] if w["n"] in CTA_VERBS)
        slates.append({"at": sents[cta_idx][0]["start"], "id": f"SH0{len(slates)+1}0", "name": CTA_VERBS[verb_w["n"]]})
        cta = {"word": CTA_VERBS[verb_w["n"]], "text": cta_text or "", "start_fraction": style["moves"]["render_queue_cta"]["starts_at_fraction"], "rows": []}
        later = [w for s in sents[cta_idx:] for w in s if w["n"] in CTA_VERBS and w["n"] != verb_w["n"]]
        if later:
            v = later[0]
            sent_v = next(s for s in sents if v in s)
            tail = [w["text"].strip(",.?!") for w in sent_v if w["start"] > v["start"]
                    and w["n"] not in FILLERS and w["n"] not in HINDI_COMMON][-2:]
            cta["rows"].append({"at": v["start"], "text": f"▸ {v['n']} → {' '.join(tail)}".strip()})

    # depth title: strongest early keyword (prefer a script ALL-CAPS word that is not already on tape)
    depth, lock = None, None
    hook_words = [w for w in words if tl.to_edit(w["start"]) < 3.5 and any(a <= w["start"] <= b for a, b in keeps)]
    taped = {line[0][1].lower() for c in captions for line in c["lines"] if line[0][0] == "t"}
    cands = sorted([w for w in hook_words if w["n"] not in FILLERS and len(w["n"]) >= 3 and not w["n"].isdigit()],
                   key=lambda w: (w["n"] in caps and w["n"] not in taped, w["n"] in caps, len(w["n"])), reverse=True)
    if cands:
        dw = cands[0]
        until = dw["start"] if tl.to_edit(dw["start"]) >= 1.2 else next(
            (c["t"] for c in captions if tl.to_edit(c["t"]) >= 2.0), dw["end"] + 1.0)
        depth = {"word": dw["text"].strip(",.?!").upper(), "until": round(until, 3)}
        lock = [0.10, 1.30]

    # zoom: alternate on cuts, punch on keywords, never hold more than ~3 s
    keys = {round(keeps[0][0], 3): 1.0}
    base = 1.0
    for s, _ in keeps[1:]:
        base = 1.12 if base == 1.0 else 1.0
        keys[round(s, 3)] = base
    tape_chunks = [c for c in captions if any(l[0][0] == "t" for l in c["lines"])]
    starts = sorted(c["t"] for c in captions)
    for c in tape_chunks:
        if lock and tl.to_edit(c["t"]) < lock[1] + 0.1:
            continue
        end_of_sent = any(c["t"] <= s[-1]["start"] <= c["t"] + 1.5 and s[-1]["text"][-1:] in ".?!" for s in sents)
        keys[round(c["t"], 3)] = 1.25 if end_of_sent else 1.12
        nxt = next((t for t in starts if t > c["t"] + 0.4), None)
        if nxt is not None:
            keys.setdefault(round(nxt, 3), 1.0)
    cut_keys = {round(s, 3) for s, _ in keeps}
    ordered = []
    for t, z in sorted(keys.items()):  # no two zoom changes within 0.6 s; a cut wins
        if ordered and tl.to_edit(t) - tl.to_edit(ordered[-1][0]) < 0.6:
            if t in cut_keys and ordered[-1][0] not in cut_keys:
                ordered[-1] = (t, z)
            continue
        ordered.append((t, z))
    filled, last_t, last_z = [], None, None
    for t, z in ordered:
        if last_t is not None:
            e0, e1 = tl.to_edit(last_t), tl.to_edit(t)
            mids = [c for c in starts if last_t < c < t and tl.to_edit(c) - e0 > 2.6 and e1 - tl.to_edit(c) > 0.8]
            if e1 - e0 > 3.0 and mids:
                last_z = 1.12 if last_z == 1.0 else 1.0
                filled.append([round(mids[0], 3), last_z])
        filled.append([t, z])
        last_t, last_z = t, z

    plan_card = None
    if card:
        parts = [p.strip() for p in card.split("|") if p.strip()]
        body_caps = [c for c in captions if len(slates) > 1 and c["t"] >= slates[1]["at"]]
        if parts and len(body_caps) >= 3:
            cin = body_caps[1]["t"]
            cout = next((c["t"] for c in body_caps if tl.to_edit(c["t"]) - tl.to_edit(cin) >= 2.4), body_caps[-1]["t"])
            rows = [{"at": round(cin + 0.15 + k * 0.7, 3), "big": r.upper()} for k, r in enumerate(parts[1:4])]
            plan_card = {"in": round(cin, 3), "out": round(cout, 3), "label": slates[1]["name"], "title": parts[0].upper(), "rows": rows}

    return {
        "name": raw.stem,
        "source": str(raw).replace("\\", "/"),
        "brand": "Tracking Marks v1",
        "notes": ["Auto plan. All times are seconds in the RAW clip except lock (edit seconds). Review captions before posting."] + notes,
        "keeps": keeps,
        "captions": captions,
        "slates": slates,
        "depth": depth,
        "lock": lock,
        "zoom": filled,
        "zoom_anchor_y": 0.22,
        "card": plan_card,
        "cta": cta,
        "music": {"bpm": 100, "drop": None},
        "transcript": " ".join(w["text"] for w in words),
    }
