"""Keep release emphasis separate from product identity and human-owned notes."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("presentation_contract", ROOT / "scripts/check_release_presentation.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_owned_presentation_contract_is_preserved():
    assert module.check_sources(ROOT) == []


def test_reserved_notes_survive_agent_summary_changes():
    before = "## Summary\nOld\n\n## Maintainer notes\n\nSenyo's own note.\n\n## Checks\nPending\n"
    after = before.replace("Old", "Updated summary").replace("Pending", "Checked")
    assert module.check_pr_notes(after, before) == []
    assert module.check_pr_notes(after.replace("Senyo's own note.", "Agent says passed."), before)
    assert module.check_pr_notes(after.replace("## Maintainer notes", "## Maintenance evidence"), before)


def test_empty_notes_keep_the_reserved_template_marker():
    assert module.check_pr_notes("## Maintainer notes\n\n" + module.RESERVED + "\n") == []
    assert module.check_pr_notes("## Maintainer notes\n\n## Checks\n")


def test_duplicate_owned_notes_are_rejected():
    body = "## Maintainer notes\n\n" + module.RESERVED + "\n"
    assert module.check_pr_notes(body + "\n" + body)
