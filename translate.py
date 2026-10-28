"""Übersetzt fremdsprachige Meldungen ins Deutsche, kostenlos und ohne Online-Dienst.

Nutzt die freien OPUS-MT-Modelle (Helsinki-NLP, CC-BY 4.0) in der CTranslate2-Umsetzung von Hugging Face. Die Modelle
(je etwa 150 MB) werden beim ersten Lauf geladen und zwischengespeichert. Fehlt etwas, bleiben die Originale stehen.
Unterstützt: Englisch (direkt) sowie Spanisch, Französisch, Italienisch, Portugiesisch (über Englisch).
"""
import hashlib
import json
import os
import re
import time
from pathlib import Path

from net import fetch

CACHE_DIR = Path(os.environ.get("MEGO_CACHE") or Path.home() / ".cache" / "mego")
MODELS = {"en-de": "michaelfeil/ct2fast-opus-mt-en-de", "romance-en": "michaelfeil/ct2fast-opus-mt-ROMANCE-en"}
PIPELINES = {"en": ["en-de"], "es": ["romance-en", "en-de"], "fr": ["romance-en", "en-de"],
             "it": ["romance-en", "en-de"], "pt": ["romance-en", "en-de"]}
NAMES = {"en": "Englisch", "es": "Spanisch", "fr": "Französisch", "it": "Italienisch", "pt": "Portugiesisch",
         "nl": "Niederländisch", "tr": "Türkisch", "ru": "Russisch", "ar": "Arabisch", "cjk": "Ostasiatisch"}

STOP = {
    "de": ("der die das den dem des ein eine einen einer und mit von für auf ist im zu nicht sich auch bei nach über wird sind "
           "hat dass wie nur noch aus als um an am zum zur vom beim bis gegen vor unter zwischen wegen oder aber wegen sein "
           "werden wurde nun jetzt mehr schon wieder dann diese dieser einem").split(),
    "en": "the of and to in for on with is are at as by from that this it be was has have will after over new says".split(),
    "es": "el los las del una para por con que se su al más como pero sus entre sobre tras desde sin hasta".split(),
    "fr": "les des une dans pour est au aux sur avec qui que par plus pas il elle cette ces mais".split(),
    "it": "il gli della per che sono con una nel nella più anche dopo come questo sulla".split(),
    "pt": "os uma não com para que dos das mais como pelo pela são ao".split(),
    "nl": "het een van voor met niet zijn naar ook maar bij door".split(),
    "tr": "ve bir bu için ile da de olarak daha çok gibi".split(),
}
STOP = {k: set(v) for k, v in STOP.items()}


def detect(text, default="de"):
    """Grobe Spracherkennung für kurze Überschriften; im Zweifel gilt die Sprache des Feeds."""
    if re.search(r"[Ѐ-ӿ]", text):
        return "ru"
    if re.search(r"[؀-ۿ]", text):
        return "ar"
    if re.search(r"[一-鿿぀-ヿ가-힯]", text):
        return "cjk"
    words = re.findall(r"[a-zA-ZÀ-ÿĀ-ſ]+", text.lower())
    scores = {lang: sum(1 for w in words if w in sw) for lang, sw in STOP.items()}
    for ch, lang in (("ñ", "es"), ("¿", "es"), ("¡", "es"), ("ß", "de"), ("ã", "pt"), ("õ", "pt"), ("ı", "tr"), ("ş", "tr")):
        if ch in text.lower():
            scores[lang] += 2
    ranked = sorted(scores.values(), reverse=True)
    best = max(scores, key=scores.get)
    return best if ranked[0] >= 1 and ranked[0] > ranked[1] else default


# ---------------------------------------------------------------- Modelle

def ensure_model(key):
    folder = CACHE_DIR / "models" / key
    if (folder / ".ok").exists():
        return folder
    repo = MODELS[key]
    import json as _json
    files = [s["rfilename"] for s in _json.loads(fetch(f"https://huggingface.co/api/models/{repo}", 30))["siblings"]]
    wanted = [f for f in files if re.fullmatch(r"model\.bin|config\.json|shared_vocabulary\.(txt|json)|source\.spm|target\.spm", f)]
    folder.mkdir(parents=True, exist_ok=True)
    for name in wanted:
        (folder / name).write_bytes(fetch(f"https://huggingface.co/{repo}/resolve/main/{name}", 600, retries=2))
    (folder / ".ok").write_text("ok")
    return folder


class Engine:
    def __init__(self, folder):
        import ctranslate2
        import sentencepiece as spm
        self.t = ctranslate2.Translator(str(folder), device="cpu", compute_type="int8", intra_threads=os.cpu_count() or 2)
        self.src = spm.SentencePieceProcessor(str(folder / "source.spm"))
        self.tgt = spm.SentencePieceProcessor(str(folder / "target.spm"))

    def run(self, texts):
        batches = [self.src.encode(t, out_type=str) + ["</s>"] for t in texts]
        results = self.t.translate_batch(batches, beam_size=2, max_decoding_length=200, max_batch_size=16)
        return [self.tgt.decode(r.hypotheses[0]).strip() for r in results]


# ---------------------------------------------------------------- Anwendung

def apply(stories, budget_s=150):
    """Setzt an jeder Meldung title_de, summary_de und src_lang. Liefert einen Hinweistext oder None."""
    started = time.time()
    cache_file = CACHE_DIR / "translations.json"
    try:
        cache = json.loads(cache_file.read_text(encoding="utf-8"))
    except Exception:
        cache = {}
    key = lambda lang, text: hashlib.sha1(f"{lang}|{text}".encode()).hexdigest()[:20]

    jobs, wanted = {}, []  # lang -> {text}
    for s in stories:
        lang = detect(s["title"], s.get("lang", "de"))
        if lang != "de":
            s["src_lang"] = lang
        for field in ("title", "summary"):
            text = s.get(field) or ""
            l = lang if field == "title" else detect(text, lang)
            if text and l in PIPELINES:
                wanted.append((s, field, l, text))
                if key(l, text) not in cache:
                    jobs.setdefault(l, set()).add(text)

    note, engines = None, {}
    try:
        for lang, texts in jobs.items():
            ordered = sorted(texts, key=len)
            pipeline = PIPELINES[lang]
            for i in range(0, len(ordered), 24):
                if time.time() - started > budget_s:
                    note = "Übersetzung unvollständig (Zeitlimit)"
                    raise TimeoutError
                chunk = ordered[i: i + 24]
                current = chunk
                for model in pipeline:
                    if model not in engines:
                        engines[model] = Engine(ensure_model(model))
                    current = engines[model].run(current)
                for original, translated in zip(chunk, current):
                    cache[key(lang, original)] = translated
    except TimeoutError:
        pass
    except Exception as e:
        note = f"Übersetzung nicht möglich ({type(e).__name__}: {str(e)[:80]})"

    done = 0
    for s, field, lang, text in wanted:
        out = cache.get(key(lang, text))
        if out and out != text:
            s[field + "_de"] = out
            done += field == "title"
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        keep = dict(list(cache.items())[-6000:])
        cache_file.write_text(json.dumps(keep, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    apply.count = done
    return note
