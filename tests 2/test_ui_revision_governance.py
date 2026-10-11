"""Stdlib-only regression tests for the release UI revision maintenance check."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_ui_revision_governance.py"
spec = importlib.util.spec_from_file_location("ui_revision_governance", SCRIPT)
gov = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gov)


def metadata(revision=1, *, schema=1, generator=1, supersedes=()):
    return f"UI_REVISION_SCHEMA = {schema!r}\nUI_GENERATOR_CONTRACT = {generator!r}\nUI_LAYOUT_REVISIONS = {{'v2_mobile': {revision!r}, 'v2_tablet': {revision!r}}}\nUI_LAYOUT_SUPERSEDES: dict = {{'v2_mobile': {supersedes!r}, 'v2_tablet': {supersedes!r}}}\n"


class GovernanceTests(unittest.TestCase):
    def test_changed_layout_needs_its_own_increment(self):
        old = gov.parse_metadata(metadata())
        current = gov.parse_metadata(metadata(2, supersedes=(1,)))
        current['UI_LAYOUT_REVISIONS']['v2_tablet'] = 1
        current['UI_LAYOUT_SUPERSEDES']['v2_tablet'] = ()
        self.assertFalse(gov.compare(current, old, gov.LAYOUT_FILES['v2_mobile']))
        self.assertTrue(gov.compare(old, old, gov.LAYOUT_FILES['v2_mobile']))
        self.assertTrue(gov.compare(current, old, gov.LAYOUT_FILES['v2_tablet']))

    def test_shared_generator_changes_require_both_layouts(self):
        old = gov.parse_metadata(metadata())
        for path in gov.SHARED_FILES:
            self.assertEqual(len(gov.compare(old, old, [path])), 2)
            self.assertFalse(gov.compare(gov.parse_metadata(metadata(2)), old, [path]))

    def test_contract_change_requires_layout_increments_and_no_downgrades(self):
        old = gov.parse_metadata(metadata())
        for changes in ({'schema': 2}, {'generator': 2}):
            self.assertTrue(gov.compare(gov.parse_metadata(metadata(**changes)), old, []))
            newer = gov.parse_metadata(metadata(2, **changes))
            self.assertFalse(gov.compare(newer, old, []))
            self.assertTrue(gov.compare(old, newer, []))
        self.assertTrue(gov.compare(old, gov.parse_metadata(metadata(2)), []))

    def test_version_only_change_and_first_adoption_pass(self):
        old = gov.parse_metadata(metadata())
        self.assertFalse(gov.compare(old, old, ['custom_components/humidity_intelligence/manifest.json']))
        self.assertFalse(gov.compare(old, None, [*gov.SHARED_FILES]))

    def test_invalid_metadata_is_rejected_without_execution(self):
        for kwargs in ({'revision': True}, {'revision': 0}, {'schema': 0}, {'generator': -1}, {'supersedes': (1,)}, {'revision': 3, 'supersedes': (1,1)}, {'revision': 3, 'supersedes': (4,)}, {'revision': 3, 'supersedes': (True,)}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                gov.parse_metadata(metadata(**kwargs))
        with self.assertRaises(ValueError):
            gov.parse_metadata(metadata().replace('UI_REVISION_SCHEMA = 1', 'UI_REVISION_SCHEMA = __import__("os").system("false")'))

    def test_real_git_worktree_and_event_base_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            def git(*args):
                return subprocess.check_output(['git','-C',str(root),*args],text=True).strip()
            git('init','-q');git('config','user.email','test@example.invalid');git('config','user.name','Test')
            path = root / gov.METADATA;path.parent.mkdir(parents=True);path.write_text(metadata())
            template = root / gov.LAYOUT_FILES['v2_mobile'][0];template.parent.mkdir(parents=True);template.write_text('original\n')
            git('add','.');git('commit','-qm','baseline');baseline=git('rev-parse','HEAD')
            self.assertFalse(gov.check_repository(root,baseline))
            template.write_text('changed\n');self.assertTrue(gov.check_repository(root,baseline))
            path.write_text(metadata(2,supersedes=(1,)));self.assertFalse(gov.check_repository(root,baseline))
            git('add','.');git('commit','-qm','UI revision')
            event=root/'event.json'
            git('update-ref','refs/remotes/origin/main',baseline)
            for payload in ({'pull_request':{'base':{'sha':baseline}}}, {'before':baseline}, {'before':'0'*40,'repository':{'default_branch':'main'}}, {}):
                event.write_text(json.dumps(payload));self.assertEqual(gov.choose_base(root,event_path=event),baseline)
            git('commit','--allow-empty','-qm','unrelated follow-up')
            event.write_text(json.dumps({'before':'0'*40,'repository':{'default_branch':'main'}}))
            self.assertNotEqual(git('rev-parse','HEAD^'), baseline)
            self.assertEqual(gov.choose_base(root,event_path=event), baseline)
            event.write_text(json.dumps({'before':'0'*40,'repository':{'default_branch':'missing'}}))
            with self.assertRaises(ValueError):gov.choose_base(root,event_path=event)
            self.assertEqual(gov.choose_base(root,'HEAD',event), 'HEAD')
            with self.assertRaises(subprocess.CalledProcessError):gov.check_repository(root,'not-a-ref')

    def test_stamp_implementation_changes_require_both_layout_increments(self):
        original = metadata() + "def stamp_card():\n    return 'old'\n"
        bumped = metadata(2) + "def stamp_card():\n    return 'old'\n"
        altered = metadata() + "def stamp_card():\n    return 'new'\n"
        self.assertEqual(gov.implementation(original), gov.implementation(bumped))
        self.assertNotEqual(gov.implementation(original), gov.implementation(altered))
        old = gov.parse_metadata(original)
        self.assertEqual(len(gov.compare(gov.parse_metadata(altered), old, [gov.METADATA])), 2)
        self.assertFalse(gov.compare(gov.parse_metadata(bumped), old, [gov.METADATA]))

    def test_repository_without_historical_metadata_allows_adoption(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            gov.git(root,'init','-q');gov.git(root,'config','user.email','test@example.invalid');gov.git(root,'config','user.name','Test')
            (root/'README').write_text('prior package')
            gov.git(root,'add','.');gov.git(root,'commit','-qm','prior')
            path=root/gov.METADATA;path.parent.mkdir(parents=True);path.write_text(metadata())
            self.assertFalse(gov.check_repository(root,'HEAD'))


if __name__ == '__main__':
    unittest.main()
