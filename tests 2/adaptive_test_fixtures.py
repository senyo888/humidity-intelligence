"""Hand-authored synthetic fleet and registry fixtures; no live data or external files."""

"""Public-safe, hand-authored synthetic fixtures. No live-data reader."""
from copy import deepcopy
from adaptive_test_support import normalize


def fixtures():
    configured = [
        {'entity_id':'fan.hi_example_extract','label':'Extract fan','role':'ventilation_zone_1','selected':True},
        {'entity_id':'fan.hi_example_supply','label':'Supply fan','role':'ventilation_zone_2'},
        {'entity_id':'humidifier.hi_example_humidifier','label':'Humidifier','role':'humidifier_zone_1'},
        {'entity_id':'light.hi_example_alert','label':'Alert light','role':'alert_light'},
    ]
    states = {r['entity_id']:{'state':'off'} for r in configured}
    mappings = [dict(output=r['entity_id'], source=f'binary_sensor.hi_example_problem_{i}', semantic='problem', rule='binary_active') for i,r in enumerate(configured)]
    states.update({m['source']:{'state':'off'} for m in mappings})
    result = []
    def add(key, label, description, change=lambda c,s,m: None, control_context=None):
        c,s,m = deepcopy(configured),deepcopy(states),deepcopy(mappings)
        change(c,s,m)
        result.append(dict(id=key,label=label,description=description,configured=c,states=s,mappings=m,control_context=deepcopy(control_context)))
    add('normal','Normal / no mapped issue','All four outputs are off; mapped problem sources report off. This is not a device-health guarantee.')
    add('active','Active','Extract fan reports on at 65%. Device operation and monitored conditions remain independent.',lambda c,s,m:s.update({'fan.hi_example_extract':{'state':'on','attributes':{'percentage':65}}}))
    add('unavailable','Unavailable','Primary output reports unavailable; its condition source can still report normally.',lambda c,s,m:s.update({'fan.hi_example_supply':{'state':'unavailable'}}))
    add('isolated','Isolated','Explicit isolation context while extract fan reports on. Isolation is not proof of physical off.',lambda c,s,m:(c[0].update(isolated=True),s.update({'fan.hi_example_extract':{'state':'on'}})))
    add('fault','Fault','Explicitly mapped binary fault signal reports on.',lambda c,s,m:(m[0].update(semantic='fault'),s.update({m[0]['source']:{'state':'on'}})))
    add('maintenance','Maintenance','Explicit filter and refill mappings require action. Extract fan remains active.',lambda c,s,m:(m[0].update(semantic='replace_filter'),m[2].update(semantic='refill'),s.update({m[0]['source']:{'state':'on'},m[2]['source']:{'state':'on'},c[0]['entity_id']:{'state':'on'}})))
    add('humidifier_idle','Humidifier on / idle','The humidifier is on but its explicit platform action is idle. On does not mean humidifying.',lambda c,s,m:s.update({c[2]['entity_id']:{'state':'on','attributes':{'action':'idle'}}}))
    add('humidifier_retry_refill','Humidifier retry / refill','Observed off state, explicit refill signal and separate synthetic HI retry context. No causal relationship is inferred.',lambda c,s,m:(m[2].update(semantic='refill'),s.update({m[2]['source']:{'state':'on'}})),control_context={
        'label':'Humidifier · Retrying',
        'detail':'Demand requested; HI is awaiting output-on confirmation. Refill is reported separately; causation is not established.',
    })
    add('unmonitored','Unmonitored','Outputs remain visible without mapped device-condition evidence.',lambda c,s,m:m.clear())
    add('partial_mapping_only','Partially mapped / no issues reported','Three of four outputs have reporting mappings; the fourth remains unmonitored. Absence of reported issues is not complete monitoring.',lambda c,s,m:m.pop())
    add('incomplete_monitoring','Incomplete monitoring','One monitoring source is unavailable, one output is unmapped. Neither makes a primary output unavailable.',lambda c,s,m:(s.update({m[0]['source']:{'state':'unavailable'}}),m.pop()))
    add('unknown','Unknown','Primary entity exists but reports unknown; fault is not inferred.',lambda c,s,m:s.update({c[0]['entity_id']:{'state':'unknown'}}))
    add('missing','Missing output','Configured output has no state entry.',lambda c,s,m:s.pop(c[0]['entity_id']))
    add('unsupported','Unsupported domain','Observed-only air purifier remains in inventory; no control support claim.',lambda c,s,m:(c.append(dict(entity_id='air_purifier.hi_example_purifier',label='Air purifier',role='aq')),s.update({'air_purifier.hi_example_purifier':{'state':'on'}})))
    add('no_outputs','No outputs','No configured inventory or mappings.',lambda c,s,m:(c.clear(),s.clear(),m.clear()))
    def multiple(c,s,m):
        m[0]['semantic']='fault'
        s[m[0]['source']]={'state':'on'}
        m.append(dict(output=c[0]['entity_id'],source='sensor.hi_example_filter',semantic='replace_filter',rule='numeric_below',threshold=10))
        s['sensor.hi_example_filter']={'state':'5'}
        s[c[0]['entity_id']]={'state':'on'}
    add('multiple_conditions','Multiple conditions / one output','Active extract fan reports both a fault and a filter intervention; it counts as one affected output.',multiple)
    def mixed(c,s,m):
        multiple(c,s,m)
        s[c[1]['entity_id']]={'state':'unavailable'}
        m[2]['semantic']='refill'
        s[m[2]['source']]={'state':'on'}
        s[m[3]['source']]={'state':'unknown'}
    add('mixed','Mixed fleet / overflow','Four affected outputs, five conditions. Overflow counts outputs rather than signals.',mixed)
    add('enum_rule','Explicit enum rule','Known active and clear enum values; novel vendor values fail closed.',lambda c,s,m:(m[0].update(rule='enum_active_values',active_values=['blocked'],clear_values=['clear'],semantic='obstruction'),s.update({m[0]['source']:{'state':'blocked'}})))
    add('orphaned_mapping','Orphaned mapping','A saved mapping points to a removed output; it is shown without reassigning it.',lambda c,s,m:m.append(dict(output='fan.hi_example_removed',source='binary_sensor.hi_example_removed_problem',semantic='problem',rule='binary_active')))
    def larger_fleet(c,s,m):
        c.clear();s.clear();m.clear()
        layout = [
            ('fan','ventilation_zone_1'),('switch','ventilation_zone_1'),
            ('fan','ventilation_zone_2'),('switch','ventilation_zone_2'),
            ('fan','aq'),('switch','aq'),
            ('humidifier','humidifier_zone_1'),('humidifier','humidifier_zone_2'),
            ('light','alert_light'),('light','alert_light'),
            ('switch','alert_power'),('switch','alert_power'),
        ]
        for i,(domain,role) in enumerate(layout):
            entity=f'{domain}.hi_example_fleet_{i+1:02d}'
            label=f'{domain.title()} output {i+1:02d}'
            if i==0:
                label='Shared extract fan with a deliberately long descriptive label for narrow displays'
            c.append(dict(entity_id=entity,label=label,role=role,selected=i==0))
            s[entity]={'state':'on' if i%2==0 else 'off'}
            source=f'binary_sensor.hi_example_fleet_{i+1:02d}_problem'
            m.append(dict(output=entity,source=source,semantic='problem',rule='binary_active'))
            s[source]={'state':'on' if i in (0,4,6,8,10) else 'off'}
        # Shared-role identity remains one record; separate output entities remain
        # distinct regardless of what a future device-registry adapter observes.
        c.append(dict(c[0],role='aq'))
        c.append(dict(c[1],role='alert_power'))
        for i,semantic in ((0,'replace_filter'),(6,'refill')):
            source=f'binary_sensor.hi_example_fleet_{i+1:02d}_maintenance'
            m.append(dict(output=c[i]['entity_id'],source=source,semantic=semantic,rule='binary_active'))
            s[source]={'state':'on'}
        s[c[2]['entity_id']]={'state':'unavailable'}
        c[7]['isolated']=True
    add('larger_mixed_fleet','12 outputs / mixed fleet','Twelve distinct outputs across seven roles, two shared-role records, fourteen explicit mappings and a long display label. Six affected outputs produce exact overflow.',larger_fleet)

    def alerts_only(c,s,m):
        c[:]=[
            dict(entity_id='light.hi_example_visual_a',label='Visual alert A',role='alert_light'),
            dict(entity_id='light.hi_example_visual_b',label='Visual alert B',role='alert_light'),
            dict(entity_id='switch.hi_example_alert_power',label='Alert power',role='alert_power'),
        ]
        s.clear();m.clear()
        s.update({r['entity_id']:{'state':'off'} for r in c})
    add('alert_only','Alert-only installation','Two visual alert outputs and one alert power switch remain a complete configured inventory without ventilation or humidifiers.',alerts_only)

    def switches_only(c,s,m):
        c[:]=[
            dict(entity_id=f'switch.hi_example_relay_{i+1}',label=f'Output relay {i+1}',role=role)
            for i,role in enumerate(('ventilation_zone_1','ventilation_zone_1','ventilation_zone_2','aq','alert_power'))
        ]
        s.clear();m.clear()
        s.update({r['entity_id']:{'state':'on' if i in (1,3) else 'off'} for i,r in enumerate(c)})
    add('switches_only','Five switch outputs','A switch-only installation retains saved list order, multiple outputs per role and explicit unmonitored status. No four-output assumption.',switches_only)
    return result


