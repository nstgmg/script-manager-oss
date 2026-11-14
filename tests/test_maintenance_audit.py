"""Regression cases found in the final maintenance safety audit."""
import unittest
from pathlib import Path
import json
import plistlib
import shutil
import subprocess
from unittest.mock import patch

from runner.common import ManagerError, write_json
from runner.maintenance import Maintenance
from runner.schedule_doctor import ScheduleDoctor
from runner.store import Store
from tests import test_maintenance as mac_fixtures
from tests import test_schedule_doctor_platforms as platform_fixtures


class DataAuditTests(unittest.TestCase):
    setUp = mac_fixtures.MaintenanceTests.setUp
    create = mac_fixtures.MaintenanceTests.create
    def test_audit_data_added_during_os_removal_is_preserved(self):
        original = self.doctor.remove
        extra = self.store.root / 'workspace/new-unapproved.txt'
        def remove(*args, **kwargs):
            result = original(*args, **kwargs)
            extra.parent.mkdir(exist_ok=True)
            extra.write_text('unapproved')
            return result
        plan = self.manager.preview()
        with patch.object(self.doctor, 'remove', side_effect=remove):
            result = self.manager.execute('reset', plan['plan_hash'])
        self.assertFalse(result['success'])
        self.assertEqual(result['deleted'], [])
        self.assertTrue(extra.exists())
        self.assertTrue(self.store.job_dir('sample').exists())

    def test_audit_changed_child_during_os_removal_is_preserved(self):
        original = self.doctor.remove
        extra = self.store.job_dir('sample') / 'unapproved.txt'
        def remove(*args, **kwargs):
            result = original(*args, **kwargs); extra.write_text('unapproved'); return result
        plan = self.manager.preview()
        with patch.object(self.doctor, 'remove', side_effect=remove):
            result = self.manager.execute('reset', plan['plan_hash'])
        self.assertFalse(result['success'])
        self.assertEqual(result['deleted'], [])
        self.assertTrue(extra.exists())

    def test_audit_nested_data_only_installation_protected(self):
        Store(self.store.root / 'workspace/other')
        write_json(self.store.root / 'workspace/other/runtime/installation.json', {'installation_id':'b'*32})
        self.assertTrue(self.manager.preview()['blockers'])

    def test_audit_unfinished_deployment_is_preserved(self):
        write_json(self.store.root / 'deployments/history/target/sample/op.json', {'status':'unconfirmed'})
        self.assertTrue(self.manager.preview()['blockers'])

    def test_audit_installation_id_mismatch_is_unknown(self):
        value = json.loads((self.store.runtime / 'installation.json').read_text())
        value['installation_id'] = 'f'*32
        write_json(self.store.runtime / 'installation.json', value)
        row = self.doctor.scan()['schedules'][0]
        self.assertEqual(row['status'], 'unknown')
        self.assertFalse(row['owned'])


class WindowsAuditTests(unittest.TestCase):
    setUp = platform_fixtures.WindowsDoctorTests.setUp
    def test_audit_modified_trigger_is_unknown(self):
        self.fake.tasks[self.name] = self.fake.tasks[self.name].replace('08:00:00', '09:00:00')
        self.assertEqual(self.doctor.scan()['schedules'][0]['status'], 'unknown')

    def test_audit_replacement_after_state_query_is_not_deleted(self):
        shutil.rmtree(self.store.root)
        row = self.doctor.scan()['schedules'][0]
        old = self.fake.tasks[self.name]
        original = self.doctor._windows_idle
        def idle(label):
            original(label)
            self.fake.tasks[label] = old.replace('08:00:00', '09:00:00')
        with patch.object(self.doctor, '_windows_idle', side_effect=idle):
            with self.assertRaises(ManagerError):
                self.doctor.remove(self.name, row['fingerprint'])
        self.assertIn(self.name, self.fake.tasks)


class LinuxAuditTests(unittest.TestCase):
    setUp = platform_fixtures.LinuxDoctorTests.setUp
    def test_audit_failed_show_cannot_be_treated_as_success(self):
        original = self.fake.__call__
        def failed(args, **kwargs):
            result = original(args, **kwargs)
            if args[2] == 'show':
                result.returncode = 1
            return result
        self.doctor.scheduler.command = failed
        self.assertTrue(all(not r['owned'] for r in self.doctor.scan()['schedules']))

