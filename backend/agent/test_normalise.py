"""Tests for LLM-output normalisation (offline)."""
import pytest

from backend.agent.normalise import clean, clean_number


@pytest.mark.parametrize("v", ["null", "None", "N/A", "n/a", "unknown", "not stated",
                               "-", "", "   ", None, "NULL"])
def test_stringy_nulls_become_none(v):
    assert clean(v) is None


@pytest.mark.parametrize("v,expect", [("  Café Aurora ", "Café Aurora"), ("14:00", "14:00"),
                                      (42, "42"), ("0", "0")])
def test_real_values_survive(v, expect):
    assert clean(v) == expect


@pytest.mark.parametrize("v", ["null", "unknown", "about twenty quid", "", None, "nan", "inf"])
def test_clean_number_rejects_non_numbers_and_non_finite(v):
    assert clean_number(v) is None


@pytest.mark.parametrize("v,expect", [("22.90", 22.9), (17, 17.0), ("-5", -5.0), (0, 0.0)])
def test_clean_number_parses_numbers(v, expect):
    """Sign/zero policy is the form layer's call — this only decides "is it a number"."""
    assert clean_number(v) == expect
