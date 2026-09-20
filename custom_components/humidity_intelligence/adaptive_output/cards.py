"""Surgically integrate output observation into normal generated cards.

Only the Outputs header/detail pair is replaced for adaptive presentation.
Native controls expand to the complete configured inventory while retaining
supporting rows and actions. Every byte outside the replacement span is retained.
These pure helpers perform no HA API calls or filesystem writes.
"""
from copy import deepcopy
import re

import yaml
from yaml.nodes import MappingNode, SequenceNode, ScalarNode

ENTITY = re.compile(r'^sensor\.[a-z0-9_]+$')


def _fields(node):
    return {key.value: value for key, value in node.value} if isinstance(node, MappingNode) else {}


def _value(node, field):
    found = _fields(node).get(field)
    return found.value if isinstance(found, ScalarNode) else None


def _sequences(node):
    if isinstance(node, SequenceNode):
        yield node
        for child in node.value:
            yield from _sequences(child)
    elif isinstance(node, MappingNode):
        for _, child in node.value:
            yield from _sequences(child)


def _entities(card):
    if not isinstance(card, dict):
        raise ValueError('Output detail wrapper is malformed.')
    if card.get('type') == 'entities':
        if not isinstance(card.get('entities'), list):
            raise ValueError('Native output entities must be a list.')
        return card
    if card.get('type') == 'custom:mod-card' and isinstance(card.get('card'), dict):
        return _entities(card['card'])
    raise ValueError('Unsupported output detail wrapper; refusing to discard interactions.')


def wire_card(source, entity):
    """Return patched YAML and public-safe preservation metadata; reject ambiguity."""
    if not isinstance(source, str) or not ENTITY.fullmatch(entity):
        raise ValueError('Source must be YAML text and feed must be a sensor entity ID.')
    root = yaml.compose(source)
    if root is None:
        raise ValueError('Card YAML is empty.')
    matches = []
    for sequence in _sequences(root):
        for index, header in enumerate(sequence.value):
            if _value(header, 'name') != 'Outputs' or _value(header, 'type') != 'custom:button-card':
                continue
            if index + 1 >= len(sequence.value):
                raise ValueError('Outputs header has no adjacent detail conditional.')
            detail = sequence.value[index + 1]
            if _value(detail, 'type') != 'conditional':
                raise ValueError('Outputs detail must be an adjacent conditional.')
            matches.append((header, detail))
    if len(matches) != 1:
        raise ValueError('Expected exactly one existing Outputs header/detail pair.')
    header, detail = matches[0]
    # Safe-load the complete document and source-mark-selected snippets, never eval JS.
    yaml.safe_load(source)
    lines = source.splitlines(keepends=True)
    first = header.start_mark.line
    last = detail.end_mark.line
    if last < len(lines) and lines[last][:detail.end_mark.column].strip():
        last += 1
    while last > first and (not lines[last - 1].strip() or lines[last - 1].lstrip().startswith('#')):
        last -= 1
    prefix = ''.join(lines[:first])
    suffix = ''.join(lines[last:])
    indent = re.match(r'^(\s*)- ', lines[first])
    if not indent:
        raise ValueError('Outputs header must be a block sequence item.')
    width = len(indent.group(1))
    original = yaml.safe_load(''.join(line[width:] if line.strip() else line for line in lines[first:last]))
    if not isinstance(original, list) or len(original) != 2:
        raise ValueError('Replacement span must contain only the output pair.')
    old_header, old_detail = original
    conditions = old_detail.get('conditions')
    if conditions != [{'entity': old_header.get('entity'), 'state': 'on'}]:
        raise ValueError('Output conditional has extra semantics; manual review required.')
    native = deepcopy(_entities(old_detail.get('card')))
    replacement = [{'type': 'custom:hi-adaptive-output-card', 'entity': entity, 'control_context': native}]
    rendered = yaml.safe_dump(replacement, sort_keys=False, allow_unicode=True, width=10000)
    rendered = ''.join(' ' * width + line if line.strip() else line for line in rendered.splitlines(keepends=True))
    patched = prefix + rendered + suffix
    parsed = yaml.safe_load(patched)
    # Compare whole-document structures after restoring the one intended replacement.
    baseline = yaml.safe_load(source)
    def restore(value):
        if isinstance(value, list):
            result=[]
            for child in value:
                if isinstance(child, dict) and child == replacement[0]:
                    result.extend(deepcopy(original))
                else:
                    result.append(restore(child))
            return result
        if isinstance(value, dict):
            return {key: restore(child) for key, child in value.items()}
        return value
    if restore(parsed) != baseline:
        raise ValueError('Unexpected change outside Outputs; refusing patch.')
    return patched, {'replaced_pairs': 1, 'native_rows_preserved': len(native['entities']),
                     'prefix_bytes_preserved': len(prefix.encode()), 'suffix_bytes_preserved': len(suffix.encode())}


