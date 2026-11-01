"""Delete a saved part, and remove a component file, without a geometry build."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from steve_desktop.cad_server import LocalCadServer
from steve_desktop.cad_service import cad_tools


SCREW = 'from steve import Component\n\nscrew = Component("screw", name="Screw")\n'
NUT = 'from steve import Component\nfrom components.screw import screw\n\nnut = Component("nut", name="Nut")\n'
SCREW_USES_NUT = 'from steve import Component\nfrom components.nut import nut\n\nscrew = Component("screw", name="Screw")\n'

PLACED = '''from steve import Design
from components.screw import screw
design = Design()
design.add(screw)
result = design.result()
'''

PATTERN = '''from steve import Design
from components.screw import screw
design = Design()
design.pattern(screw, count=4, axis="Z")
result = design.result()
'''

JOINT = '''from steve import Design
from components.screw import screw
design = Design()
design.pattern(screw, count=4, axis="Z")
design.revolute("hinge", screw.face("head"), screw.face("tip"))
result = design.result()
'''


class DeleteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.server = LocalCadServer(self.temp.name)
        self.client = TestClient(self.server.app, headers={'x-steve-session': self.server.token})

    def tearDown(self):
        self.client.close()
        self.server.close()
        self.temp.cleanup()

    def design(self, code, files, name='Hardware'):
        return self.client.post('/v1/documents', json={
            'name': name, 'kind': 'design', 'code': code, 'files': files, 'links': {},
        }).json()

    def part(self, name='Bracket'):
        return self.client.post('/v1/documents', json={
            'name': name, 'kind': 'part', 'code': 'result = None\n', 'files': {}, 'links': {},
        }).json()

    def test_trash_hides_a_part_and_restore_brings_it_back_without_a_new_revision(self):
        doc = self.part()
        saved = self.client.put('/v1/documents/' + doc['id'], json={**doc, 'name': 'Bracket 2'}).json()
        history = list(self.server.state['history'][doc['id']])
        self.client.post('/v1/trash', json={'ids': [doc['id']]})
        self.assertEqual(self.client.get('/v1/documents').json()['documents'], [])
        stored = self.server.state['documents'][doc['id']]
        self.assertEqual(stored['revision'], saved['revision'])
        self.assertEqual(self.server.state['history'][doc['id']], history)
        self.client.post('/v1/trash/restore', json={'ids': [doc['id']]})
        listed = self.client.get('/v1/documents').json()['documents']
        self.assertEqual([item['id'] for item in listed], [doc['id']])
        self.assertNotIn('deleted_at', self.server.state['documents'][doc['id']])

    def test_purge_removes_history_and_empty_trash_skips_a_second_time(self):
        gone = self.part('Gone')
        kept = self.part('Kept')
        self.client.post('/v1/trash', json={'ids': [gone['id']]})
        self.server.state.setdefault('history', {}).setdefault(gone['id'], []).append({'revision': 0})
        (self.server.folder / 'documents' / gone['id']).mkdir(parents=True, exist_ok=True)
        purged = self.client.post('/v1/trash/purge', json={'ids': [gone['id'], kept['id']]}).json()
        self.assertEqual([item['id'] for item in purged['purged']], [gone['id']])
        self.assertEqual(purged['skipped'][0]['id'], kept['id'])
        self.assertNotIn(gone['id'], self.server.state['documents'])
        self.assertNotIn(gone['id'], self.server.state.get('history', {}))
        self.assertFalse((self.server.folder / 'documents' / gone['id']).exists())
        again = self.client.post('/v1/trash/purge', json={'ids': [gone['id']]}).json()
        self.assertEqual(again['purged'], [])
        self.assertEqual(again['skipped'][0]['id'], gone['id'])
        self.client.post('/v1/trash', json={'ids': [kept['id']]})
        emptied = self.client.post('/v1/trash/empty', json={}).json()
        self.assertEqual([item['id'] for item in emptied['purged']], [kept['id']])
        self.assertEqual(self.client.get('/v1/trash').json()['documents'], [])

    def test_purge_refuses_while_a_live_design_links_the_part_even_if_asked_to_force(self):
        bracket = self.part('Bracket')
        self.client.post('/v1/documents', json={
            'name': 'Assembly', 'kind': 'design', 'code': 'from links import bracket\n',
            'files': {}, 'links': {'bracket': {'document_id': bracket['id'], 'revision': 1}},
        })
        self.client.post('/v1/trash', json={'ids': [bracket['id']]})
        refused = self.client.post('/v1/trash/purge', json={'ids': [bracket['id']], 'force': True}).json()
        self.assertEqual(refused['purged'], [])
        self.assertEqual(refused['skipped'][0]['id'], bracket['id'])
        self.assertIn(bracket['id'], self.server.state['documents'])
        status = self.client.get('/v1/documents/' + next(iter(
            doc['id'] for doc in self.server.state['documents'].values() if doc['name'] == 'Assembly'))).json()
        self.assertTrue(status['link_status']['bracket']['trashed'])
        self.assertEqual(status['link_status']['bracket']['latest'], 1)

    def test_remove_placed_component_file_is_a_new_revision_and_history_keeps_it(self):
        doc = self.design(PLACED, {'components/screw.py': SCREW})
        removed = self.client.post(f"/v1/documents/{doc['id']}/files/delete", json={
            'paths': ['components/screw.py'], 'revision': doc['revision'],
        }).json()
        saved = removed['document']
        self.assertEqual(saved['revision'], doc['revision'] + 1)
        self.assertNotIn('components/screw.py', saved['files'])
        self.assertNotIn('components.screw', saved['code'])
        self.assertNotIn('design.add(screw)', saved['code'])
        self.assertIn('from steve import Design', saved['code'])
        previous = self.server.state['history'][doc['id']][-1]
        self.assertIn('components/screw.py', previous['files'])
        self.assertIn('Removed components/screw.py', saved['message'])

    def test_remove_empty_component_file(self):
        doc = self.design('from steve import Design\ndesign = Design()\nresult = design.result()\n',
                          {'components/washer.py': ''})
        removed = self.client.post(f"/v1/documents/{doc['id']}/files/delete", json={
            'paths': ['components/washer.py'], 'revision': doc['revision'],
        }).json()
        self.assertNotIn('components/washer.py', removed['document']['files'])
        self.assertEqual(removed['document']['revision'], 2)
        self.assertIn('components/washer.py', self.server.state['history'][doc['id']][-1]['files'])

    def test_mutual_component_files_delete_together_and_one_alone_refuses(self):
        doc = self.design(
            'from steve import Design\nfrom components.screw import screw\nfrom components.nut import nut\n'
            'design = Design()\ndesign.add(screw)\ndesign.add(nut)\nresult = design.result()\n',
            {'components/screw.py': SCREW_USES_NUT, 'components/nut.py': NUT})
        alone = self.client.post(f"/v1/documents/{doc['id']}/files/delete", json={
            'paths': ['components/screw.py'], 'revision': doc['revision'],
        })
        self.assertEqual(alone.status_code, 422)
        self.assertTrue(alone.json()['detail']['references'])
        self.assertIn('components/screw.py', self.client.get(f"/v1/documents/{doc['id']}").json()['files'])
        both = self.client.post(f"/v1/documents/{doc['id']}/files/delete", json={
            'paths': ['components/nut.py', 'components/screw.py'], 'revision': doc['revision'],
        })
        self.assertEqual(both.status_code, 200, both.text)
        self.assertEqual(both.json()['document']['files'], {})

    def test_pattern_is_removed_and_a_joint_refuses_unless_the_ui_forces_it(self):
        patterned = self.design(PATTERN, {'components/screw.py': SCREW}, name='Patterned')
        ok = self.client.post(f"/v1/documents/{patterned['id']}/files/delete", json={
            'paths': ['components/screw.py'], 'revision': patterned['revision'],
        })
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertNotIn('design.pattern', ok.json()['document']['code'])
        jointed = self.design(JOINT, {'components/screw.py': SCREW}, name='Jointed')
        refused = self.client.post(f"/v1/documents/{jointed['id']}/files/delete", json={
            'paths': ['components/screw.py'], 'revision': jointed['revision'],
        })
        self.assertEqual(refused.status_code, 422)
        self.assertTrue(any('revolute' in item['detail'] for item in refused.json()['detail']['references']))
        self.assertIn('components/screw.py', self.client.get(f"/v1/documents/{jointed['id']}").json()['files'])
        forced = self.client.post(f"/v1/documents/{jointed['id']}/files/delete", json={
            'paths': ['components/screw.py'], 'revision': jointed['revision'], 'force': True,
        })
        self.assertEqual(forced.status_code, 200, forced.text)
        saved = forced.json()['document']
        self.assertNotIn('components/screw.py', saved['files'])
        self.assertNotIn('design.pattern', saved['code'])
        self.assertIn('design.revolute', saved['code'])
        self.assertTrue(any('revolute' in item for item in forced.json()['warnings']))

    def test_stale_revision_and_unsaved_context_do_not_write(self):
        doc = self.design(PLACED, {'components/screw.py': SCREW})
        stale = self.client.post(f"/v1/documents/{doc['id']}/files/delete", json={
            'paths': ['components/screw.py'], 'revision': doc['revision'] + 9,
        })
        self.assertEqual(stale.status_code, 409)
        self.assertIn('components/screw.py', self.client.get(f"/v1/documents/{doc['id']}").json()['files'])
        dirty = dict(doc)
        dirty['code'] = doc['code'] + '# dirty\n'
        self.server.context = {
            'document': {'name': doc['name'], 'kind': doc['kind'], 'code': dirty['code'],
                         'files': doc['files'], 'links': {}},
            'document_id': doc['id'], 'build_id': None, 'selection': [],
        }
        blocked = self.client.post(f"/v1/documents/{doc['id']}/files/delete", json={
            'paths': ['components/screw.py'], 'revision': doc['revision'],
        })
        self.assertEqual(blocked.status_code, 409)
        self.assertIn('components/screw.py', self.server.state['documents'][doc['id']]['files'])
        sent = self.client.post(f"/v1/documents/{doc['id']}/files/delete", json={
            'paths': ['components/screw.py'], 'revision': doc['revision'],
            'code': dirty['code'], 'files': doc['files'],
        })
        self.assertEqual(sent.status_code, 200, sent.text)
        self.assertIn('# dirty', sent.json()['document']['code'])
        self.assertNotIn('components/screw.py', sent.json()['document']['files'])

    def test_history_restore_brings_the_component_file_back(self):
        doc = self.design(PLACED, {'components/screw.py': SCREW})
        removed = self.client.post(f"/v1/documents/{doc['id']}/files/delete", json={
            'paths': ['components/screw.py'], 'revision': doc['revision'],
        }).json()['document']
        restored = self.client.post(f"/v1/documents/{doc['id']}/history/restore", json={
            'revision': removed['revision'], 'commit_id': str(doc['revision']),
        })
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertIn('components/screw.py', restored.json()['document']['files'])
        self.assertEqual(restored.json()['document']['revision'], removed['revision'] + 1)

    def test_mcp_remove_file_refuses_a_joint_and_rejects_purge(self):
        doc = self.design(JOINT, {'components/screw.py': SCREW})
        toolset = cad_tools(self.temp.name, None, lambda _text: None)
        tool = toolset.tools['cad_delete']
        schema = tool.function_schema.json_schema
        properties = schema['properties']
        self.assertNotIn('force', properties)
        self.assertNotIn('purge', properties)
        self.assertNotIn('empty', properties)
        self.assertNotIn('empty_trash', properties)
        mode = properties['mode']
        values = set(mode.get('enum') or [])
        for option in mode.get('anyOf', []):
            if 'const' in option:
                values.add(option['const'])
            values.update(option.get('enum') or [])
        self.assertEqual(values, {'trash', 'restore', 'remove_file'})
        with self.assertRaises(ValidationError):
            tool.function_schema.validator.validate_python({'mode': 'purge', 'document_id': doc['id']})
        with self.assertRaises(ValidationError):
            tool.function_schema.validator.validate_python({'mode': 'empty_trash', 'document_id': doc['id']})
        rejected = tool.function(mode='purge', document_id=doc['id'])
        self.assertFalse(rejected['ok'])
        self.assertIn(doc['id'], self.server.state['documents'])
        self.assertNotIn('deleted_at', self.server.state['documents'][doc['id']])
        refused = tool.function(mode='remove_file', document_id=doc['id'],
                                path='components/screw.py', expected_revision=doc['revision'])
        self.assertFalse(refused['ok'])
        self.assertEqual(refused['action'], 'refused')
        self.assertTrue(refused['references'])
        self.assertIn('components/screw.py', self.server.state['documents'][doc['id']]['files'])
        trashed = tool.function(mode='trash', document_id=doc['id'])
        self.assertTrue(trashed['ok'])
        self.assertEqual(trashed['action'], 'trashed')
        self.assertEqual(self.server.state['documents'][doc['id']]['revision'], doc['revision'])
        restored = tool.function(mode='restore', document_id=doc['id'])
        self.assertTrue(restored['ok'])
        self.assertNotIn('deleted_at', self.server.state['documents'][doc['id']])

    def test_git_export_skips_trash_and_unlinks_a_removed_component_without_pushing(self):
        doc = self.design(PLACED, {'components/screw.py': SCREW})
        root = Path(self.temp.name) / 'repo'
        root.mkdir()
        item = {'path': str(root), 'owned_files': [], 'token': ''}
        with patch('steve_desktop.local_git.subprocess.run', side_effect=AssertionError('git must not run')):
            self.server.local_git.export_sources(item)
            self.assertTrue((root / doc['id'] / 'components' / 'screw.py').is_file())
            self.client.post(f"/v1/documents/{doc['id']}/files/delete", json={
                'paths': ['components/screw.py'], 'revision': doc['revision'],
            })
            self.server.local_git.export_sources(item)
            self.assertFalse((root / doc['id'] / 'components' / 'screw.py').exists())
            self.assertTrue((root / doc['id'] / 'main.py').is_file())
            self.client.post('/v1/trash', json={'ids': [doc['id']]})
            self.server.local_git.export_sources(item)
            self.assertFalse((root / doc['id'] / 'main.py').exists())


if __name__ == '__main__':
    unittest.main()