class MoreDataAuditTests(unittest.TestCase):
    setUp = mac_fixtures.MaintenanceTests.setUp
    create = mac_fixtures.MaintenanceTests.create
    def test_audit_partial_file_deletion_is_reported_and_resumable(self):
        target = self.store.job_dir('sample') / 'unapproved.txt'
        target.write_text('approved synthetic data')
        plan = self.manager.preview()
        original = __import__('os').unlink
        failed = [False]
        def unlink(path, *args, **kwargs):
            if str(path) == 'main.py' and not failed[0]:
                failed[0] = True
                raise PermissionError('injected partial deletion')
            return original(path, *args, **kwargs)
        with patch('runner.maintenance.os.unlink', side_effect=unlink):
            result = self.manager.execute('reset', plan['plan_hash'])
        self.assertFalse(result['success'])
        self.assertTrue(result['deleted_entries'])
        self.assertTrue(result['remaining'])
        self.assertFalse(self.fake.services)
        fresh = self.manager.preview()
        self.assertFalse(fresh['blockers'], fresh)
        self.assertTrue(self.manager.execute('reset', fresh['plan_hash'])['success'])

    def test_audit_separate_code_root_external_files_and_preview_scope(self):
        code = self.base / 'code/runner/__main__.py'
        code.parent.mkdir(parents=True); code.write_text('synthetic program')
        outside = self.base / 'external/result.html'; outside.parent.mkdir(); outside.write_text('keep')
        before = {str(p) for p in self.manager.targets()}
        plan = self.manager.preview('uninstall')
        self.assertEqual(before, {e['path'] for e in plan['delete']})
        result = self.manager.execute('uninstall', plan['plan_hash'])
        self.assertTrue(result['success'], result)
        self.assertEqual(set(result['deleted']), before)
        self.assertTrue(code.exists() and outside.exists() and self.store.root.exists())

    def test_audit_walk_failure_mount_and_path_escape_block_deletion(self):
        folder = self.store.root / 'workspace'; folder.mkdir()
        real_walk = __import__('os').walk
        def denied(path, **kwargs):
            if path == folder:
                kwargs['onerror'](PermissionError('inventory denied'))
            return real_walk(path, **kwargs)
        with patch('runner.maintenance.os.walk', side_effect=denied):
            self.assertTrue(self.manager.preview()['blockers'])
        real_mount = Path.is_mount
        with patch.object(Path, 'is_mount', lambda p: p == folder or real_mount(p)):
            self.assertTrue(self.manager.preview()['blockers'])
        from runner.common import contained
        with self.assertRaises(ManagerError):
            contained(self.store.root, '../external/result.html')
        folder.rmdir(); folder.symlink_to(self.base / 'external', target_is_directory=True)
        self.assertTrue(self.manager.preview()['blockers'])

    def test_audit_directory_replacement_does_not_touch_external_files(self):
        folder = self.store.root / 'workspace'; folder.mkdir(); (folder/'file').write_text('approved')
        external = self.base / 'external'; external.mkdir(); (external/'file').write_text('keep')
        plan = self.manager.preview()
        original = self.manager._delete_tree
        def replaced(path, records, anchors, progress):
            if path == folder:
                folder.rename(self.store.root/'saved-workspace')
                folder.symlink_to(external, target_is_directory=True)
            return original(path, records, anchors, progress)
        with patch.object(self.manager, '_delete_tree', side_effect=replaced):
            result = self.manager.execute('reset', plan['plan_hash'])
        self.assertFalse(result['success'])
        self.assertEqual((external/'file').read_text(), 'keep')
        self.assertTrue((self.store.root/'saved-workspace/file').exists())

    def test_audit_direct_schedule_remove_does_not_kill_running_wrapper(self):
        label = self.scheduler.label('sample', 'daily'); self.fake.running.add(label)
        with self.assertRaises(ManagerError):
            self.scheduler.remove('sample', 'daily')
        self.assertIn(label, self.fake.services)

    def test_audit_loaded_invocation_drift_is_unknown(self):
        label = self.scheduler.label('sample', 'daily')
        self.fake.definitions[label] = dict(self.fake.definitions[label], ProgramArguments=['/usr/bin/true'])
        row = self.doctor.scan()['schedules'][0]
        self.assertEqual(row['status'], 'unknown')
        with self.assertRaises(ManagerError):
            self.scheduler.remove('sample', 'daily')
        self.assertIn(label, self.fake.services)

    def test_audit_failure_after_some_schedules_removed_can_resume(self):
        self.scheduler.save('sample','second',{'id':'second','name':'second','enabled':True,'type':'calendar',
             'times':['23:59'],'weekdays':[7]},self.store.get('sample')['etag'],True)
        plan = self.manager.preview(); original = self.doctor.remove
        def remove(label, *args, **kwargs):
            if label.endswith('.second'): raise ManagerError('injected failure',502)
            return original(label,*args,**kwargs)
        with patch.object(self.doctor,'remove',side_effect=remove):
            result = self.manager.execute('reset',plan['plan_hash'])
        self.assertFalse(result['success']); self.assertEqual(len(result['removed_schedules']),1)
        self.assertFalse(result['deleted_entries'])
        new = self.manager.preview()
        self.assertTrue(self.manager.execute('reset',new['plan_hash'])['success'])

