import pytest

from backend.evals.run_v342_formal import run


def test_v342_formal_runner_rejects_later_source_versions():
    with pytest.raises(RuntimeError, match="sealed V3.4.2 source hash mismatch"):
        run(limit_per_workflow=1)
