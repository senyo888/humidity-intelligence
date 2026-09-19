#!/usr/bin/env python3
"""Build an offline Stability Score replay using the shipped backend and badge.

Run: python3 scripts/stability_scenario.py --output /tmp/hi-stability-scenario.html
No Home Assistant imports, connections, services, persistence or runtime mutation.
Synthetic observations are inputs; all score, cap, wording and movement are backend outputs.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import textwrap
import types
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[1]


def load_backend(root=ROOT):
    runtime = root / 'custom_components' / 'humidity_intelligence'
    if not (runtime / 'helpers' / 'stability.py').exists():
        runtime = root
    name = '_hi_scenario_backend'
    for suffix, path in [('', runtime), ('.helpers', runtime / 'helpers')]:
        package = types.ModuleType(name + suffix)
        package.__path__ = [str(path)]
        sys.modules[name + suffix] = package
    module_name = name + '.helpers.stability'
    spec = importlib.util.spec_from_file_location(module_name, runtime / 'helpers/stability.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module, runtime


# Each duration is actual synthetic 10-minute buckets; never shorten backend windows.
STAGES = [
    ('Collection', 302, 'Accumulate genuine synthetic buckets; no score before 303 samples.'),
    ('Excellent baseline', 130, 'Stable humidity inside the configured target and complete AQ evidence.'),
    ('Deterioration', 72, 'Humidity rises gradually beyond target; drift and room spread increase.'),
    ('Sustained Risk', 144, 'Mould Risk persists for a full 24 hours.'),
    ('Current Danger', 12, 'Mould Danger caps the current headline at 54 / Poor.'),
    ('AQ crossing', 12, 'A configured AQ threshold crossing applies its real backend cap.'),
    ('CO emergency', 6, 'The synthetic CO emergency latch forces the strongest headline cap.'),
    ('Recovery', 510, '85 hours of healthy observations allow historic caps and window evidence to expire.'),
    ('Partial AQ evidence', 432, 'AQ observations unavailable; missing evidence is never called bad air.'),
    ('Live unavailable', 6, 'Required current humidity truth unavailable; history cannot supply a score.'),
    ('Restore complete evidence', 432, 'Return complete live inputs and rebuild AQ evidence.'),
    ('Sampling gaps', 432, 'Skip every fourth scheduled observation; adjacent-pair coverage degrades.'),
]


def build_replay(mod):
    ring = mod.StabilitySnapshotRing()
    runtime = {'stability_snapshot_ring': ring, 'config': {
        'target_profile': 'custom', 'custom_target_low': 45., 'custom_target_high': 55.}}
    frames, stages = [], []
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    index = 0
    for stage_name, duration, description in STAGES:
        stages.append({'name': stage_name, 'start': index, 'end': index + duration - 1,
                       'description': description})
        for tick in range(duration):
            now = start + timedelta(minutes=10 * index)
            humidity, spread, drift, mould = 50., 1.5, 1., 'OK'
            if stage_name == 'Deterioration':
                humidity, spread, drift = 50 + 15 * (tick + 1) / duration, 6., 6.
            if stage_name == 'Sustained Risk':
                humidity, spread, drift, mould = 64., 7., 6., 'Risk'
            if stage_name == 'Current Danger':
                humidity, spread, drift, mould = 70., 9., 8., 'Danger'
            aq_bad = stage_name == 'AQ crossing'
            aq_missing = stage_name == 'Partial AQ evidence'
            unavailable = stage_name == 'Live unavailable'
            co = stage_name == 'CO emergency'
            mode = 'telemetry_unavailable' if unavailable else 'co_emergency' if co else 'normal'
            sample = mod.StabilitySnapshot(
                observed_at=now, house_humidity=None if unavailable else humidity,
                target_low=45., target_high=55., worst_condensation_state='OK',
                worst_mould_state=mould, room_or_level_humidity_spread=spread,
                house_humidity_drift_7d=drift, runtime_mode=mode,
                required_telemetry_available=not unavailable, balance_scope='room', balance_source_count=2,
                air_quality_clearance=None if aq_missing else 0. if aq_bad else 1.,
                air_quality_configured_condition_count=1,
                air_quality_evaluated_condition_count=0 if aq_missing else 1,
                air_quality_bad_condition_count=int(aq_bad), air_quality_telemetry_source_count=1,
                air_quality_source_count=1, air_quality_available_source_count=0 if aq_missing else 1,
                air_quality_bad_trigger_codes=('co2_high',) if aq_bad else (), co_emergency_active=co)
            gap = stage_name == 'Sampling gaps' and tick % 4 == 0
            accepted = False if gap else ring.add(sample)
            ring.prune(now)
            runtime.update(runtime_mode=mode, core_sensors=[types.SimpleNamespace(
                _attr_unique_id='hi_' + suffix, _attr_native_value=value) for suffix, value in [
                    ('house_avg_humidity', None if unavailable else humidity),
                    ('worst_condensation_risk', 'OK'), ('worst_mould_risk', mould)]],
                stability_current_air_quality={'configured_trigger_count': 1,
                    'evaluated_trigger_count': 0 if aq_missing else 1, 'crossed_trigger_count': int(aq_bad)})
            if not gap:
                mod.record_stability_score_movement(runtime, observed_at=now)
            payload = mod.stability_diagnostics_payload(runtime, observed_at=now)
            frames.append({'stage': stage_name, 'at': now.isoformat(), 'hour': round(index / 6, 2),
                'accepted': accepted, 'gap': gap, 'inputs': {'humidity': None if unavailable else humidity,
                'target': [45, 55], 'mould': mould, 'aq_bad': aq_bad, 'aq_missing': aq_missing,
                'co_emergency': co}, 'payload': payload})
            index += 1
    return {'stages': stages, 'frames': frames}


def extract_badge(runtime):
    source = runtime / 'ui/cards/v2_mobile.yaml'
    text = source.read_text()
    card = text.index('          entity: sensor.hi_diagnostics\n')
    gauge = text.index('            gauge: |\n', card)
    begin = text.index('[[[', gauge) + 3
    end = text.index(']]]', begin)
    javascript = textwrap.dedent(text[begin:end]).strip()
    css_match = re.search(r'(?m)^( +)extra_styles: \|\n', text[end:])
    if not css_match:
        raise ValueError('Shipped Stability badge CSS was not found')
    css_start = end + css_match.end()
    indent = len(css_match.group(1))
    css_lines = []
    for line in text[css_start:].splitlines():
        if line.strip() and len(line) - len(line.lstrip()) <= indent:
            break
        css_lines.append(line)
    css = textwrap.dedent('\n'.join(css_lines))
    if '.hi-stability-gauge {' not in css or 'return `<div' not in javascript:
        raise ValueError('Shipped Stability badge extraction failed')
    return javascript, css, hashlib.sha256(source.read_bytes()).hexdigest()


def render(output, root=ROOT):
    mod, runtime = load_backend(root)
    data = build_replay(mod)
    javascript, css, source_hash = extract_badge(runtime)
    data['provenance'] = {'formula_version': data['frames'][-1]['payload']['formula_version'],
        'backend_sha256': hashlib.sha256((runtime / 'helpers/stability.py').read_bytes()).hexdigest(),
        'card_sha256': source_hash, 'simulated': True}
    template = (root / 'tools/stability-scenario/index.html').read_text()
    serialized = json.dumps(data, separators=(',', ':'), allow_nan=False).replace('<', '\\u003c')
    html = template.replace('/* BADGE_CSS */', css).replace('/* BADGE_JS */', javascript).replace('/* REPLAY_DATA */', serialized)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html)
    return data


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = render(args.output)
    print(f"Built {len(result['frames'])} synthetic buckets across {len(result['stages'])} stages: {args.output}")