class LinuxMoreAuditTests(unittest.TestCase):
    setUp = platform_fixtures.LinuxDoctorTests.setUp
    def test_actual_loaded_exec_and_timer_target_drift_are_unknown(self):
        original = self.fake.__call__
        def drift(args, **kwargs):
            result=original(args, **kwargs)
            if args[2]=='show':
                result.stdout=result.stdout.replace('ExecStart={ path=', 'ExecStart={ path=/foreign').replace('Unit=scriptmanager-', 'Unit=foreign-')
            return result
        self.doctor.scheduler.command=drift
        self.assertTrue(all(not r['owned'] for r in self.doctor.scan()['schedules']))

    def test_not_found_exit_four_is_verified_but_other_errors_are_not(self):
        original=self.fake.__call__
        def rc4(args, **kwargs):
            result=original(args, **kwargs)
            if args[2]=='show' and 'LoadState=not-found' in result.stdout:
                result.returncode=4
            return result
        self.doctor.scheduler.command=rc4
        shutil.rmtree(self.remote)
        row=next(r for r in self.doctor.scan()['schedules'] if r['id'].endswith('.timer'))
        self.assertTrue(self.doctor.remove(row['id'],row['fingerprint'])['verified'])

    def test_definition_changed_in_last_state_query_is_not_stopped(self):
        shutil.rmtree(self.remote)
        row=next(r for r in self.doctor.scan()['schedules'] if r['id'].endswith('.timer'))
        original=self.doctor._unit_state; count=[0]
        def changed(name):
            state=original(name);count[0]+=1
            if count[0]==4:
                path=Path(row['path']);path.write_text(path.read_text()+'# external\n')
            return state
        self.fake.calls.clear()
        with patch.object(self.doctor,'_unit_state',side_effect=changed):
            with self.assertRaises(ManagerError):self.doctor.remove(row['id'],row['fingerprint'])
        self.assertFalse(any(call[2]=='stop' for call in self.fake.calls))

class WindowsMoreAuditTests(unittest.TestCase):
    setUp = platform_fixtures.WindowsDoctorTests.setUp
    def test_orphan_with_modified_trigger_does_not_pass_self_checksum(self):
        shutil.rmtree(self.store.root)
        self.fake.tasks[self.name]=self.fake.tasks[self.name].replace('08:00:00','09:00:00')
        self.assertEqual(self.doctor.scan()['schedules'][0]['status'],'unknown')

    def test_metadata_without_full_checksum_needs_original_state(self):
        import xml.etree.ElementTree as ET
        from runner.windows_schedule import NS
        from runner.installation import DESCRIPTION
        root=ET.fromstring(self.fake.tasks[self.name])
        desc=root.find('{'+NS+'}RegistrationInfo/{'+NS+'}Description')
        meta=json.loads(desc.text[len(DESCRIPTION):]);meta.pop('definition_sha256')
        desc.text=DESCRIPTION+json.dumps(meta)
        self.fake.tasks[self.name]=ET.tostring(root,encoding='unicode')
        from runner.common import digest
        state=self.scheduler.state('sample','daily');state['task_sha256']=digest(self.fake.tasks[self.name].encode())
        write_json(self.scheduler.state_path('sample','daily'),state)
        self.assertTrue(self.doctor.scan()['schedules'][0]['owned'])
        shutil.rmtree(self.store.root)
        self.assertFalse(self.doctor.scan()['schedules'][0]['owned'])

    def test_direct_scheduler_refuses_running_task(self):
        self.fake.running=True
        with self.assertRaises(ManagerError):self.scheduler.remove('sample','daily')
        self.assertIn(self.name,self.fake.tasks)

