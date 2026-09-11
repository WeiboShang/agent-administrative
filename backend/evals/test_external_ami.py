"""Tests for the AMI external harness's pure helpers (offline — no dataset, no LLM)."""
from backend.evals.external_ami import MAX_TURNS, _transcript


def test_transcript_drops_the_qmsum_query_line():
    ex = {"input": "How did the team evaluate cost?\nPM: Let's begin.\nMarketing: Sure."}
    out = _transcript(ex)
    assert "How did the team" not in out          # the query is a QMSum artifact
    assert out == "PM: Let's begin.\nMarketing: Sure."


def test_transcript_truncates_to_wf1s_evaluated_regime():
    turns = "\n".join(f"Speaker{i}: line {i}" for i in range(200))
    out = _transcript({"input": f"query?\n{turns}"})
    assert len(out.split("\n")) == MAX_TURNS


def test_transcript_drops_blank_lines():
    out = _transcript({"input": "q?\nPM: a.\n\n\nMarketing: b.\n"})
    assert out == "PM: a.\nMarketing: b."
