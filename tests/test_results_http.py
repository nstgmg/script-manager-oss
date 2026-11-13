import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from dashboard.server import Dashboard
from runner.common import write_json
from runner.store import default_job


class ResultsHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.server = Dashboard(self.temp.name, 0)
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=.01), daemon=True)
        self.thread.start()
        self.server.store.create(default_job('support', '지원사업'))
        self.run = 'a' * 32
        base = 'runtime/job-data/support/output/' + self.run
        write_json(Path(self.temp.name) / base / 'report.json', {
            'generated_at': '2020-01-01T00:00:00Z', 'complete': False,
            'announcements': [{'title': '용인 AI', 'source': 'source-b', 'deadline': {'status': '모집 중'}},
                              {'title': '서울 교육', 'source': 'source-a', 'deadline': {'status': '확인 필요'}}]})
        write_json(Path(self.temp.name) / 'runtime/runs/support' / self.run / 'run.json', {
            'id': self.run, 'job_id': 'support', 'state': 'failed',
            'created_at': '2020-01-01T00:00:00Z', 'managed_output': base})

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, path):
        client = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        client.request('GET', path)
        response = client.getresponse()
        result = response.status, json.loads(response.read())
        client.close()
        return result

    def test_catalog_and_filtered_results_have_provenance_and_warnings(self):
        with patch('runner.execution.Execution.start', side_effect=AssertionError('must not start')):
            status, result = self.request('/api/results/jobs?' + urlencode({'keyword': '지원'}))
            self.assertEqual(status, 200)
            self.assertEqual(result['jobs'][0]['last_run']['id'], self.run)
            query = urlencode([('keyword', '용인'), ('keyword', 'AI'), ('status', '모집 중'),
                               ('source', 'source-b'), ('from', '2020-01-01'), ('to', '2020-01-01')])
            status, result = self.request('/api/jobs/support/results?' + query)
        self.assertEqual(status, 200)
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['items'][0]['provenance']['run_id'], self.run)
        self.assertTrue(result['items'][0]['stale'])
        self.assertTrue({'partial_result', 'stale_data'} <= {w['code'] for w in result['warnings']})

    def test_no_matches_and_pagination(self):
        status, result = self.request('/api/jobs/support/results?keyword=unmatched')
        self.assertEqual(status, 200)
        self.assertEqual(result['total'], 0)
        self.assertIn('no_matches', {w['code'] for w in result['warnings']})
        status, result = self.request('/api/jobs/support/results?limit=1&offset=1')
        self.assertEqual(status, 200)
        self.assertEqual(result['total'], 2)
        self.assertEqual(result['items'][0]['source'], 'source-a')
        self.assertFalse(result['has_more'])

    def test_invalid_filters_return_client_error(self):
        for query in ('limit=bad', 'limit=0', 'offset=-1', 'from=bad', 'all_runs=yes',
                      'keyword=', 'from=', 'status=', 'file=', 'run=', 'limit=',
                      'stale_hours=nan', 'timezone=invalid', 'run=abc',
                      'status=open&status=closed', 'unknown=1', 'file=../.env',
                      'run=' + self.run + '&all_runs=true'):
            with self.subTest(query=query):
                self.assertEqual(self.request('/api/jobs/support/results?' + query)[0], 400)
        self.assertEqual(self.request('/api/jobs/missing/results')[0], 404)
        self.assertEqual(self.request('/api/results/jobs?unknown=1')[0], 400)
        self.assertEqual(self.request('/api/results/jobs?keyword=')[0], 400)
        self.assertEqual(self.request('/api/results/jobs?keyword=a&keyword=b')[0], 400)


if __name__ == '__main__':
    unittest.main()
