"""Pure adapter for current HI saved config; no HA imports, state reads or writes.

Whole-section options precedence follows config_flow._effective_config. Disabled
roles still describe configured inventory. Selection/isolation/conflict can only
come from explicitly supplied runtime context, never from config enable flags.
"""
from .model import ENTITY, MAX_CONFIG


SECTIONS = (
    ('zones', (('zone1', 'ventilation_zone_1'), ('zone2', 'ventilation_zone_2'))),
    ('humidifiers', (('level1', 'humidifier_zone_1'), ('level2', 'humidifier_zone_2'))),
    ('aq', (('level1', 'aq'), ('level2', 'aq'))),
)
CONTEXT = frozenset(('selected', 'isolated', 'safety_conflict'))


def _entity(value, path):
    if not isinstance(value, str) or ENTITY.fullmatch(value) is None:
        raise ValueError(f'{path} requires a valid entity ID.')
    return value


def extract_configured(data, options, labels=None, context=None):
    """Return role-tagged normalizer rows, preserving saved list order/duplicates.

    labels is an optional entity-ID -> plain label dictionary; the normalizer
    bounds displayed text. context is entity-ID -> explicit boolean context.
    Unknown top-level config settings are outside this adapter's scope. Unknown
    role keys inside output sections reject, to avoid silently losing outputs.
    The 128-record limit applies before shared-output deduplication.
    """
    if not isinstance(data, dict) or not isinstance(options, dict):
        raise ValueError('Config data and options must be dictionaries.')
    labels = {} if labels is None else labels
    context = {} if context is None else context
    if not isinstance(labels, dict) or not isinstance(context, dict):
        raise ValueError('Labels and context must be dictionaries.')
    for entity, label in labels.items():
        _entity(entity, 'Label key')
        if not isinstance(label, str):
            raise ValueError('Labels must be plain strings.')
    for entity, values in context.items():
        _entity(entity, 'Context key')
        if not isinstance(values, dict) or set(values) - CONTEXT:
            raise ValueError('Context supports selected, isolated and safety_conflict only.')
        if any(type(value) is not bool for value in values.values()):
            raise ValueError('Runtime context must contain explicit booleans.')

    result = []

    def add(entity, role, path, enabled):
        _entity(entity, path)
        if len(result) >= MAX_CONFIG:
            raise ValueError(f'Configuration exceeds {MAX_CONFIG} output records.')
        row = {'entity_id': entity, 'role': role, 'role_enabled': enabled}
        if entity in labels:
            row['label'] = labels[entity]
        row.update(context.get(entity, {}))
        result.append(row)

    def add_list(values, role, path, enabled):
        if not isinstance(values, list):
            raise ValueError(f'{path} must be a list.')
        for entity in values:
            add(entity, role, path, enabled)

    for section_name, roles in SECTIONS:
        section = options.get(section_name) if section_name in options else data.get(section_name, {})
        if not isinstance(section, dict):
            raise ValueError(f'{section_name} must be a dictionary.')
        if set(section) - {key for key, _ in roles}:
            raise ValueError(f'{section_name} contains an unsupported role key.')
        for key, role in roles:
            cfg = section.get(key, {})
            if not isinstance(cfg, dict):
                raise ValueError(f'{section_name}.{key} must be a dictionary.')
            enabled = cfg.get('enabled', False)
            if type(enabled) is not bool:
                raise ValueError('Configured role enable flags must be booleans.')
            add_list(cfg.get('outputs', []), role, f'{section_name}.{key}.outputs', enabled)

    alerts = options.get('alerts') if 'alerts' in options else data.get('alerts', [])
    if not isinstance(alerts, list):
        raise ValueError('alerts must be a list.')
    for index, alert in enumerate(alerts):
        if not isinstance(alert, dict):
            raise ValueError(f'alerts[{index}] must be a dictionary.')
        enabled = alert.get('enabled', True)
        if type(enabled) is not bool:
            raise ValueError('Configured alert enable flags must be booleans.')
        add_list(alert.get('lights', []), 'alert_light', f'alerts[{index}].lights', enabled)
        power = alert.get('power_entity')
        if power is not None and power != '':
            add(power, 'alert_power', f'alerts[{index}].power_entity', enabled)
    return result
