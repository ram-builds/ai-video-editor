# ai-video-editor

AI powered video editing app. Turns a raw talking-head clip into a branded 9:16 reel in the
**Tracking Marks** style (`brand/style.json`): pauses and repeats cut, flush-left Hinglish captions with
one cobalt keyword per sentence, a depth title behind you in the hook, shot slates, a scan-wipe card,
a render-queue call to action, an original music bed, brand sound cues and a −14 LUFS master.

## Setup

```bash
pip install -r requirements.txt
```

FFmpeg 7.1 or newer must be on PATH. The first run downloads Whisper `turbo` (~1.5 GB) and the
`u2net_human_seg` person model (~170 MB).

## One command

```bash
python -m pipeline reel "E:/Documents/ai video editor/raw/REEL2.mp4" --script script.txt --cta-text "for KCET + COMEDK"
```

The reel lands in `<project>/exports/REEL2_tracking-marks.mp4` when the clip sits in `<project>/raw`.
Working files go to `<project>/exports/.work/REEL2/`, including `sheet.jpg`, a 16-frame contact sheet.

## Review first (recommended)

```bash
python -m pipeline plan   raw/REEL2.mp4 --script script.txt --card "MILEGA | Mentoring | Realizations | PYQ tricks"
python -m pipeline render exports/REEL2.plan.json
```

`plan` writes an editable JSON plan. Open it, fix any misheard caption words, and render. The `notes` list
says what was cut and why.

| Option | What it does |
|---|---|
| `--script FILE` | What you meant to say. Its spoken lines steer Whisper; its spellings and ALL-CAPS words fix captions and pick keywords. Lines starting with `On screen:` are ignored for transcription. |
| `--cta-text "…"` | Text beside the CTA word in the render-queue card. |
| `--card "TITLE \| ROW \| ROW \| ROW"` | Adds the full-screen scan-wipe card in the middle chapter. |
| `--keep-outro` | Keeps sign-offs like "milte hain" after the CTA (cut by default). |

## What the planner does on its own

- Cuts every pause over 0.3 s, a leading "So/um", disfluencies, false starts ("aapko follow, aapko chahiye"),
  speech Whisper can't make out (after a second, focused attempt), and a sign-off after the CTA.
- Romanizes Devanagari into Hinglish and matches loanwords by sound ("pholv" → follow, "dili apdets" → daily updates).
- Chunks captions 1–3 words, filler words small, one tape keyword per sentence (script ALL-CAPS words and CTA verbs win).
- Picks the depth title, three chapter slates, punch-in zooms (never more than ~3 s without a change) and the CTA.

Still worth a human look: words Whisper mishears in a noisy room, and anything in `notes` marked as cut.

## Plan format

All times are seconds in the **raw clip**, except `lock` (seconds of the finished reel).

```jsonc
{
  "name": "REEL1", "source": "E:/…/raw/REEL1.MP4",
  "keeps":    [[0.82, 5.52], …],                       // ranges of the raw clip to keep, in order
  "captions": [{"t": 3.48, "lines": [[["f","ya"]], [["t","COMEDK"]]]}, …],
              // line runs: w = caption word, f = filler (small), t = cobalt tape keyword, n = number (mono + cross)
  "slates":   [{"at": 0.82, "id": "SH010", "name": "HOOK"}, …],
  "depth":    {"word": "KCET", "until": 2.98},        // big word behind you, shown until `until`
  "lock":     [0.10, 1.30],                            // tracking crosses on your head
  "zoom":     [[2.18, 1.12], [7.20, 1.25], …],         // increases snap in, decreases ease out over 8 frames
  "card":     {"in": 10.4, "out": 12.8, "label": "…", "title": "MILEGA", "rows": [{"at": 10.55, "big": "MENTORING", "small": "sessions"}]},
  "cta":      {"word": "FOLLOW", "text": "for KCET + COMEDK", "start_fraction": 0.75, "rows": [{"at": 25.92, "text": "▸ share → study buddies"}]},
  "music":    {"bpm": 100, "drop": 6.00}               // beat drops at this raw time (default: first cut after 2.5 s)
}
```

`reels/REEL1.plan.json` is the hand-tuned plan for the first reel; `python -m pipeline render reels/REEL1.plan.json`
reproduces it.

## Layout

| Path | Purpose |
|---|---|
| `brand/style.json` | Tracking Marks tokens: colors, type sizes, safe zones, pacing, grade, audio targets |
| `brand/fonts/` | Static instances of Archivo and JetBrains Mono used for captions (OFL) |
| `pipeline/planner.py` | Transcript → plan (cuts, captions, keywords, slates, zoom, card, CTA) |
| `pipeline/graphics.py` | Plan → ASS motion graphics rendered by libass |
| `pipeline/render.py` | Cut/zoom/grade, person matte, composite, export |
| `pipeline/sound.py` | Music bed, sound cues, voice chain, ducking, loudness master |
| `pipeline/hinglish.py` | Devanagari → Hinglish, filler words, spelling fixes |
| `reels/` | Saved plans and scripts |
