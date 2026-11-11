"""Whisper transcription tuned for Hinglish (turbo model, Hindi hint, Latin-script prompt)."""
import hashlib
import json
from pathlib import Path

DEFAULT_PROMPT = ("Hinglish reel, Latin script. Follow karo, share karo, comment karo, reel, video, "
                  "preparation, strategy, Instagram page, daily updates.")


_MODELS = {}


def _model(name):
    if name not in _MODELS:
        import whisper
        _MODELS[name] = whisper.load_model(name)
    return _MODELS[name]


def prompt_from_script(script: str) -> str:
    """Spoken lines only: on-screen text in the prompt makes Whisper hallucinate it into the audio."""
    if not script:
        return DEFAULT_PROMPT
    lines = [l.strip() for l in script.splitlines() if l.strip() and not l.lower().lstrip().startswith(("on screen", "on-screen", "text:", "title:"))]
    return " ".join(lines)[:600] or DEFAULT_PROMPT


def transcribe_window(path: Path, a: float, b: float, prompt: str, model: str = "turbo") -> list:
    """Transcribe one stretch of the clip on its own (recovers speech the full pass skipped)."""
    import whisper
    audio = whisper.load_audio(str(path))[int(max(0, a) * 16000): int(b * 16000)]
    r = _model(model).transcribe(audio, language="hi", initial_prompt=prompt, word_timestamps=True,
                                 condition_on_previous_text=False, fp16=False)
    return [{"word": w["word"].strip(), "start": round(a + w["start"], 3), "end": round(a + w["end"], 3),
             "prob": round(w.get("probability", 1.0), 3)} for s in r["segments"] for w in s.get("words", []) if w["word"].strip()]


def transcribe(path: Path, cache_dir: Path, prompt: str = None, model: str = "turbo", log=print) -> list:
    """Word list [{word, start, end, prob}] for the clip, cached by file size + mtime + prompt."""
    st = path.stat()
    key = hashlib.sha1(f"{path.resolve()}|{st.st_size}|{st.st_mtime}|{prompt}|{model}".encode()).hexdigest()[:12]
    cache = cache_dir / f"words_{key}.json"
    if cache.exists():
        log(f"transcript: cached ({cache.name})")
        return json.loads(cache.read_text(encoding="utf-8"))
    log(f"transcript: whisper {model} (first run downloads the model)")
    r = _model(model).transcribe(str(path), language="hi", initial_prompt=prompt or DEFAULT_PROMPT, word_timestamps=True,
                     condition_on_previous_text=False, fp16=False)
    words = [{"word": w["word"].strip(), "start": round(w["start"], 3), "end": round(w["end"], 3),
              "prob": round(w.get("probability", 1.0), 3)}
             for s in r["segments"] for w in s.get("words", []) if w["word"].strip()]
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(words, ensure_ascii=False, indent=0), encoding="utf-8")
    return words
