import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from dashboard.server import Dashboard
from runner.common import ManagerError
from runner.dashboard_run import DashboardRun
from runner.execution import Execution
from runner.store import default_job


class DashboardRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.server = Dashboard(self.temp.name, 0)
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=.01), daemon=True)
        self.thread.start()
        self.events = []
        self.client = DashboardRun(self.temp.name, 'http://127.0.0.1:' + str(self.server.server_port), self.events.append)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def job(self, code, timeout=10):
        config = default_job('mock', 'Mock')
        config.update(command=[sys.executable, 'main.py'], timeout_seconds=timeout)
        self.server.store.create(config)
        (Path(self.temp.name)/'jobs/mock/main.py').write_text(code)

    def test_success_filters_projection_and_bounded_logs(self):
        self.job("""import json,os
from pathlib import Path
print('x'*3000)
Path(os.environ['SCRIPT_MANAGER_OUTPUT_DIR'],'report.json').write_text(json.dumps({'announcements':[{'title':'용인','summary':'지원','secret_detail':'omit'},{'title':'서울'}]}))
""")
        result = self.client.run('mock', poll_seconds=.1, query={'keyword':['용인'], 'limit':1}, log_chars=10)
        self.assertTrue(result['success'], result)
        self.assertEqual(result['results']['total'], 1)
        self.assertEqual(result['results']['items'][0]['data'], {'title':'용인','summary':'지원'})
        self.assertEqual(result['results']['items'][0]['provenance']['run_id'], result['run_id'])
        self.assertEqual(len(result['logs']['stdout']['text']), 10)
        self.assertTrue(result['logs']['stdout']['excerpt_limited'])
        stages = [e['stage'] for e in self.events]
        self.assertEqual(stages[:2], ['identified','accepted'])
        self.assertIn('completed', stages)
        self.assertEqual(stages[-1], 'results')
        print('MOCK_SUCCESS', json.dumps(result['timings']))
        import contextlib
        import io
        from runner.__main__ import main
        output=io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            code=main(['--root',self.temp.name,'run-dashboard','mock','--url',self.client.base,
                       '--run',result['run_id'],'--keyword','용인','--fields','title'])
        self.assertEqual(code,0)
        self.assertEqual(json.loads(output.getvalue())['results']['items'][0]['data'],{'title':'용인'})

    def test_failure_and_worker_timeout(self):
        for code, timeout, expected in [('import sys; print("failure",file=sys.stderr); sys.exit(7)',10,'failed'),
                                        ('import time; time.sleep(2)',1,'timed_out')]:
            with self.subTest(expected=expected):
                if expected == 'failed':
                    self.job(code,timeout)
                else:
                    # Only the isolated fixture changes, never project Jobs.
                    p=Path(self.temp.name)/'jobs/mock/main.py'; p.write_text(code)
                    item=self.server.store.get('mock')
                    self.server.store.update_fields('mock', {'timeout_seconds':timeout}, item['etag'])
                result=self.client.run('mock',poll_seconds=.1)
                self.assertFalse(result['success'])
                self.assertEqual(result['state'],expected,result)
                if expected=='failed':
                    self.assertEqual(result['exit_code'],7)
                    self.assertIn('failure',result['logs']['stderr']['text'])

    def test_wait_timeout_resume_and_duplicate_lock(self):
        self.job('import time; time.sleep(.5)')
        result=self.client.run('mock',wait_seconds=.05,poll_seconds=.1)
        self.assertTrue(result['wait_timed_out'])
        self.assertFalse(result['success'])
        duplicate=self.client.run('mock',poll_seconds=.1)
        self.assertIn('409',duplicate['observation_error'])
        self.assertFalse(duplicate['submission_uncertain'])
        resumed=self.client.run('mock',run_id=result['run_id'],poll_seconds=.1)
        self.assertTrue(resumed['success'],resumed)
        self.assertNotIn('submit',[r['stage'] for r in self.client.metrics])
        self.assertEqual(len(Execution(self.server.store).list('mock')),1)

    def test_lost_submit_response_never_reposts(self):
        self.job('print("ok")')
        original=self.client.request
        def request(path, stage, *args, **kwargs):
            value=original(path,stage,*args,**kwargs)
            if stage=='submit':
                raise ManagerError('lost response')
            return value
        with patch.object(self.client,'request',side_effect=request):
            result=self.client.run('mock',poll_seconds=.1)
        self.assertTrue(result['submission_uncertain'])
        self.assertEqual(len(result['existing_runs']),1)
        self.assertEqual(len(Execution(self.server.store).list('mock')),1)
        run=Execution(self.server.store).list('mock')[0]
        self.client.run('mock',run_id=run['id'],poll_seconds=.1)
        self.assertNotIn('submit',[r['stage'] for r in self.client.metrics])

    def test_observation_failure_preserves_id_and_resume_does_not_submit(self):
        self.job('print("ok")')
        original=self.client.request
        def request(path,stage,*args,**kwargs):
            if stage=='status':
                raise ManagerError('read failed')
            return original(path,stage,*args,**kwargs)
        with patch.object(self.client,'request',side_effect=request):
            result=self.client.run('mock',poll_seconds=.1)
        self.assertTrue(result['run_id'])
        self.assertIn('--run '+result['run_id'],result['resume'])
        self.assertFalse(result['success'])
        resumed=self.client.run('mock',run_id=result['run_id'],poll_seconds=.1)
        self.assertTrue(resumed['success'])
        self.assertEqual(len(Execution(self.server.store).list('mock')),1)

    def test_root_mismatch_and_invalid_options_never_submit(self):
        self.client.root='/wrong-root'
        result=self.client.run('mock')
        self.assertIn('루트',result['observation_error'])
        self.assertEqual([r['stage'] for r in self.client.metrics],['session'])
        for options in ({'wait_seconds':float('nan')},{'poll_seconds':0},{'run_id':'bad'}):
            with self.assertRaises(ManagerError):
                self.client.run('mock',**options)
        for url in ('http://example.com:80','http://127.0.0.1:8765/path','http://user:pass@localhost:8765'):
            with self.assertRaises(ManagerError):
                DashboardRun(self.temp.name,url)


if __name__ == '__main__':
    unittest.main()
