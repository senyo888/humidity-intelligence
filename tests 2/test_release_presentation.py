"""Keep release emphasis separate from product identity and human-owned notes."""
import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest

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


@pytest.mark.parametrize("fence", ["```", "~~~~", "   ````"])
def test_fenced_example_cannot_replace_the_real_owned_section(fence):
    example = fence + "markdown\n## Maintainer notes\nExample only.\n" + fence + "\n\n"
    owned = "## Maintainer notes\n\nSenyo's note.\n\n## Checks\nPending\n"
    before = example + owned
    assert module.check_pr_notes(before, before) == []
    assert module.notes_block(before) == "\nSenyo's note.\n\n"
    assert module.check_pr_notes(example, before)
    assert module.check_pr_notes(before.replace("Senyo's note.", "Changed."), before)


def test_fenced_heading_does_not_end_the_owned_block():
    body = "## Maintainer notes\nMy example:\n```markdown\n## Checks\nOwned text\n```\n\n## Checks\nDone\n"
    assert "Owned text" in module.notes_block(body)
    assert module.check_pr_notes(body.replace("Owned text", "Changed"), body)


@pytest.mark.parametrize("heading", ["## Maintainer notes", "  ## Maintainer notes ##\r\n"])
def test_end_of_file_heading_is_present_but_needs_reserved_marker(heading):
    assert module.notes_block(heading) == ""
    assert module.check_pr_notes(heading) == ["Blank Maintainer notes must retain the reserved template marker."]


def test_shorter_fence_does_not_close_an_example():
    body = "````markdown\n```\n## Maintainer notes\nExample\n````\n"
    assert module.notes_block(body) is None
    assert module.check_pr_notes(body)


def test_source_check_is_independent_of_legacy_default_encoding():
    original = Path.read_text

    def legacy_read(path, *args, **kwargs):
        kwargs.setdefault("encoding", "cp1252")
        return original(path, *args, **kwargs)

    with patch.object(Path, "read_text", legacy_read):
        assert module.check_sources(ROOT) == []
