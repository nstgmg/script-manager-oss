import contextlib
import http.client
import io
import json
import tempfile
import threading
import unittest
from unittest.mock import patch

from dashboard.server import Dashboard
from runner.__main__ import main
from runner.common import ManagerError
from runner.dashboard_run import DashboardRun
from runner.execution import Execution
from tests.test_parameters import definitions, MOCK_SCRIPT
from runner.store import default_job
import sys


class ParameterHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.server = Dashboard(self.temp.name, 0)
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=.01), daemon=True)
        self.thread.start()
        self.base = 'http://127.0.0.1:' + str(self.server.server_port)
        self.client = DashboardRun(self.temp.name, self.base)
        self.server.store.create(dict(default_job('sample'), command=[sys.executable, 'main.py'], parameters=definitions()))
        (self.server.store.job_dir('sample') / 'main.py').write_text(MOCK_SCRIPT)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, body, headers=None, path='/api/jobs/sample/runs', raw=False):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        actual = {'X-CSRF-Token': self.server.token, 'Origin': self.base, 'Content-Type': 'application/json'}
        actual.update(headers or {})
        conn.request('POST', path, body if raw else json.dumps(body), actual)
        response = conn.getresponse()
        value = json.load(response)
        status = response.status
        conn.close()
        return status, value

    def test_dashboard_payload_api_and_cli_apply_identical_values(self):
        values = {'text': '한글 ; $(echo literal)', 'day': '2026-11-13', 'count': 3, 'enabled': False}
        with patch('runner.execution.subprocess.Popen') as spawn:
            # Hold the detached worker to inspect API acceptance then run via CLI below.
            spawn.return_value.wait.return_value = 0
            status, accepted = self.request({'parameters': values})
        self.assertEqual(status, 202, accepted)
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            code = main(['--root', self.temp.name, 'run', 'sample', '--wait', '--parameters', json.dumps(values)])
        self.assertEqual(code, 0, output.getvalue())
        result = json.loads(output.getvalue())
        self.assertEqual(result['parameters'], accepted['parameters'])
        self.assertEqual(result['resolved_command'], accepted['resolved_command'])
        self.assertEqual(result['parameter_contract_version'], accepted['parameter_contract_version'])

    def test_run_dashboard_cli_transmits_waits_and_resumes_same_run(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            code = main(['--root', self.temp.name, 'run-dashboard', 'sample', '--url', self.base,
                         '--poll-seconds', '.1', '--parameters', '{"text":"cli","verbose":true}'])
        result = json.loads(output.getvalue())
        self.assertEqual(code, 0, result)
        self.assertTrue(result['success'])
        self.assertEqual(result['parameters']['text'], 'cli')
        self.assertIn('--verbose', json.loads(result['logs']['stdout']['text'])['argv'])
        resumed = self.client.run('sample', run_id=result['run_id'], poll_seconds=.1)
        self.assertEqual(resumed['parameters'], result['parameters'])
        self.assertNotIn('submit', [item['stage'] for item in self.client.metrics])
        with self.assertRaises(ManagerError):
            self.client.run('sample', run_id=result['run_id'], parameters={})
        self.assertEqual(len(Execution(self.server.store).list('sample')), 1)

    def test_invalid_http_and_client_inputs_never_run_or_expose_values(self):
        for body in ({'parameters': None}, {'parameters': []}, {'parameters': {'text': 'x', 'count': '3'}},
                     {'parameters': {'text': 'x', 'count': 8}}, {'parameters': {}},
                     {'parameters': {'api_key': 'sentinel-private-value'}},
                     {'parameters': {'text': 'x'}, 'command': ['echo', 'no']}):
            with self.subTest(body=body), patch('runner.execution.subprocess.Popen') as spawn:
                status, error = self.request(body)
                self.assertEqual(status, 400, error)
                self.assertNotIn('sentinel-private-value', json.dumps(error))
                spawn.assert_not_called()
        bad = self.client.run('sample', parameters={'text': 'x', 'count': '3'})
        self.assertFalse(bad['success'])
        self.assertIn('integer', bad['observation_error'])
        self.assertNotIn('submit', [item['stage'] for item in self.client.metrics])
        self.assertEqual(Execution(self.server.store).list('sample'), [])

    def test_parameter_requests_preserve_host_origin_csrf_checks(self):
        for headers in ({'X-CSRF-Token': ''}, {'Origin': 'https://evil.test'}, {'Host': 'evil.test'}):
            self.assertEqual(self.request({'parameters': {'text': 'x'}}, headers)[0], 403)
        self.assertEqual(Execution(self.server.store).list('sample'), [])

    def test_duplicate_keys_and_invalid_json_never_submit(self):
        for raw in ('{"parameters":{"text":"x","count":2,"count":3}}',
                    '{"parameters":{"text":"x","ratio":NaN}}',
                    '{"parameters":{"text":"sentinel-private-value",', 'null'):
            status, error = self.request(raw, raw=True)
            self.assertEqual(status, 400)
            self.assertNotIn('sentinel-private-value', json.dumps(error))
        self.assertEqual(Execution(self.server.store).list('sample'), [])


if __name__ == '__main__':
    unittest.main()
