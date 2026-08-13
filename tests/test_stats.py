import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.common.stats import summarize, coefficient_of_variation


def test_summarize_basic():
    lat = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    s = summarize(lat)
    assert s.n == 10
    assert s.min_ms == 10
    assert s.max_ms == 100
    assert abs(s.mean_ms - 55) < 1e-9
    # p50 of 1..100 by 10s (numpy linear interpolation) should sit around 55
    assert 45 <= s.p50_ms <= 65
    assert s.p95_ms >= s.p50_ms


def test_summarize_empty():
    s = summarize([])
    assert s.n == 0
    assert s.mean_ms == 0


def test_coefficient_of_variation():
    assert coefficient_of_variation([]) == 0.0
    cv_low = coefficient_of_variation([100, 101, 99, 100])
    cv_high = coefficient_of_variation([10, 500, 5, 900])
    assert cv_low < cv_high


if __name__ == "__main__":
    test_summarize_basic()
    test_summarize_empty()
    test_coefficient_of_variation()
    print("All tests passed.")
