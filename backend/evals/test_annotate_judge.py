"""Tests for the judge-label annotator (offline — no terminal, no model)."""
import json

from backend.evals import annotate_judge as ann


def _rows():
    return [
        {"i": 0, "source": "a\nb", "output": "o", "human_supported": None,
         "judge_g": True, "claims_g": [{"claim": "c", "supported": False}],
         "judge_h": False, "claims_h": [{"claim": "c", "supported": True}]},
        {"i": 1, "source": "x", "output": "y", "human_supported": True,
         "judge_g": False, "claims_g": [], "judge_h": False, "claims_h": []},
    ]


def test_judge_names_are_discovered_from_the_columns():
    assert ann._judge_names(_rows()) == ["g", "h"]


def test_save_is_atomic_and_round_trips(tmp_path, monkeypatch):
    path = tmp_path / "labels.jsonl"
    monkeypatch.setattr(ann, "LABEL_PATH", str(path))
    rows = _rows()
    rows[0]["human_supported"] = False
    ann._save(rows)
    assert not (tmp_path / "labels.jsonl.tmp").exists()      # temp file cleaned up
    back = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [r["human_supported"] for r in back] == [False, True]


def test_render_shows_the_thread_summary_and_a_disagreement(capsys, monkeypatch):
    monkeypatch.setattr(ann.os, "system", lambda *_a: None)
    ann._render(_rows()[0], ["g", "h"], 1, 2)
    out = capsys.readouterr().out
    assert "THREAD" in out and "SUMMARY" in out
    assert "DISAGREED" in out          # judge_g=True vs judge_h=False
    assert "UNSUPPORTED" in out        # g marked the claim unsupported


def test_render_is_quiet_when_the_judges_agree(capsys, monkeypatch):
    monkeypatch.setattr(ann.os, "system", lambda *_a: None)
    ann._render(_rows()[1], ["g", "h"], 1, 2)
    assert "DISAGREED" not in capsys.readouterr().out
