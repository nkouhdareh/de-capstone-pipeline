"""TR-38: hand-verified worked example for the disproportionality metrics.

These pure-Python formulas mirror dbt/macros/signal_metrics.sql (TR-20..23). The
expected numbers are the same ones committed to dbt/seeds/signal_worked_example.csv,
so three artefacts agree on one truth: this test, the seed, and the dbt macro test
(dbt/tests/assert_signal_worked_example.sql). If any formula drifts, one of them
fails.
"""
import csv
import math
from pathlib import Path

import pytest

SEED = Path(__file__).resolve().parents[1] / "de_capstone" / "seeds" / "signal_worked_example.csv"

# thresholds — mirror dbt_project.yml vars (TR-25)
MIN_CASES, MIN_PRR, MIN_CHI2 = 3, 2.0, 4.0


def prr(a, b, c, d):
    return (a / (a + b)) / (c / (c + d))


def ror(a, b, c, d):
    return (a * d) / (b * c)


def ror_ci_lower(a, b, c, d):
    return math.exp(math.log(ror(a, b, c, d)) - 1.96 * math.sqrt(1/a + 1/b + 1/c + 1/d))


def chi2_yates(a, b, c, d):
    n = a + b + c + d
    return n * (abs(a * d - b * c) - n / 2) ** 2 / ((a + b) * (c + d) * (a + c) * (b + d))


def is_signal(a, b, c, d):
    return a >= MIN_CASES and prr(a, b, c, d) >= MIN_PRR and chi2_yates(a, b, c, d) >= MIN_CHI2


def _seed_rows():
    with open(SEED, newline="") as f:
        return list(csv.DictReader(f))


def test_primary_signal_example():
    # a=20, b=80, c=100, d=9800 — a strong, clearly-flagged signal
    a, b, c, d = 20, 80, 100, 9800
    assert prr(a, b, c, d) == pytest.approx(19.8, abs=1e-6)
    assert ror(a, b, c, d) == pytest.approx(24.5, abs=1e-6)
    assert ror_ci_lower(a, b, c, d) == pytest.approx(14.447996, abs=1e-5)
    assert chi2_yates(a, b, c, d) == pytest.approx(285.317752, abs=1e-4)
    assert is_signal(a, b, c, d) is True


@pytest.mark.parametrize("row", _seed_rows(), ids=lambda r: f"{r['drug']}/{r['reaction']}")
def test_matches_seed_fixture(row):
    a, b, c, d = (int(row[k]) for k in "abcd")
    assert prr(a, b, c, d) == pytest.approx(float(row["expected_prr"]), abs=1e-4)
    assert ror(a, b, c, d) == pytest.approx(float(row["expected_ror"]), abs=1e-4)
    assert ror_ci_lower(a, b, c, d) == pytest.approx(float(row["expected_ror_ci_lower"]), abs=1e-4)
    assert chi2_yates(a, b, c, d) == pytest.approx(float(row["expected_chi2_yates"]), abs=1e-3)
    assert is_signal(a, b, c, d) == (row["expected_is_signal"].strip().lower() == "true")
