"""Hinglish text helpers: Devanagari -> Latin, filler words, and snapping to a script's spelling."""
import difflib
import re

_CONS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n", "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "n",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n", "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m", "य": "y", "र": "r", "ल": "l", "व": "v", "श": "sh",
    "ष": "sh", "स": "s", "ह": "h", "क़": "q", "ख़": "kh", "ग़": "g", "ज़": "z", "ड़": "d", "ढ़": "dh", "फ़": "f",
}
_NUKTA = {"क": "q", "ख": "kh", "ग": "g", "ज": "z", "ड": "d", "ढ": "dh", "फ": "f"}
_VOW = {"अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo", "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au", "ऋ": "ri", "ऑ": "o"}
_MATRA = {"ा": "a", "ि": "i", "ी": "i", "ु": "u", "ू": "u", "े": "e", "ै": "ai", "ो": "o", "ौ": "au", "ृ": "ri", "ॉ": "o", "ॅ": "e"}
_VIRAMA, _NUK, _ANUS, _CHANDRA, _VISARGA = "्", "़", "ं", "ँ", "ः"
_DEV = re.compile(r"[ऀ-ॿ]")


def has_devanagari(s: str) -> bool:
    return bool(_DEV.search(s))


def to_latin(word: str) -> str:
    """Romanize one Devanagari word the way people type Hinglish (apne, isko, karein, saath)."""
    if not has_devanagari(word):
        return word
    units = []  # list of [consonant_or_vowel_text, inherent_a: bool]
    i, w = 0, word
    while i < len(w):
        ch = w[i]
        nxt = w[i + 1] if i + 1 < len(w) else ""
        if ch in _CONS:
            c = _NUKTA.get(ch, _CONS[ch]) if nxt == _NUK else _CONS[ch]
            if nxt == _NUK:
                i += 1
                nxt = w[i + 1] if i + 1 < len(w) else ""
            if nxt == _VIRAMA:
                units.append([c, False]); i += 2; continue
            if nxt in _MATRA:
                units.append([c + _MATRA[nxt], False]); i += 2; continue
            units.append([c, True]); i += 1; continue
        if ch in _VOW:
            units.append([_VOW[ch], False])
        elif ch in (_ANUS, _CHANDRA):
            units.append(["n", False])
        elif ch == _VISARGA:
            units.append(["h", False])
        elif ch in _MATRA:
            units.append([_MATRA[ch], False])
        else:
            units.append([ch, False])
        i += 1
    # schwa deletion: drop the inherent 'a' word-finally and in V C(a) C V contexts
    out = []
    for k, (txt, inherent) in enumerate(units):
        if inherent:
            last = k == len(units) - 1
            before_nasal_end = k == len(units) - 2 and units[-1][0] == "n"
            prev_vowel = k > 0 and units[k - 1][0][-1:] in "aeiou"
            next_cv = k + 1 < len(units) and units[k + 1][0][-1:] in "aeiou" and not units[k + 1][1]
            if last or (prev_vowel and next_cv and k > 0) or (before_nasal_end and k > 0):
                out.append(txt)
            else:
                out.append(txt + "a")
        else:
            out.append(txt)
    s = "".join(out)
    s = re.sub(r"ee(?=[^aeiou]|$)", "i", s) if len(s) > 3 else s
    return s


FILLERS = set("""
hai hain ho tha thi the hoga ko ki ke ka se mein me main pe par aur ya or to toh na nahi bhi hi jo wo vo yeh ye is us
isko usko inko unko apne apna apni aapke aapki aapko aap hum humare hamare hamara tum tumhe kya kaise kab jab
the a an of in on at for and but so it this that is are was were be with you your we our i my me just like very
""".split())
# everyday Hindi words that must never be "corrected" into English or script words
HINDI_COMMON = set("""
sath saath phir fir kar karo karna karni karein karen raha rahe rahi wala wale wali liye lie sab bas khel dekh dekho
dekhiye dekhie aaj kal abhi sirf bahut accha achha theek thik matlab milte milega milenge milta sakte sakta sakti
chahiye chahie hota hoti hote hua hui kuch kuchh badiya badhiya pura puri poora jisko jab tab yahan wahan sun sunkar
bolo bol baat log logon din raat mera meri mere tera tumhara hamara humar hamare naya nayi pehle baad saal
""".split())
DISFLUENCIES = {"um", "umm", "uh", "uhh", "hmm", "hm", "er", "erm", "aa", "aaa"}
LEADING_FILLERS = DISFLUENCIES | {"so", "okay", "ok", "toh", "to", "haan", "achha", "acha", "right", "alright"}
CTA_VERBS = {"follow": "FOLLOW", "share": "SHARE", "comment": "COMMENT", "subscribe": "SUBSCRIBE", "save": "SAVE", "dm": "DM"}
OUTRO = ["milte hain", "milte hai", "milenge phir", "phir milte", "agli video", "next video", "see you", "bye", "thank you",
         "thanks for watching", "chalo"]
