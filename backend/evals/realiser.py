"""LLM realiser — paraphrase template-rendered eval cases into varied natural text.

data_strategy.md §3.2 step 2: the gold is fixed *before* realisation, an LLM only varies
the surface form, and a deterministic **back-check** verifies the facts survived (person
names, the date expression verbatim, HH:MM times). A failed rewrite falls back to the
template text (recorded in ``meta.realised``), so the dataset never silently loses gold
alignment.

The realiser model must be DIFFERENT from every evaluated generator (no model writes its
own exam): default is Gemini (free tier, separate quota from Groq). Realised datasets are
FROZEN to data/eval_datasets/*.jsonl by ``realise_datasets`` (LLM paraphrase is not
deterministic, so final numbers must run on a frozen file, not a fresh realisation).
"""
import json
import os
import time
from dataclasses import asdict
from typing import Callable, Optional

from ..fixtures import org
from .scheduling_data import Case
from .triage_data import ThreadCase

ModelFn = Callable[[str], str]        # prompt -> raw text

DATASETS_DIR = "data/eval_datasets"

REALISE_PROMPT = """Rewrite the following workplace message so it reads naturally and \
differently (vary the wording, sentence order and tone — like a real colleague typing).

STRICT rules — the rewrite MUST:
- keep every person name exactly as written
- keep the date expression "{date_phrase}" EXACTLY as written (do not reword or resolve it)
- keep any clock times exactly as written (HH:MM 24h format)
- keep all factual details; add no new facts, dates, times or people
- be a single message of 1–4 sentences

Message:
{text}

Rewritten message only — no quotes, no explanation."""


def facts_survive(text: str, *, required: list[str]) -> bool:
    """Every required literal (names / date phrase / times) appears in the rewrite."""
    low = text.lower()
    return all(r.lower() in low for r in required if r)


# Meta-output markers: a model answering ABOUT the rewrite instead of WITH it. Found in
# the wild (Qwen emitted "**Original Message:** …" bullets that passed the facts check
# because they QUOTED the original — hence the shape checks below).
_META_MARKERS = ("**", "original message", "rewritten message", "rewrite:")


def is_clean_rewrite(out: str, original: str) -> bool:
    """Shape check: a single-paragraph rewrite, not meta-output or a quote-through."""
    if not out or "\n" in out:
        return False
    if out.lstrip().startswith(("-", "*", "•", "#")):   # bullet/heading = meta-output
        return False
    low = out.lower()
    if any(m in low for m in _META_MARKERS):
        return False
    if len(out) > 2.5 * len(original) + 60:            # bloated → probably meta-output
        return False
    if original.strip().lower() in low:                 # quoting the original ≠ rewriting
        return False
    return True


def realise_text(text: str, model_fn: ModelFn, *, date_phrase: Optional[str],
                 required: list[str], retries: int = 1) -> tuple[str, bool]:
    """Paraphrase ``text``; return ``(new_text, realised)`` — falls back on check failure."""
    prompt = REALISE_PROMPT.format(date_phrase=date_phrase or "(none)", text=text)
    for _ in range(retries + 1):
        out = model_fn(prompt).strip().strip('"')
        if is_clean_rewrite(out, text) and facts_survive(out, required=required):
            return out, True
    return text, False


# ── WF2 scheduling cases ─────────────────────────────────────────────────────────────

def _first_names(user_ids: list[str]) -> list[str]:
    names = []
    for uid in user_ids:
        p = org.find_person(uid)
        if p:
            names.append(p.name.split()[0])
    return names


def realise_sched_case(case: Case, model_fn: ModelFn) -> Case:
    """Realise one WF2 case. ``revision`` keeps its dialogue structure (multi-turn
    supersession is the point of that tier) — it is left as-template."""
    if case.meta["tier"] == "revision":
        case.meta["realised"] = False
        return case
    gold, meta = case.gold, dict(case.meta)
    required = _first_names(gold["participants"])
    if meta.get("date_phrase") and gold["intent"] != "none":
        required.append(meta["date_phrase"])
    if gold.get("time"):
        required.append(gold["time"])
    text, ok = realise_text(case.input_text, model_fn,
                            date_phrase=meta.get("date_phrase"), required=required)
    meta["realised"] = ok
    return Case(text, gold, meta)


# ── WF1 triage threads ───────────────────────────────────────────────────────────────

