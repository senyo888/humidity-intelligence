"""Observed failed buckets stay bounded and cannot imply sample progress."""
from datetime import datetime, timedelta, timezone

from test_stability_score import _load_stability_module, _sample

NOW = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)


def test_failed_bucket_is_unique_and_success_clears_only_same_bucket():
    mod = _load_stability_module()
    runtime = {}
    previous = NOW - timedelta(minutes=10)
    for bucket in (previous, NOW, NOW):
        mod.record_stability_bucket_outcome(runtime, bucket, NOW)
    assert runtime['stability_failed_buckets'] == {previous, NOW}
    mod.record_stability_bucket_outcome(runtime, NOW, NOW, successful=True)
    assert runtime['stability_failed_buckets'] == {previous}
    result = mod._sampling_payload(runtime, observed_at=NOW)['failure_history']
    assert result['status'] == 'available'
    assert result['failed_bucket_count'] == 1
    expected = (int(previous.timestamp()) // 600 % 432) * 360 / 432
    assert result['marker_angles_degrees'] == [round(expected, 6)]


def test_long_late_history_is_bounded_and_expires_on_read():
    mod = _load_stability_module()
    runtime = {}
    mod.record_stability_bucket_outcome(runtime, NOW - timedelta(days=365), NOW, missed_range=True)
    result = mod._sampling_payload(runtime, observed_at=NOW)['failure_history']
    assert result['failed_bucket_count'] == 432
    assert len(set(result['marker_angles_degrees'])) == 432
    assert all(0 <= angle < 360 for angle in result['marker_angles_degrees'])
    later = mod._sampling_payload(runtime, observed_at=NOW + timedelta(hours=72))['failure_history']
    assert later['failed_bucket_count'] == 0
    assert runtime['stability_failed_buckets'] == set()


def test_future_missing_and_malformed_history_never_invent_failures():
    mod = _load_stability_module()
    runtime = {'stability_failed_buckets': {False, 7, 'bad', datetime(2026, 9, 19), NOW + timedelta(minutes=10), NOW + timedelta(seconds=1)}}
    mod.record_stability_bucket_outcome(runtime, NOW + timedelta(minutes=10), NOW, missed_range=True)
    assert runtime['stability_failed_buckets'] == set()
    assert mod._sampling_payload({}, observed_at=NOW)['failure_history']['failed_bucket_count'] == 0
    for bad in (None, [], 'bad', 42):
        runtime['stability_failed_buckets'] = bad
        assert mod._sampling_payload(runtime, observed_at=NOW)['failure_history']['failed_bucket_count'] == 0


def test_late_range_records_only_scheduled_boundaries_and_prunes_old_data():
    mod = _load_stability_module()
    runtime = {}
    first = NOW - timedelta(minutes=20)
    mod.record_stability_bucket_outcome(runtime, first, NOW + timedelta(seconds=30), missed_range=True)
    assert runtime['stability_failed_buckets'] == {first, first + timedelta(minutes=10), NOW}
    assert 'stability_snapshot_ring' not in runtime
    # A fresh runtime has no reconstructed missed history.
    assert mod._sampling_payload({}, observed_at=NOW)['failure_history']['marker_angles_degrees'] == []


def test_missing_history_is_unavailable_and_reads_do_not_initialize_it():
    mod = _load_stability_module()
    for bad in (None, [], "bad", 42):
        runtime = {} if bad is None else {"stability_failed_buckets": bad}
        result = mod._sampling_payload(runtime, observed_at=NOW)["failure_history"]
        assert result["status"] == "unavailable"
        assert result["marker_angles_degrees"] == []
        assert runtime.get("stability_failed_buckets") is bad
    assert mod._sampling_payload({"stability_failed_buckets": set()}, observed_at=NOW)["failure_history"]["status"] == "available"


def test_stored_valid_bucket_cannot_be_marked_failed_by_later_duplicate_attempt():
    mod = _load_stability_module()
    ring = mod.StabilitySnapshotRing()
    assert ring.add(_sample(mod, 0, observed_at=NOW))
    runtime = {"stability_snapshot_ring": ring, "stability_failed_buckets": {NOW}}
    mod.record_stability_bucket_outcome(runtime, NOW, NOW)
    assert runtime["stability_failed_buckets"] == set()
    previous = NOW - timedelta(minutes=10)
    mod.record_stability_bucket_outcome(runtime, previous, NOW, missed_range=True)
    assert runtime["stability_failed_buckets"] == {previous}
