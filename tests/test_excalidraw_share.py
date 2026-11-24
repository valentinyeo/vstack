#!/usr/bin/env python3
import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'skills/excalidraw/excalidraw-share'
EXAMPLE = ROOT / 'skills/excalidraw/example.excalidraw'
KEY = 'sk-test-key-do-not-log'

DRAWING = {
    'type': 'excalidraw',
    'version': 2,
    'source': 'https://excalidraw.com',
    'elements': [
        {'id': 'a', 'type': 'rectangle', 'x': 0, 'y': 0, 'width': 100, 'height': 60},
        {'id': 'b', 'type': 'arrow', 'x': 100, 'y': 30, 'width': 80, 'height': 0,
         'startBinding': {'elementId': 'a', 'fixedPoint': [0.5, 0.5], 'mode': 'orbit'},
         'endBinding': {'elementId': 'c', 'fixedPoint': [0.5, 0.5], 'mode': 'orbit'}},
        {'id': 'c', 'type': 'text', 'x': 180, 'y': 10, 'width': 80, 'height': 20,
         'text': 'hello'},
    ],
    'appState': {},
    'files': {},
}


def load_module():
    loader = importlib.machinery.SourceFileLoader('excalidraw_share', str(SCRIPT))
    spec = importlib.util.spec_from_loader('excalidraw_share', loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class FakeApi:
    def __init__(self, failed=None):
        self.calls = []
        self.failed = failed
        self.scene_id = 'Scene1'

    def __call__(self, request, timeout=None):
        body = json.loads(request.data.decode()) if request.data else None
        self.calls.append((request.get_method(), request.full_url, body,
                           dict(request.headers)))
        if self.failed and self.failed in request.full_url:
            from urllib.error import HTTPError
            raise HTTPError(request.full_url, 401, 'Unauthorized', {},
                            io.BytesIO(b'{"error":"nope"}'))
        payload = json.dumps({'metadata': {'id': self.scene_id}}).encode()
        return io.BytesIO(payload)


class ShareTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.module = load_module()
        self.api = FakeApi()
        self.module.urlopen = self.api
        self.key_reads = 0

        def fake_key():
            self.key_reads += 1
            return KEY

        self.module.read_key = fake_key

    def write(self, data, name='drawing.excalidraw'):
        path = self.dir / name
        path.write_text(json.dumps(data), encoding='utf-8')
        return path

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with patch('sys.stdout', out), patch('sys.stderr', err):
            code = self.module.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_create_fill_share_in_order(self):
        path = self.write(DRAWING)
        code, out, err = self.run_main(str(path), '--name', 'How it ships')
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(out.strip(),
                         'https://app.excalidraw.com/s/1GorMHPWnnO/Scene1')
        methods = [(method, url.split('/api/v1')[-1]) for method, url, _, _ in self.api.calls]
        self.assertEqual(methods, [
            ('POST', '/collections/8nmjwOyvh62/scenes'),
            ('PUT', '/scenes/Scene1/content'),
            ('PUT', '/scenes/Scene1/link-sharing'),
        ])
        self.assertEqual(self.api.calls[0][2], {'name': 'How it ships'})
        self.assertEqual(self.api.calls[2][2], {'access': 'view'})
        for _, _, _, headers in self.api.calls:
            self.assertEqual(headers.get('Authorization'), 'Bearer ' + KEY)

    def test_scene_name_defaults_to_file_name(self):
        path = self.write(DRAWING, 'Fleet flow.excalidraw')
        self.assertEqual(self.run_main(str(path))[0], 0)
        self.assertEqual(self.api.calls[0][2], {'name': 'Fleet flow'})

    def test_missing_indices_are_filled_in_document_order(self):
        self.write(DRAWING)
        self.assertEqual(self.run_main(str(self.dir / 'drawing.excalidraw'))[0], 0)
        content = self.api.calls[1][2]
        self.assertEqual([element['index'] for element in content['elements']],
                         ['a0', 'a1', 'a2'])
        self.assertEqual(content['type'], 'excalidraw')
        self.assertEqual(content['version'], 2)
        self.assertEqual(content['appState']['viewBackgroundColor'], '#ffffff')
        self.assertEqual(content['files'], {})

    def test_existing_indices_are_kept(self):
        drawing = json.loads(json.dumps(DRAWING))
        for position, element in enumerate(drawing['elements']):
            element['index'] = 'b%02d' % position
        self.write(drawing)
        self.assertEqual(self.run_main(str(self.dir / 'drawing.excalidraw'))[0], 0)
        content = self.api.calls[1][2]
        self.assertEqual([element['index'] for element in content['elements']],
                         ['b00', 'b01', 'b02'])

    def test_index_order_stays_lexicographic_past_a_z(self):
        indices = [self.module.fractional_index(n) for n in range(200)]
        self.assertEqual(indices[:3], ['a0', 'a1', 'a2'])
        self.assertEqual(indices[10], 'aA')
        self.assertEqual(indices[61], 'az')
        self.assertEqual(indices[62], 'b00')
        self.assertEqual(indices, sorted(indices))
        self.assertEqual(len(set(indices)), len(indices))

    def test_scene_flag_updates_instead_of_creating(self):
        self.write(DRAWING)
        code, out, _ = self.run_main(str(self.dir / 'drawing.excalidraw'),
                                     '--scene', 'Existing9')
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(),
                         'https://app.excalidraw.com/s/1GorMHPWnnO/Existing9')
        self.assertEqual([call[0] for call in self.api.calls], ['PUT', 'PUT'])
        self.assertTrue(self.api.calls[0][1].endswith('/scenes/Existing9/content'))

    def test_bare_element_list_is_accepted(self):
        self.write(DRAWING['elements'], 'list.json')
        self.assertEqual(self.run_main(str(self.dir / 'list.json'))[0], 0)
        self.assertEqual(len(self.api.calls[1][2]['elements']), 3)

    def test_key_is_read_once_and_never_printed(self):
        self.write(DRAWING)
        code, out, err = self.run_main(str(self.dir / 'drawing.excalidraw'))
        self.assertEqual(code, 0)
        self.assertEqual(self.key_reads, 1)
        self.assertNotIn(KEY, out + err)
        self.assertNotIn('Bearer', out + err)

    def test_api_error_exits_non_zero_with_one_plain_line(self):
        self.module.urlopen = FakeApi(failed='/content')
        self.write(DRAWING)
        code, out, err = self.run_main(str(self.dir / 'drawing.excalidraw'))
        self.assertEqual(code, 1)
        self.assertEqual(out, '')
        self.assertEqual(len(err.strip().splitlines()), 1)
        self.assertIn('HTTP 401', err)
        self.assertNotIn(KEY, err)
        self.assertNotIn('Traceback', err)

    def test_missing_file_exits_non_zero(self):
        code, out, err = self.run_main(str(self.dir / 'nope.excalidraw'))
        self.assertEqual(code, 1)
        self.assertEqual(out, '')
        self.assertEqual(len(err.strip().splitlines()), 1)

    def test_file_without_elements_exits_non_zero(self):
        self.write({'type': 'excalidraw', 'elements': []})
        code, _, err = self.run_main(str(self.dir / 'drawing.excalidraw'))
        self.assertEqual(code, 1)
        self.assertEqual(len(err.strip().splitlines()), 1)

    def test_broken_json_exits_non_zero(self):
        path = self.dir / 'bad.json'
        path.write_text('{not json', encoding='utf-8')
        code, _, err = self.run_main(str(path))
        self.assertEqual(code, 1)
        self.assertEqual(len(err.strip().splitlines()), 1)

    def test_the_shipped_example_is_a_working_document(self):
        scene = self.module.document(json.loads(EXAMPLE.read_text(encoding='utf-8')))
        self.assertTrue(scene['elements'])
        self.assertTrue(all(element['index'] for element in scene['elements']))
        types = {element['type'] for element in scene['elements']}
        self.assertTrue({'rectangle', 'arrow', 'text'} <= types)


class KeyCommandTest(unittest.TestCase):
    def test_reads_the_credential_with_xdg_runtime_dir(self):
        module = load_module()
        calls = []

        def fake_run(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, KEY + '\n', '')

        with patch.object(subprocess, 'run', fake_run), \
                patch.dict(os.environ, {}, clear=False):
            os.environ.pop('XDG_RUNTIME_DIR', None)
            self.assertEqual(module.read_key(), KEY)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], ['yeo-key', 'Excalidraw', 'credential'])
        self.assertEqual(calls[0][1]['env']['XDG_RUNTIME_DIR'],
                         '/run/user/%d' % os.getuid())

    def test_a_failing_yeo_key_exits_non_zero_with_one_plain_line(self):
        module = load_module()
        with patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess(
                ['yeo-key'], 1, '', 'yeo-key: op-cache failed')), \
                patch('sys.stderr', io.StringIO()) as err, patch('sys.stdout', io.StringIO()):
            code = module.main([str(EXAMPLE)])
        self.assertEqual(code, 1)
        self.assertEqual(len(err.getvalue().strip().splitlines()), 1)
        self.assertIn('op-cache failed', err.getvalue())


if __name__ == '__main__':
    unittest.main()