class FinalDataRaceTests(unittest.TestCase):
    setUp = mac_fixtures.MaintenanceTests.setUp
    create = mac_fixtures.MaintenanceTests.create
    def test_unapproved_child_added_inside_deletion_is_retained_until_new_approval(self):
        folder=self.store.root/'workspace';folder.mkdir();(folder/'old').write_text('approved')
        plan=self.manager.preview();original=self.manager._delete_tree
        def added(path,records,anchors,progress):
            if path==folder:(folder/'new').write_text('not approved')
            return original(path,records,anchors,progress)
        with patch.object(self.manager,'_delete_tree',side_effect=added):
            result=self.manager.execute('reset',plan['plan_hash'])
        self.assertFalse(result['success']);self.assertEqual(result['phase'],'delete-data')
        self.assertTrue((folder/'new').exists());self.assertNotIn(str(folder/'new'),result['deleted_entries'])
        next_plan=self.manager.preview()
        self.assertTrue(self.manager.execute('reset',next_plan['plan_hash'])['success'])

    def test_same_device_bind_mount_is_blocked_by_linux_mount_inventory(self):
        folder=self.store.root/'workspace';folder.mkdir()
        original=Path.read_text
        def text(path,*args,**kwargs):
            if path==Path('/proc/self/mountinfo'):
                return '1 0 0:1 / '+str(folder)+' rw - ext4 /dev/synthetic rw\n'
            return original(path,*args,**kwargs)
        with patch('runner.maintenance.sys.platform','linux'),patch.object(Path,'read_text',text):
            self.assertTrue(self.manager.preview()['blockers'])

class RollbackAuditTests(unittest.TestCase):
    setUp = mac_fixtures.MaintenanceTests.setUp
    create = mac_fixtures.MaintenanceTests.create
    def test_mac_rollback_preserves_external_replacement(self):
        path=Path(self.scheduler.plan('sample',schedule_id='daily')['path'])
        foreign=b'foreign definition created outside the transaction'
        original=self.fake.__call__
        def command(args,**kwargs):
            if args[0]=='plutil':
                path.write_bytes(foreign)
                return subprocess.CompletedProcess(args,1,'','injected lint failure')
            return original(args,**kwargs)
        self.scheduler.command=command
        with self.assertRaises(ManagerError):
            self.scheduler.apply('sample',self.store.get('sample')['etag'],'daily')
        self.assertEqual(path.read_bytes(),foreign)
        self.assertEqual(self.scheduler.state('sample','daily')['phase'],'degraded')

class WindowsRollbackAuditTests(unittest.TestCase):
    setUp = platform_fixtures.WindowsDoctorTests.setUp
    def test_windows_rollback_preserves_external_replacement(self):
        foreign='<foreign-task/>'
        original=self.fake.__call__;creates=[]
        def command(args,**kwargs):
            if args[:2]==['schtasks','/Create']:
                creates.append(args);self.fake.tasks[self.name]=foreign
                return subprocess.CompletedProcess(args,1,'','injected registration failure')
            return original(args,**kwargs)
        self.scheduler.command=command
        with self.assertRaises(ManagerError):
            self.scheduler.apply('sample',self.store.get('sample')['etag'],'daily')
        self.assertEqual(self.fake.tasks[self.name],foreign)
        self.assertEqual(len(creates),1)
        self.assertEqual(self.scheduler.state('sample','daily')['phase'],'degraded')
