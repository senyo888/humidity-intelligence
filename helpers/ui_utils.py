"""UI helper functions for Humidity Intelligence.

This module contains functions for handling UI assets, including
substituting real entity IDs into dashboard YAML and registering
predefined cards with the Lovelace dashboard.  Only stubs are provided
here; implementation will be added in a future iteration.
"""

from __future__ import annotations

import logging
from typing import Dict

_LOGGER = logging.getLogger(__name__)


def substitute_entities(yaml_str: str, mapping: Dict[str, str]) -> str:
    """Replace placeholder entity IDs in a YAML string with real IDs.

    :param yaml_str: The YAML template containing placeholders
    :param mapping: A mapping from placeholder names to actual entity IDs
    :return: A YAML string with placeholders replaced
    """
    for placeholder, entity_id in mapping.items():
        yaml_str = yaml_str.replace(placeholder, entity_id)
    return yaml_str