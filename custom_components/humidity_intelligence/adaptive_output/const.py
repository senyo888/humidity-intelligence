"""Optional read-only output observation contract."""
DOMAIN = 'humidity_intelligence'
HI_DOMAIN = DOMAIN
CONF_SECTION = 'output_observation'
CONF_CONFIRMATIONS = 'confirmations'
MAX_PAYLOAD_BYTES = 524288
HELPERS = {
    'air_control_enabled': 'HI automatic control',
    'air_control_manual_override': 'HI manual override',
    'air_isolate_fan_outputs': 'Fan-output isolation',
    'air_isolate_humidifier_outputs': 'Humidifier-output isolation',
}


def observation_settings(data, options):
    """Whole-section options precedence, matching HI's effective configuration."""
    value = options.get(CONF_SECTION) if CONF_SECTION in options else data.get(CONF_SECTION, {})
    if not isinstance(value, dict):
        raise ValueError('Output observation settings must be a dictionary.')
    result = {'enabled': False, 'presentation': 'native', 'confirmations': [], 'retired': [], 'custom_meanings': {}, **value}
    if type(result['enabled']) is not bool or result['presentation'] not in ('native', 'adaptive'):
        raise ValueError('Invalid output observation enable or presentation setting.')
    return result
