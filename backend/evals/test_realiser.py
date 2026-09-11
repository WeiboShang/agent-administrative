"""Tests for the LLM realiser + back-check. Offline (stub model_fn, no LLM)."""
import os

from backend.evals.realiser import (
    facts_survive,
    load_sched_cases,
    load_thread_cases,
    realise_sched_case,
    realise_text,
    realise_thread_case,
    write_cases,
)
from backend.evals.scheduling_data import make_case
from backend.evals.triage_data import make_position_case, make_thread_case


def _echo_stub(prompt: str) -> str:
    """Pretend-paraphrase: reword the original (keeps all facts, changes the surface)."""
    text = prompt.split("Message:\n", 1)[1].rsplit("\n\nRewritten", 1)[0]
    return (text.replace("Hi ", "Hey ").replace("Can we", "Could we")
                .replace("can we", "could we"))


def _lossy_stub(prompt: str) -> str:
    return "Let's meet sometime!"          # drops names/dates/times → must fall back


def _meta_stub(prompt: str) -> str:
    """The failure mode found live: quotes the original inside meta-output — the facts
    check alone passes, the shape check must reject it."""
    text = prompt.split("Message:\n", 1)[1].rsplit("\n\nRewritten", 1)[0]
    return f'- **Original Message:** "{text}"'


def test_realise_text_keeps_facts_or_falls_back():
    text = "Hi Bob, can we meet about the launch plan on next Tuesday at 14:00?"
    out, ok = realise_text(text, _echo_stub, date_phrase="next Tuesday",
                           required=["Bob", "next Tuesday", "14:00"])
    assert ok and out.startswith("Hey Bob") and out != text
    out, ok = realise_text(text, _lossy_stub, date_phrase="next Tuesday",
                           required=["Bob", "next Tuesday", "14:00"])
    assert not ok and out == text           # fallback = template text unchanged


def test_meta_output_and_quote_through_are_rejected():
    text = "Hi Bob, can we meet about the launch plan on next Tuesday at 14:00?"
    out, ok = realise_text(text, _meta_stub, date_phrase="next Tuesday",
                           required=["Bob", "next Tuesday", "14:00"])
    assert not ok and out == text           # facts survive, but shape check rejects
    from backend.evals.realiser import is_clean_rewrite
    assert not is_clean_rewrite("line one\nline two", text)      # multiline
    assert not is_clean_rewrite("**Rewritten:** hey Bob", text)  # markdown meta
    assert not is_clean_rewrite("FYI — " + text, text)           # quote-through


def test_facts_survive_is_case_insensitive():
    assert facts_survive("BOB and CHEN at 14:00", required=["Bob", "14:00"])
    assert not facts_survive("someone at some point", required=["Bob"])


def test_realise_sched_case_marks_meta_and_keeps_gold():
    c = make_case("clean", seed=3)
    r = realise_sched_case(c, _echo_stub)
    assert r.meta["realised"] is True
    assert r.gold == c.gold                 # gold untouched by realisation
    assert r.input_text != c.input_text


def test_revision_tier_is_left_as_template():
    c = make_case("revision", seed=3)
    r = realise_sched_case(c, _echo_stub)
    assert r.meta["realised"] is False and r.input_text == c.input_text


def test_realise_thread_case_rewrites_only_action_lines():
    c = make_position_case(10, "middle", seed=4)
    r = realise_thread_case(c, _echo_stub)
    assert r.meta["realised"] is True
    changed = [i for i, (a, b) in enumerate(zip(c.raw_text.split("\n"),
                                                r.raw_text.split("\n"))) if a != b]
    assert changed == [c.meta["action_index"]]   # exactly the buried action line


def test_write_and_load_roundtrip(tmp_path):
    sched = [realise_sched_case(make_case("clean", seed=i), _echo_stub) for i in range(2)]
    p = os.path.join(tmp_path, "s.jsonl")
    write_cases(sched, p)
    back = load_sched_cases(p)
    assert [c.gold for c in back] == [c.gold for c in sched]

    threads = [realise_thread_case(make_thread_case("meeting", i), _echo_stub)
               for i in range(2)]
    p = os.path.join(tmp_path, "t.jsonl")
    write_cases(threads, p)
    back = load_thread_cases(p)
    assert [c.gold for c in back] == [c.gold for c in threads]
