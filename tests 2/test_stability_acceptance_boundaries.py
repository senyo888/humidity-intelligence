"""Hand-calculated receiving fixtures for accepted Stability formula boundaries."""

import pytest

from test_stability_score import _load_stability_module, _sample


@pytest.mark.parametrize(
    "large_changes,expected_volatility,expected_raw",
    [(21, 0.9167, 98.75), (22, 0.5, 92.5)],
)
def test_nearest_rank_p95_changes_at_the_410th_of_431_deltas(
    large_changes, expected_volatility, expected_raw,
):
    # 432 observations give 431 consecutive changes. Nearest-rank p95 is
    # position ceil(.95 * 431) = 410. With 21 six-point changes, that position
    # is still one point; with 22 it is six points. The volatility deductions
    # from an otherwise perfect score are 15 / 12 = 1.25 and 15 * 6 / 12 = 7.5.
    mod = _load_stability_module()
    humidity = 50.0
    samples = []
    for index in range(432):
        if index:
            change = 6.0 if index <= large_changes else 1.0
            humidity += change if index % 2 else -change
        samples.append(_sample(
            mod, index, house_humidity=humidity, target_low=40.0,
            target_high=60.0, room_or_level_humidity_spread=0.0,
        ))

    result = mod.evaluate_stability_window(samples)

    assert result["availability"] == "available"
    assert result["component_coverage"]["volatility"]["valid_samples"] == 431
    assert result["subscores"]["volatility_score"] == expected_volatility
    assert result["score"]["raw_score"] == expected_raw
    assert result["caps"]["classification_cap_reasons"] == []


@pytest.mark.parametrize("omit_middle_observations", [False, True])
def test_closed_excursions_use_elapsed_time_and_median_despite_missing_buckets(
    omit_middle_observations,
):
    # Three excursions close at buckets 36, 72 and 120, having started at
    # buckets 30, 60 and 90: durations 1, 2 and 5 hours. Their median is 2h,
    # rather than the mean 8/3h. Removing buckets 61..70 must not shorten the
    # second excursion: its two retained bad observations still span 2h to
    # the next stable observation. Recovery is 1 - 2/12 = 5/6.
    mod = _load_stability_module()
    samples = [
        _sample(
            mod, index,
            house_humidity=60.0
            if 30 <= index < 36 or 60 <= index < 72 or 90 <= index < 120
            else 50.0,
        )
        for index in range(432)
        if not (omit_middle_observations and 61 <= index <= 70)
    ]

    result = mod.evaluate_stability_window(samples)

    assert result["availability"] == "available"
    assert result["window"]["valid_samples"] == (422 if omit_middle_observations else 432)
    assert result["recovery"]["median_recovery_time_hours"] == 2.0
    assert result["recovery"]["open_event_capped"] is False
    assert result["recovery"]["open_event_duration_used_hours"] == 0.0
    assert result["subscores"]["recovery_score"] == 0.8333


@pytest.mark.parametrize(
    "condition,reason",
    [
        ({"worst_condensation_state": "Risk"}, "condensation_risk_duration_24h"),
        ({"worst_mould_state": "Risk"}, "mould_risk_duration_24h"),
        ({"air_quality_clearance": 0.0, "air_quality_bad_condition_count": 1},
         "air_quality_bad_duration_24h"),
    ],
)
@pytest.mark.parametrize("risk_buckets", [14, 15])
def test_sustained_cap_starts_at_fifteen_of_144_expected_buckets(
    condition, reason, risk_buckets,
):
    # With the final bucket at 431, the fixed 24h window is 288..431.
    # 14/144 = 9.722...%, whereas 15/144 = 10.416...%. Place all affected
    # buckets at its beginning so the separate 12h AQ cap and live caps
    # cannot obscure the threshold being tested.
    mod = _load_stability_module()
    samples = [
        _sample(
            mod, index, room_or_level_humidity_spread=0.0,
            **(condition if 288 <= index < 288 + risk_buckets else {}),
        )
        for index in range(432)
    ]

    result = mod.evaluate_stability_window(samples)

    assert result["availability"] == "available"
    assert result["score"]["window_score"] > 91
    if risk_buckets == 14:
        assert result["caps"]["classification_cap_reasons"] == []
        assert result["score"]["display_classification"] == "Excellent"
    else:
        assert result["caps"]["classification_cap_reasons"] == [reason]
        assert result["score"]["display_score"] == 91
        assert result["score"]["display_classification"] == "Good"