OUTRO_LEAD = {"theek", "thik", "thie", "thek", "chalo", "ok", "okay", "to", "toh", "achha"}


# English words that Hinglish reels use a lot; Whisper's Hindi mode often writes them in Devanagari
REEL_VOCAB = """follow share comment subscribe save like page instagram insta reel reels video videos daily updates update
study buddy buddies friends link bio free course class exam exams test topics topic tricks trick shortcuts tips
score marks rank college preparation strategy session sessions mentoring effort efforts realization notes syllabus
toppers topper students student content creator editor edit editing hook prompt guide channel live support
important simple easy best top seat""".split()

_PHON = [("ph", "f"), ("sh", "s"), ("ch", "c"), ("th", "t"), ("dh", "d"), ("bh", "b"), ("kh", "k"), ("gh", "g"),
         ("ck", "k"), ("q", "k"), ("z", "j"), ("v", "w"), ("x", "ks"), ("c", "k")]


def _skeleton(word: str) -> str:
    s = norm(word)
    for a, b in _PHON:
        s = s.replace(a, b)
    s = s[0] + re.sub(r"[aeiouy]", "", s[1:]) if s else s
    return re.sub(r"(.)\1+", r"\1", s)


def snap_sound(word: str, vocab: list, cutoff=0.8, min_skeleton=3) -> str:
    """Match a romanized loanword to an English/script word by its consonant skeleton (pholv -> follow)."""
    core = norm(word)
    if len(core) < 3 or core in FILLERS or core in HINDI_COMMON:
        return word
    tail = re.search(r"[,.?!]+$", word)
    tail = tail.group(0) if tail else ""
    sk = _skeleton(core)
    if len(sk) < min_skeleton:
        return word
    best, score = None, 0.0
    for v in vocab:
        vs = _skeleton(v)
        if not vs or vs[0] != sk[0] or abs(len(vs) - len(sk)) > 2:
            continue
        r = difflib.SequenceMatcher(None, sk, vs).ratio()
        if r > score:
            best, score = v, r
    return (best + tail) if best and score >= cutoff else word


# frequent Whisper spellings -> the way Hinglish is usually typed
HINGLISH_FIX = {"rhe": "rahe", "rhi": "rahi", "dhe": "de", "aapna": "apna", "aapni": "apni", "karayye": "kariye",
                "kariyee": "kariye", "humar": "hamare", "humare": "hamare", "kheel": "khel", "badiya": "badhiya",
                "men": "mein", "dikhiye": "dekhiye", "dekhie": "dekhiye", "chahie": "chahiye", "lie": "liye"}
BIGRAM_FIX = {("insta", "raam"): "Instagram", ("insta", "ram"): "Instagram", ("insta", "gram"): "Instagram"}


def fix_spelling(words: list) -> list:
    """Apply HINGLISH_FIX / BIGRAM_FIX to cleaned word dicts (keeps punctuation and timing)."""
    out, i = [], 0
    while i < len(words):
        w = words[i]
        if i + 1 < len(words) and (w["n"], words[i + 1]["n"]) in BIGRAM_FIX:
            nxt = words[i + 1]
            text = BIGRAM_FIX[(w["n"], nxt["n"])] + nxt["text"][len(nxt["text"].rstrip(",.?!")):]
            out.append({**w, "text": text, "n": norm(text), "end": nxt["end"]})
            i += 2
            continue
        if w["n"] in HINGLISH_FIX:
            fixed = HINGLISH_FIX[w["n"]]
            if w["text"][:1].isupper():
                fixed = fixed.capitalize()
            w = {**w, "text": fixed + w["text"][len(w["text"].rstrip(",.?!")):], "n": fixed}
        out.append(w)
        i += 1
    return out


def norm(word: str) -> str:
    return re.sub(r"[^\w]", "", word.lower())


def snap(word: str, vocab: dict, cutoff=0.82) -> str:
    """Replace a word by the script's spelling when it is a close match (keeps trailing punctuation)."""
    core = norm(word)
    if not core or not vocab or core in HINDI_COMMON or core in FILLERS:
        return word
    if len(core) < 4:
        return (vocab[core] + word[len(word.rstrip(',.?!')):]) if core in vocab else word
    tail = re.search(r"[,.?!]+$", word)
    tail = tail.group(0) if tail else ""
    if core in vocab:
        return vocab[core] + tail
    m = difflib.get_close_matches(core, list(vocab), n=1, cutoff=cutoff)
    return (vocab[m[0]] + tail) if m else word


def script_vocab(script: str) -> dict:
    vocab = {}
    for tok in re.findall(r"[A-Za-z0-9][A-Za-z0-9'+-]*", script or ""):
        vocab.setdefault(norm(tok), tok)
    return vocab


def script_caps(script: str) -> set:
    """ALL-CAPS tokens in the script (KCET, COMEDK, PYQ) are strong keyword candidates."""
    return {norm(t) for t in re.findall(r"\b[A-Z][A-Z0-9]{1,}\b", script or "")}