def build_scenarios():
    return [dict(id=f['id'],label=f['label'],description=f['description'],control_context=f['control_context'],payload=normalize(f['configured'],f['states'],f['mappings'])) for f in fixtures()]

"""Synthetic registry transitions run through automatic discovery and status."""
from copy import deepcopy
from adaptive_test_support import DiscoverySession
from adaptive_test_support import identity
from adaptive_test_support import extract_configured


def base_inputs():
    data = dict(zones={'zone1': {'outputs': ['fan.hi_example_device_fan', 'switch.hi_example_device_power']}},
                humidifiers={'level1': {'outputs': ['humidifier.hi_example_device_humidifier']}},
                aq={}, alerts=[])
    labels = {'fan.hi_example_device_fan': 'Ventilation unit', 'switch.hi_example_device_power': 'Unit power',
              'humidifier.hi_example_device_humidifier': 'Humidifier'}
    configured = extract_configured(data, {}, labels=labels)
    registry = []
    def add(entity_id, device, cls=None, category=None, **kwargs):
        registry.append(dict(entity_id=entity_id, id='example_'+entity_id.split('.')[1],
            device_id=device, original_device_class=cls, entity_category=category, **kwargs))
    add('fan.hi_example_device_fan', 'example_ventilation')
    add('switch.hi_example_device_power', 'example_ventilation')
    add('humidifier.hi_example_device_humidifier', 'example_humidifier')
    add('binary_sensor.hi_example_device_problem', 'example_ventilation', 'problem', 'diagnostic')
    add('binary_sensor.hi_example_device_connection', 'example_ventilation', 'connectivity', 'diagnostic')
    add('binary_sensor.hi_example_device_battery', 'example_humidifier', 'battery', 'diagnostic')
    add('sensor.hi_example_device_signal', 'example_ventilation', 'signal_strength', 'diagnostic')
    add('sensor.hi_example_device_filter', 'example_ventilation', None, 'diagnostic')
    add('sensor.hi_example_device_tank', 'example_humidifier', 'enum', 'diagnostic')
    add('binary_sensor.hi_example_unrelated_problem', 'example_unrelated', 'problem', 'diagnostic')
    source_names = dict(problem='Device problem', connection='Connection', battery='Low battery',
                        signal='Signal strength', filter='Filter remaining', tank='Tank status')
    for entry in registry:
        suffix = entry['entity_id'].rsplit('_', 1)[-1]
        if suffix in source_names:
            entry['name'] = source_names[suffix]
    states = {r['entity_id']: {'state':'off'} for r in registry}
    states.update({
        'fan.hi_example_device_fan': {'state':'on', 'attributes':{'percentage':55}},
        'switch.hi_example_device_power': {'state':'on'},
        'binary_sensor.hi_example_device_connection': {'state':'on'},
        'sensor.hi_example_device_signal': {'state':'-63'},
        'sensor.hi_example_device_filter': {'state':'7'},
        'sensor.hi_example_device_tank': {'state':'empty'},
        'binary_sensor.hi_example_unrelated_problem': {'state':'on'},
    })
    return configured, registry, states