# Cues that mark a realisable line inside a triage thread: the action lines (meeting / expense)
# and the borderline social invitations of the *ambiguous* tier. Kept multi-word so they
# never match the varied noise pool. Must cover every phrasing in triage_data._AMBIGUOUS, or
# those cases silently fall back to template and the realised tier loses its variety.
_TRIAGE_ACTION_CUES = ("can we sync on", "please reimburse it")
_TRIAGE_SOCIAL_CUES = (
    "catch up", "catching up", "grab a coffee", "get coffee", "over coffee",
    "grab lunch", "team lunch", "over lunch", "do lunch", "grab a bite",
    "get together", "hang out", "meet up", "team social", "social for the team",
    "team night out", "night out", "for drinks",
)


def realise_thread_case(case: ThreadCase, model_fn: ModelFn) -> ThreadCase:
    """Realise the *action/ambiguous* lines inside a thread (noise lines are already a
    varied 52-line pool). A line keeps its ``Speaker:`` prefix; facts are back-checked."""
    gold, meta = case.gold, dict(case.meta)
    lines = case.raw_text.split("\n")
    realised_any = False
    for i, line in enumerate(lines):
        if ":" not in line:
            continue
        speaker, _, body = line.partition(":")
        low = body.lower()
        is_action = (any(c in low for c in _TRIAGE_ACTION_CUES)
                     or any(c in low for c in _TRIAGE_SOCIAL_CUES))
        if not is_action:
            continue
        facts = meta.get("facts") or {}
        required = [facts.get("weekday"), facts.get("time"), *(facts.get("names") or [])]
        required = [r for r in required if r and r in body]   # only facts this line holds
        new_body, ok = realise_text(body.strip(), model_fn, date_phrase=None,
                                    required=required)
        if ok:
            lines[i] = f"{speaker}: {new_body}"
            realised_any = True
    meta["realised"] = realised_any
    return ThreadCase("\n".join(lines), gold, meta)


# ── freeze / load ────────────────────────────────────────────────────────────────────

def write_cases(cases: list, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps(asdict(c), ensure_ascii=False) + "\n")


def load_sched_cases(path: str) -> list[Case]:
    with open(path, encoding="utf-8") as f:
        return [Case(**json.loads(line)) for line in f if line.strip()]


def load_thread_cases(path: str) -> list[ThreadCase]:
    with open(path, encoding="utf-8") as f:
        return [ThreadCase(**json.loads(line)) for line in f if line.strip()]


def make_gemini_realiser(model: str = "gemini-2.5-flash", pause_s: float = 2.0) -> ModelFn:
    """Gemini-backed realiser (not an evaluated generator → no circularity).
    NOTE: the Gemini free tier is only ~20 requests/day/model — fine for spot checks,
    too small for a full freeze; prefer :func:`make_groq_realiser` for batches."""
    from langchain_core.messages import HumanMessage
    from langchain_google_genai import ChatGoogleGenerativeAI

    llm = ChatGoogleGenerativeAI(model=model, google_api_key=os.environ["GOOGLE_API_KEY"],
                                 temperature=0.8)   # variety is the goal

    def fn(prompt: str) -> str:
        time.sleep(pause_s)
        return llm.invoke([HumanMessage(content=prompt)]).content

    return fn


def make_groq_realiser(model: str = "qwen/qwen3.6-27b", pause_s: float = 1.0) -> ModelFn:
    """Groq-backed realiser on a model that is NOT an evaluated generator (default:
    Qwen, Alibaba family — separate per-model Groq quota; no circularity with the
    evaluated Llama/gpt-oss generators). Strips any ``<think>…</think>`` reasoning
    and rides out 429s (sleeps the provider's suggested wait)."""
    import re as _re

    from langchain_core.messages import HumanMessage
    from langchain_groq import ChatGroq

    llm = ChatGroq(model=model, api_key=os.environ["GROQ_API_KEY"], temperature=0.8)

    def fn(prompt: str) -> str:
        time.sleep(pause_s)
        for attempt in range(8):
            try:
                out = llm.invoke([HumanMessage(content=prompt)]).content
                return _re.sub(r"<think>.*?</think>", "", out, flags=_re.S).strip()
            except Exception as e:  # noqa: BLE001
                s = str(e)
                if "429" not in s or attempt == 7:
                    raise
                m = _re.search(r"try again in (?:(\d+)m)?([0-9.]+)s", s)
                wait = (min(int(m.group(1) or 0) * 60 + float(m.group(2)) + 2, 900)
                        if m else 20.0)
                print(f"    realiser 429 — waiting {wait:.0f}s", flush=True)
                time.sleep(wait)
        return ""

    return fn
