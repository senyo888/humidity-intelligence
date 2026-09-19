"""Load the tracked pure observer modules without importing Home Assistant setup."""
from importlib import import_module
from pathlib import Path
import sys
from types import ModuleType

INTEGRATION_ROOT = Path(__file__).resolve().parents[1] / 'custom_components/humidity_intelligence/adaptive_output'
PACKAGE = '_hi_adaptive_pure_contract_tests'
package = ModuleType(PACKAGE)
package.__path__ = [str(INTEGRATION_ROOT)]
sys.modules[PACKAGE] = package
model = import_module(f'{PACKAGE}.model')
normalize, MAX_CONFIG, MAX_TEXT = model.normalize, model.MAX_CONFIG, model.MAX_TEXT
extract_configured = import_module(f'{PACKAGE}.config_adapter').extract_configured
discovery = import_module(f'{PACKAGE}.discovery')
discover, identity = discovery.discover, discovery.identity
DiscoverySession = import_module(f'{PACKAGE}.observer').DiscoverySession