def confirmation(registry, output, source, **rule):
    entries = {r['entity_id']:r for r in registry}
    return dict(output=output, source=source, output_identity=identity(entries[output]),
                source_identity=identity(entries[source]), **rule)


def build_discovery_scenarios():
    configured, registry, states = base_inputs()
    session = DiscoverySession(configured, registry, states)
    result = []
    def capture(key, label, description, current=session, **extra):
        result.append(dict(id='discovery_'+key, label='Discovery · '+label, description=description,
                           control_context=None, payload=deepcopy(current.snapshot['payload']),
                           observer=dict(watch_entities=current.snapshot['watch_entities'], revision=current.revision), **extra))
    capture('automatic', 'Automatic sources', 'Diagnostics are pulled from the configured devices. Standard problem, connection and battery meanings are automatic; filter and tank meanings are not guessed.')
    session.state_changed('binary_sensor.hi_example_device_problem', {'state':'on'})
    capture('device_problem', 'Shared device problem', 'One device-level source is associated with both configured outputs. It reports a device problem, not two diagnosed component faults.')
    session.state_changed('binary_sensor.hi_example_device_problem', {'state':'off'})
    session.state_changed('binary_sensor.hi_example_device_battery', {'state':'on'})
    session.state_changed('binary_sensor.hi_example_device_connection', {'state':'off'})
    capture('battery_connection', 'Battery and connection', 'Low battery and disconnected meanings come from documented binary classes. A separate output may still report On.')
    session.state_changed('binary_sensor.hi_example_device_battery', {'state':'off'})
    session.state_changed('binary_sensor.hi_example_device_connection', {'state':'on'})
    session.state_changed('binary_sensor.hi_example_device_problem', {'state':'unavailable'})
    capture('unavailable', 'Diagnostic unavailable', 'The diagnostic source becomes unavailable while the output remains On. Monitoring and output availability stay separate.')
    disabled = deepcopy(registry)
    next(r for r in disabled if r['entity_id']=='binary_sensor.hi_example_device_problem')['disabled_by']='user'
    session.registry_changed(disabled)
    capture('disabled', 'Diagnostic disabled', 'Discovery lists a disabled source without enabling it. Previously monitored coverage remains visibly incomplete.')
    removed = [r for r in registry if r['entity_id']!='binary_sensor.hi_example_device_problem']
    session.registry_changed(removed)
    capture('removed', 'Diagnostic removed', 'A removed source remains a monitoring gap for the session. Removing a diagnostic does not silently clear attention.')
    session.registry_changed(registry)
    session.state_changed('binary_sensor.hi_example_device_problem', {'state':'off'})
    capture('restored', 'Diagnostic restored', 'The same source identity returns with a reporting state. The monitoring gap clears without a device command.')
    confirmations = [confirmation(registry, 'fan.hi_example_device_fan', 'sensor.hi_example_device_filter',
                        semantic='replace_filter', rule='numeric_below', threshold=10),
                     confirmation(registry, 'humidifier.hi_example_device_humidifier', 'sensor.hi_example_device_tank',
                        semantic='refill', rule='enum_active_values', active_values=['empty'], clear_values=['filled'])]
    session.confirm(confirmations)
    capture('confirmed', 'Confirmed filter and tank', 'Synthetic user confirmation supplies a below-10 filter threshold and empty/filled tank meaning. These example rules are not universal defaults.')
    result[0]['comparison_id']='discovery_confirmed'
    result[-1]['comparison_id']='discovery_automatic'
    session.state_changed('sensor.hi_example_device_tank', {'state':'new_vendor_value'})
    capture('novel_value', 'Unrecognised vendor value', 'An unfamiliar tank value cannot become clear. The confirmed mapping reports monitoring uncertainty.')
    session.state_changed('sensor.hi_example_device_tank', {'state':'filled'})
    renamed = deepcopy(registry)
    next(r for r in renamed if r['entity_id']=='sensor.hi_example_device_filter')['entity_id']='sensor.hi_example_renamed_filter'
    session.registry_changed(renamed)
    session.state_changed('sensor.hi_example_renamed_filter', {'state':'7'})
    capture('renamed', 'Source renamed', 'A harmless entity-ID rename follows the same stable registry identity. Its confirmed meaning is preserved.')
    replaced = deepcopy(renamed)
    next(r for r in replaced if r['entity_id']=='sensor.hi_example_renamed_filter')['id']='example_replacement_filter'
    session.registry_changed(replaced)
    capture('replaced', 'Source identity replaced', 'A replacement source cannot inherit the previous confirmed meaning just because its entity ID is similar.')
    no_device = deepcopy(registry)
    next(r for r in no_device if r['entity_id']=='humidifier.hi_example_device_humidifier')['device_id']=None
    detached = DiscoverySession(configured, no_device, states)
    capture('no_device', 'Output without device', 'An output without device association stays in inventory. Automatic discovery cannot establish its diagnostics; explicit mapping remains possible.', detached)
    return result
