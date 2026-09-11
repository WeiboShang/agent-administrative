import pytest

from backend.evals.run_v343_formal import run


def test_v343_formal_runner_rejects_later_source_versions():
    # V3.4.3 remains replayable from its sealed commit.  Once V3.5 source files exist,
    # its source hash must fail rather than presenting current code as the historical run.
    with pytest.raises(RuntimeError, match="sealed V3.4.3 source hash mismatch"):
        run(limit_per_workflow=1)