def with_configured_controls(source, configured):
    """Keep native supporting rows, expanding configured outputs without positional limits.

    Only the Outputs entities sequence is reserialized. Surrounding template bytes,
    expansion helper and native row actions remain intact.
    """
    root = yaml.compose(source)
    matches = []
    for sequence in _sequences(root):
        for index, header in enumerate(sequence.value):
            if _value(header, 'name') == 'Outputs' and _value(header, 'type') == 'custom:button-card':
                if index + 1 < len(sequence.value):
                    matches.append(sequence.value[index + 1])
    if len(matches) != 1:
        raise ValueError('Expected one Outputs detail for native controls.')
    detail = matches[0]
    card = _fields(detail).get('card')
    if _value(card, 'type') == 'custom:mod-card':
        card = _fields(card).get('card')
    if _value(card, 'type') != 'entities':
        raise ValueError('Expected preserved native entities card.')
    entities_node = _fields(card).get('entities')
    if not isinstance(entities_node, SequenceNode):
        raise ValueError('Expected native entity rows.')
    # PyYAML end marks can extend across comments up to the next sibling.
    # Keep those trailing lines outside the rows span before de-indentation;
    # otherwise a shallower footer comment becomes malformed bare YAML text.
    lines = source.splitlines(keepends=True)
    first = entities_node.start_mark.line
    last = entities_node.end_mark.line
    if last < len(lines) and lines[last][:entities_node.end_mark.column].strip():
        last += 1
    while last > first and (not lines[last - 1].strip() or lines[last - 1].lstrip().startswith('#')):
        last -= 1
    start = sum(map(len, lines[:first]))
    end = sum(map(len, lines[:last]))
    indent = entities_node.start_mark.column
    existing = yaml.safe_load(''.join(line[indent:] if line.strip() else line for line in lines[first:last]))
    inventory = list(dict.fromkeys(row['entity_id'] for row in configured))
    by_entity = {}
    supporting = []
    for row in existing:
        entity = row if isinstance(row, str) else row.get('entity') if isinstance(row, dict) else None
        if entity in inventory:
            by_entity.setdefault(entity, row)
        else:
            supporting.append(row)
    controls = []
    for entity in inventory:
        row = deepcopy(by_entity.get(entity, {'entity': entity}))
        if isinstance(row, dict):
            # Canonical templates have positional example names, not user labels.
            row.pop('name', None)
        controls.append(row)
    rows = controls + supporting
    rendered = yaml.safe_dump(rows, sort_keys=False, allow_unicode=True, width=10000)
    rendered = ''.join(' ' * indent + line if line.strip() else line for line in rendered.splitlines(keepends=True))
    return source[:start] + rendered + source[end:]


def render_output_card(source, configured, feed=None):
    """Pure CPU-bound generation; called through HA's executor."""
    native = with_configured_controls(source, configured)
    return wire_card(native, feed)[0] if feed else native
