"""Entry-local reusable display meanings; source rules and control stay separate."""
from copy import deepcopy
import re
import unicodedata
from uuid import uuid4

from .model import MEANING_LABELS, SEMANTICS

MAX_MEANINGS = 32
MAX_NAME = 80
MAX_INSTRUCTIONS = 240
MEANING_ID = re.compile(r'custom_[0-9a-f]{32}\Z')


def _name(value):
    if not isinstance(value, str):
        raise ValueError('invalid_meaning_name')
    name = unicodedata.normalize('NFKC', value).strip()
    if not 0 < len(name) <= MAX_NAME or any(unicodedata.category(c).startswith('C') for c in name):
        raise ValueError('invalid_meaning_name')
    return name


def _instructions(value):
    if not isinstance(value, str):
        raise ValueError('invalid_instructions')
    text = value.replace('\r\n', '\n').strip()
    if len(text) > MAX_INSTRUCTIONS or any(unicodedata.category(c).startswith('C') and c != '\n' for c in text):
        raise ValueError('invalid_instructions')
    return text


def validate_library(value):
    """Validate bounded definitions; names are literal text, never markup/code."""
    if not isinstance(value, dict) or len(value) > MAX_MEANINGS:
        raise ValueError('invalid_meanings')
    result = {}
    names = {unicodedata.normalize('NFKC', name).casefold() for name in MEANING_LABELS.values()}
    names |= {'add custom meaning…', 'add custom meaning...', 'add custom meaning'}
    for ident, row in value.items():
        if not isinstance(ident, str) or not MEANING_ID.fullmatch(ident) or not isinstance(row, dict) or not {'name', 'classification'} <= set(row) or set(row) - {'name', 'classification', 'instructions'}:
            raise ValueError('invalid_meanings')
        name = _name(row['name'])
        if name.casefold() in names:
            raise ValueError('duplicate_meaning_name')
        classification = row['classification']
        if not isinstance(classification, str) or classification not in SEMANTICS:
            raise ValueError('invalid_classification')
        names.add(name.casefold())
        result[ident] = {'name': name, 'classification': classification, 'instructions': _instructions(row.get('instructions', ''))}
    return result


def meaning_uses(settings, meaning_id):
    return [deepcopy(row) for row in settings.get('confirmations', []) if row.get('custom_meaning_id') == meaning_id]


def save_meaning(settings, name, classification, meaning_id=None, *, instructions=""):
    """Pure staged update: compatibility semantic changes atomically with library."""
    from .mappings import section
    result = section(settings)
    library = result['custom_meanings']
    if meaning_id is not None and meaning_id not in library:
        raise ValueError('unknown_meaning')
    if meaning_id is None:
        if len(library) >= MAX_MEANINGS:
            raise ValueError('meaning_limit')
        meaning_id = 'custom_' + uuid4().hex
    library[meaning_id] = {'name': name, 'classification': classification, 'instructions': instructions}
    result['custom_meanings'] = validate_library(library)
    for row in result['confirmations']:
        if row.get('custom_meaning_id') == meaning_id:
            row['semantic'] = classification
    return section(result)


def delete_meaning(settings, meaning_id, replacement=None, remove_uses=False):
    """Require an explicit replacement/removal decision; never delete dangling uses."""
    from .mappings import section
    result = section(settings)
    library = result['custom_meanings']
    if meaning_id not in library:
        raise ValueError('unknown_meaning')
    uses = meaning_uses(result, meaning_id)
    if type(remove_uses) is not bool or (replacement is not None and remove_uses):
        raise ValueError('invalid_replacement')
    if replacement is not None and (not isinstance(replacement, str) or replacement == meaning_id or replacement not in SEMANTICS and replacement not in library):
        raise ValueError('invalid_replacement')
    if uses and replacement is None and not remove_uses:
        raise ValueError('meaning_in_use')
    rows = []
    for row in result['confirmations']:
        if row.get('custom_meaning_id') == meaning_id:
            if remove_uses:
                continue
            if replacement in library:
                row['custom_meaning_id'] = replacement
                row['semantic'] = library[replacement]['classification']
            else:
                row.pop('custom_meaning_id', None)
                row['semantic'] = replacement
        rows.append(row)
    result['confirmations'] = rows
    del library[meaning_id]
    return section(result)
