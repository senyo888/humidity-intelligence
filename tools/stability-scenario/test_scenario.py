"""End-to-end synthetic replay exercises actual backend and shipped badge extraction."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('hi_scenario', ROOT / 'scripts/stability_scenario.py')
scenario = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scenario)


def test_full_scenario_uses_real_backend_transitions():
    backend, runtime = scenario.load_backend()
    replay = scenario.build_replay(backend)
    ends = {s['name']: replay['frames'][s['end']]['payload'] for s in replay['stages']}
    assert ends['Collection']['presentation']['state_code'] == 'collecting'
    assert ends['Excellent baseline']['score']['display_classification'] == 'Excellent'
    assert ends['Deterioration']['score']['display_score'] < ends['Excellent baseline']['score']['display_score']
    assert ends['Sustained Risk']['score']['display_score'] <= 91
    assert ends['Current Danger']['score']['display_score'] <= 54
    assert ends['AQ crossing']['aq_adjustment']['points'] == 12
    assert not any('air_quality_bad' in reason for reason in ends['AQ crossing']['caps']['classification_cap_reasons'])
    assert ends['CO emergency']['score']['display_score'] == 0
    assert ends['Recovery']['score']['display_classification'] == 'Excellent'
    assert ends['Partial AQ evidence']['presentation']['tone'] == 'incomplete'
    assert ends['Live unavailable']['presentation']['state_code'] == 'live_data_unavailable'
    assert ends['Live unavailable']['movement']['status'] == 'unavailable'
    assert ends['Restore complete evidence']['score']['display_classification'] == 'Excellent'
    assert ends['Sampling gaps']['presentation']['state_code'] == 'incomplete_evidence_gaps'
    assert any(f['payload']['movement']['direction'] == 'higher' for f in replay['frames'])
    assert any(f['payload']['movement']['direction'] == 'lower' for f in replay['frames'])
    tokens = {f['payload']['movement']['color_token'] for f in replay['frames']}
    assert {'rise_gentle', 'rise_strong', 'fall_gentle', 'fall_strong'} <= tokens
    movements = [f['payload']['movement'] for f in replay['frames']]
    assert any(m['direction'] == 'higher' and m['start_position_degrees'] < m['end_position_degrees'] < 0 for m in movements)
    assert any(m['direction'] == 'steady' and m['end_position_degrees'] != 0 and m['start_position_degrees'] == m['end_position_degrees'] for m in movements)
    assert any(abs(m['end_position_degrees']) > 180 for m in movements)
    for frame in replay['frames']:
        assert frame['payload']['control_contract']['lane_selection_input'] is False
        assert frame['payload']['control_contract']['output_write_input'] is False
    js, css, digest = scenario.extract_badge(runtime)
    assert 'stability.movement' in js
    assert 'width: 82px' in css
    assert len(digest) == 64
