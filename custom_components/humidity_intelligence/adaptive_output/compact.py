"""Optional compact presentation of existing observation truth; no control policy.

Attention order and semantics remain owned by the full model. This projection is
built after bridge overlays and may be omitted for an invalid input; callers keep
the complete existing payload as the compatibility fallback.
"""
MAX_LINES = 8
MAX_LINE = 240
MAX_CONDITIONS = 1024


def _count(value):
    if type(value) is not int or not 0 <= value <= MAX_CONDITIONS:
        raise ValueError('Invalid compact count.')
    return value


def _number(count, singular, plural=None):
    return f'{count} {singular if count == 1 else plural or singular + "s"}'


def build_compact(payload):
    """Return bounded backend-authored text, or None for the existing full fallback."""
    try:
        return _build(payload)
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def _build(payload):
    counts = payload['counts']
    configured = _count(counts['configured'])
    conditions = _count(counts['conditions'])
    affected = _count(counts['affected'])
    mapped = _count(counts['mapped'])
    reporting = _count(counts['reporting'])
    attention = payload['attention']
    records = payload['records']
    if not isinstance(attention, list) or not isinstance(records, list) or len(attention) != conditions or len(records) != configured:
        raise ValueError('Inconsistent compact inventory.')
    if affected > configured or reporting > mapped or mapped > configured:
        raise ValueError('Inconsistent compact counts.')
    coverage = payload['coverage']['state']
    if coverage not in ('not_configured', 'unmonitored', 'complete', 'incomplete'):
        raise ValueError('Unknown compact coverage.')
    discovery = payload.get('discovery', {})
    lost = _count(discovery.get('lost_count', 0))
    setup = _count(discovery.get('setup_count', 0))
    retired = _count(discovery.get('retired_count', 0))
    review = _count(discovery.get('review_count', 0))
    shown = min(2, conditions)
    remainder = conditions - shown
    if conditions:
        title = _number(conditions, 'condition') + ' · ' + _number(affected, 'output')
        tone = attention[0]['tone']  # Existing first item; never re-rank here.
        if tone not in ('neutral', 'active', 'context', 'warning', 'danger'):
            raise ValueError('Unknown compact tone.')
    elif not configured:
        title, tone = 'No outputs configured', 'neutral'
    elif coverage == 'complete':
        title, tone = 'No monitored issues reported', 'neutral'
    elif not mapped and not (lost or retired or review):
        title, tone = 'Monitoring not configured', 'neutral'
    else:
        title, tone = 'Monitoring incomplete', 'warning'

    monitoring = []
    # Lost evidence is independent of the two visible condition slots.
    if lost:
        monitoring.append(_number(lost, 'previously monitored source') + (' is' if lost == 1 else ' are') + ' no longer usable.')
    unknown = len({item.get('source') or item.get('entity_id') for item in attention
                   if item.get('code') == 'monitoring_unknown'})
    if unknown:
        monitoring.append(_number(unknown, 'monitoring source') + (' cannot currently be interpreted.'))
    routine = []
    if configured and coverage != 'complete':
        routine.append(f'Monitoring configured: {mapped}/{configured} outputs')
        if reporting != mapped:
            routine.append(f'Readings usable for {reporting}/{configured} outputs')
    if setup:
        routine.append(_number(setup, 'reading') + (' needs a monitoring rule' if setup == 1 else ' need a monitoring rule'))
    if routine:
        monitoring.append(' · '.join(routine))
    if retired:
        monitoring.append('Monitoring is paused for ' + _number(retired, 'output/source link') + '.')
    if review > setup + lost:
        monitoring.append(_number(review, 'diagnostic source') + (' needs' if review == 1 else ' need') + ' review in total.')

    runtime = {row['key']: row['state'] for row in payload.get('runtime_context', [])}
    context = []
    if runtime.get('air_control_manual_override') == 'on':
        context.append('Manual control is active.')
    if runtime.get('air_control_enabled') == 'off':
        context.append('Automatic air control is disabled.')
    if payload.get('runtime_context_complete') is False:
        context.append('HI control or isolation context is incomplete.')
    isolation = {kind: sum(row.get('isolation', {}).get('state') == kind for row in records)
                 for kind in ('isolated', 'partial', 'unknown')}
    parts = []
    for kind, text in (('isolated', 'isolated'), ('partial', 'with some roles isolated'), ('unknown', 'with isolation unknown')):
        if isolation[kind]:
            parts.append(_number(isolation[kind], 'output') + ' ' + text)
    if parts:
        context.append(' · '.join(parts) + '.')
    pending = sum(row.get('observation_pending') is True for row in records)
    if pending:
        context.append(_number(pending, 'output') + (' is' if pending == 1 else ' are') + ' waiting for a new Home Assistant report.')
    disabled = sum(bool(row.get('configured_roles')) and all(role.get('enabled') is False for role in row['configured_roles']) for row in records)
    if disabled:
        context.append(_number(disabled, 'output') + (' has' if disabled == 1 else ' have') + ' only disabled configured roles.')
    for lines in (monitoring, context):
        if len(lines) > MAX_LINES or any(len(line) > MAX_LINE for line in lines):
            raise ValueError('Compact text exceeds supported bounds.')
    return dict(schema_version=1, title=title, tone=tone,
                condition_count=conditions, affected_output_count=affected,
                shown_condition_count=shown, remaining_condition_count=remainder,
                remainder_label=f'Showing {shown} of {conditions} conditions · {remainder} more' if remainder else '',
                monitoring_lines=monitoring, context_lines=context)
