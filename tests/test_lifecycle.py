import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from deployments.packages import Packages
from deployments.client import Deployment
from runner.common import ManagerError, now, write_json
from runner.execution import Execution
from runner.lifecycle import Lifecycle
from runner.store import Store, default_job, dump_yaml


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.store.create(default_job('sample'))
        self.life = Lifecycle(self.store)
        self.packages = Packages(self.store)

    def output(self, n, state='succeeded', managed=True):
        run = format(n, '032x')
        paths = self.life.paths('sample', run, create=True)
        Path(paths['SCRIPT_MANAGER_OUTPUT_DIR'], 'result.txt').write_text('output')
        record = dict(id=run, job_id='sample', state=state,
                      created_at='2020-01-%02dT00:00:00+00:00' % n)
        if managed:
            record['managed_output'] = 'runtime/job-data/sample/output/' + run
        write_json(self.store.runtime / 'runs/sample' / run / 'run.json', record)
        return run

    def test_packages_retention_protection_and_permanent_metadata(self):
        packages = [self.packages.create('sample') for _ in range(8)]
        pids = [p['id'] for p in packages]
        self.life.save('sample', {'pins': [pids[0]], 'rollback_packages': [pids[1]]})
        history = self.store.root / 'deployments/history/server/sample'
        for n, pid in enumerate(pids[2:4]):
            write_json(history / (str(n)+'.json'), dict(id=str(n), target='server', job_id='sample',
                package_id=pid, release='r-'+str(n), action='deploy', status='verified', created_at=str(n)))
        preview = self.life.preview('sample')
        self.assertEqual(preview['policy']['package_keep'], 5)
        self.assertFalse(preview['policy']['package_auto'])
        self.assertEqual(preview['package_reclaim_bytes'], 0)
        self.life.save('sample', {'package_keep': 0})
        candidates = [p['id'] for p in self.life.packages('sample') if p['cleanup_candidate']]
        self.assertEqual(set(candidates), set(pids[4:]))
        result = self.life.cleanup('sample', 'packages', candidates)
        self.assertEqual(result['errors'], [])
        self.assertEqual(len(self.packages.list('sample')), 8)
        for pid in candidates:
            package = self.packages.get(pid, 'sample')
            self.assertFalse(package['zip_available'])
            self.assertTrue(package['manifest'])
            self.assertTrue(package['zip_sha256'])
            with self.assertRaises(ManagerError):
                self.packages.archive(pid, 'sample')
        self.assertEqual(len(Deployment(self.store).history('sample')), 2)

    def test_output_limits_restore_and_protected_resources(self):
        old, newest = self.output(1), self.output(2)
        active = self.output(3, 'running')
        legacy = self.output(4, managed=False)
        paths = self.life.paths('sample')
        state = Path(paths['SCRIPT_MANAGER_STATE_DIR'], 'checkpoint')
        state.write_text('state')
        workspace = Path(paths['SCRIPT_MANAGER_WORKSPACE_DIR'], 'notes')
        workspace.write_text('shared')
        self.assertFalse(any(r['cleanup_candidate'] for r in self.life.outputs('sample')))
        self.life.save('sample', {'output_runs': 1})
        self.assertEqual([r['id'] for r in self.life.outputs('sample') if r['cleanup_candidate']], [old])
        self.life.cleanup('sample', 'output', [old])
        self.assertTrue(next(r for r in self.life.outputs('sample') if r['id']==old)['trashed'])
        self.life.restore('sample', old)
        self.assertTrue(Path(self.life.paths('sample', old)['SCRIPT_MANAGER_OUTPUT_DIR'], 'result.txt').exists())
        self.life.save('sample', {'output_days': 1, 'output_runs': None})
        self.assertEqual({r['id'] for r in self.life.outputs('sample') if r['cleanup_candidate']}, {old, newest})
        self.assertEqual(state.read_text(), 'state')
        self.assertEqual(workspace.read_text(), 'shared')
        self.assertNotIn(legacy, [r['id'] for r in self.life.outputs('sample')])
        # Job deletion leaves runtime data and workspace untouched.
        # Mark fake active record terminal before deletion.
        record = self.store.runtime / 'runs/sample' / active / 'run.json'
        data=json.loads(record.read_text()); data['state']='succeeded'; write_json(record,data)
        self.store.delete('sample', self.store.get('sample')['etag'])
        self.assertTrue(state.exists()); self.assertTrue(workspace.exists())
        self.assertTrue(self.life.outputs('sample'))

    def test_locks_symlinks_invalid_policies_and_failed_rename(self):
        run = self.output(1)
        self.life.save('sample', {'output_runs': 0})
        with self.store.job_lock('sample', 'run'):
            with self.assertRaises(ManagerError):
                self.life.cleanup('sample', 'output')
        with patch('runner.lifecycle.os.rename', side_effect=OSError('injected')):
            result = self.life.cleanup('sample', 'output')
        self.assertEqual(len(result['errors']), 1)
        self.assertFalse(self.life.outputs('sample')[0]['trashed'])
        with self.assertRaises(ManagerError):
            self.life.cleanup('sample', 'output', [])
        output = Path(self.life.paths('sample', run)['SCRIPT_MANAGER_OUTPUT_DIR'])
        (output/'escape').symlink_to(self.store.root)
        with self.assertRaises(ManagerError):
            self.life.cleanup('sample', 'output')
        (output/'escape').unlink()
        for policy in ({'package_keep': True}, {'output_days': -1}, {'pins': ['../escape']}, {'state_auto': True}):
            with self.assertRaises(ManagerError):
                self.life.save('sample', policy)
        for bad in ('../escape', None, '/tmp'):
            with self.assertRaises(ManagerError):
                self.life.restore('sample', bad)

    def test_package_unlink_failure_and_automatic(self):
        pid = self.packages.create('sample')['id']
        self.life.save('sample', {'package_keep': 0})
        original = Path.unlink
        def fail(path, *args, **kwargs):
            if path.name == 'package.zip':
                raise OSError('injected')
            return original(path,*args,**kwargs)
        with patch.object(Path, 'unlink', fail):
            result = self.life.cleanup('sample','packages')
        self.assertEqual(len(result['errors']),1)
        self.assertTrue(self.packages.get(pid,'sample')['zip_available'])
        self.life.save('sample', {'package_keep': 1,'package_auto': True})
        newer = self.packages.create('sample')['id']
        self.assertFalse(self.packages.get(pid,'sample')['zip_available'])
        self.assertTrue(self.packages.get(newer,'sample')['zip_available'])

    def test_real_execution_env_and_post_run_cleanup(self):
        item = self.store.get('sample')
        config = item['config']; config['command'] = [sys.executable, 'main.py']
        self.store.update('sample',dump_yaml(config),item['etag'])
        (self.store.job_dir('sample')/'main.py').write_text(
            "import os\nfrom pathlib import Path\n"
            "Path(os.environ['SCRIPT_MANAGER_OUTPUT_DIR'],'result').write_text('done')\n"
            "Path(os.environ['SCRIPT_MANAGER_STATE_DIR'],'checkpoint').write_text('saved')\n"
            "print(os.environ['SCRIPT_MANAGER_WORKSPACE_DIR'])\n")
        self.life.save('sample', {'output_auto':True,'output_runs':0})
        execution = Execution(self.store)
        run = execution.start('sample')['id']
        deadline = time.monotonic()+15
        while time.monotonic()<deadline:
            record=execution.get('sample',run)
            if record['state'] not in ('queued','running') and any(r['trashed'] for r in self.life.outputs('sample')):
                break
            time.sleep(.05)
        self.assertEqual(record['state'],'succeeded')
        self.assertTrue(self.life.outputs('sample')[0]['trashed'])
        self.assertEqual(Path(self.life.paths('sample')['SCRIPT_MANAGER_STATE_DIR'],'checkpoint').read_text(),'saved')
        self.assertIn('/workspace',execution.logs('sample',run)['text'])

    def test_default_count_and_missing_zip_deployment_block(self):
        packages=[self.packages.create('sample') for _ in range(6)]
        old=packages[0]['id']
        self.assertEqual([r['id'] for r in self.life.packages('sample') if r['cleanup_candidate']],[old])
        # Simulate a package created before manifest sidecars existed.
        (self.packages._directory(old)/'manifest.json').unlink()
        self.assertEqual(self.life.cleanup('sample','packages')['completed'],[old])
        self.assertTrue(self.packages.get(old,'sample')['manifest'])
        deployer=Deployment(self.store)
        with patch.object(deployer,'target',return_value={'id':'test'}):
            with self.assertRaises(ManagerError) as error:
                deployer.plan('sample','test',old)
        self.assertEqual(error.exception.status,409)

    def test_rollback_receipts_and_uncertain_deploy_are_protected(self):
        pids=[self.packages.create('sample')['id'] for _ in range(4)]
        folder=self.store.root/'deployments/history/server/sample'
        for n,pid in enumerate(pids):
            write_json(folder/(str(n)+'.json'),dict(id=str(n),target='server',job_id='sample',
                action='deploy',release='r-'+str(n),package_id=pid,created_at=str(n),
                status='unconfirmed' if n==3 else 'verified'))
        write_json(folder/'rollback.json',dict(id='rb',target='server',job_id='sample',
            action='rollback',release='r-0',package_id=None,created_at='5',status='verified'))
        self.life.save('sample',{'package_keep':0})
        rows={r['id']:r for r in self.life.packages('sample')}
        self.assertIn('current',rows[pids[0]]['protection'])
        self.assertIn('rollback',rows[pids[2]]['protection'])
        self.assertIn('unconfirmed',rows[pids[3]]['protection'])
        self.assertEqual(self.life.cleanup('sample','packages')['completed'],[pids[1]])

    def test_workspace_excluded_and_ancestor_symlinks_rejected(self):
        folder=self.store.job_dir('sample')/'workspace'
        folder.mkdir(); (folder/'agent.txt').write_text('local workspace')
        package=self.packages.create('sample')
        self.assertNotIn('workspace/agent.txt',self.packages.get(package['id'],'sample')['manifest']['files'])
        root=self.store.root/'runtime/job-data'
        root.symlink_to(self.store.jobs,target_is_directory=True)
        with self.assertRaises(ManagerError):
            self.life.paths('sample','0'*32,True)
