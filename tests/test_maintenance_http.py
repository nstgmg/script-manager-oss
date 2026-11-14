"""Only ephemeral loopback servers; never starts a resident Dashboard."""
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from dashboard.server import Dashboard
from runner.schedule import Scheduler
from runner.schedule_doctor import ScheduleDoctor
from runner.store import default_job
from tests.test_maintenance import DoctorLaunchctl


class MaintenanceHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.patcher = patch("runner.schedule.platform.system", return_value="Darwin")
        self.patcher.start(); self.addCleanup(self.patcher.stop)
        self.fake = DoctorLaunchctl()
        self.server = Dashboard(Path(self.temp.name) / "project", 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        scheduler = Scheduler(self.server.store, Path(self.temp.name) / "agents", self.fake)
        self.doctor = ScheduleDoctor(self.server.store, scheduler)
        self.doctor_patcher = patch("runner.schedule_doctor.ScheduleDoctor", return_value=self.doctor)
        self.doctor_patcher.start(); self.addCleanup(self.doctor_patcher.stop)
        maintenance_patcher = patch("runner.maintenance.ScheduleDoctor", return_value=self.doctor)
        maintenance_patcher.start(); self.addCleanup(maintenance_patcher.stop)
        job = self.server.store.create(default_job("sample"))
        scheduler.save("sample", "daily", {"id": "daily", "name": "daily", "type": "calendar", "enabled": True,
                                            "times": ["23:59"], "weekdays": [7]}, job["etag"], True)

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=10)
        actual = {"X-CSRF-Token": self.server.token, "Content-Type": "application/json"}
        actual.update(headers or {})
        connection.request(method, path, json.dumps(body) if body is not None else None, actual)
        response = connection.getresponse()
        result = json.loads(response.read()); connection.close()
        return response.status, result

    def test_readonly_preview_csrf_confirm_and_new_job_after_reset(self):
        self.assertEqual(self.request("GET", "/api/schedule-doctor")[1]["counts"]["healthy"], 1)
        status, plan = self.request("GET", "/api/reset")
        self.assertEqual(status, 200)
        self.assertTrue(self.server.store.list())
        self.assertEqual(self.request("POST", "/api/reset", {})[0], 428)
        self.assertEqual(self.request("POST", "/api/reset", {"confirm":plan["plan_hash"]}, {"X-CSRF-Token":""})[0], 403)
        self.assertEqual(self.request("POST", "/api/reset", {"confirm":"stale"})[0], 409)
        status, result = self.request("POST", "/api/reset", {"confirm":plan["plan_hash"]})
        self.assertEqual(status, 200, result)
        self.assertTrue(result["success"])
        self.assertEqual(self.request("GET", "/api/jobs")[1], [])
        self.assertEqual(self.request("POST", "/api/jobs", {"id":"fresh"})[0], 201)
        self.assertEqual(self.request("GET", "/api/session")[1]["root"], str(self.server.store.root))

    def test_os_failure_response_reports_phase_and_remaining_data(self):
        plan = self.request("GET", "/api/reset")[1]
        self.fake.ignore_bootout = True
        status, result = self.request("POST", "/api/reset", {"confirm":plan["plan_hash"]})
        self.assertEqual(status, 409)
        self.assertEqual(result["phase"], "remove-schedules")
        self.assertTrue(result["remaining"])
        self.assertEqual(result["deleted"], [])

    def test_duplicate_reset_requests_and_stale_replay_do_not_repeat_cleanup(self):
        plan = self.request('GET', '/api/reset')[1]
        entered, release = threading.Event(), threading.Event()
        original = self.doctor.remove
        calls, first_result = [], []
        def delayed(*args, **kwargs):
            calls.append(args[0]); entered.set()
            if not release.wait(5): raise RuntimeError('test release timed out')
            return original(*args, **kwargs)
        def first():
            first_result.append(self.request('POST','/api/reset',{'confirm':plan['plan_hash']}))
        with patch.object(self.doctor,'remove',side_effect=delayed):
            thread=threading.Thread(target=first); thread.start()
            try:
                self.assertTrue(entered.wait(5))
                self.assertEqual(self.request('POST','/api/reset',{'confirm':plan['plan_hash']})[0],409)
            finally:
                release.set(); thread.join(6)
        self.assertEqual(first_result[0][0],200, first_result)
        self.assertEqual(len(calls),1)
        self.assertEqual(self.request('POST','/api/reset',{'confirm':plan['plan_hash']})[0],409)
        self.assertEqual(self.request('POST','/api/jobs',{'id':'after-reset'})[0],201)
        self.assertEqual(self.request('POST','/api/reset',{'confirm':plan['plan_hash']})[0],409)
        self.assertTrue(self.server.store.job_dir('after-reset').exists())

    def test_connection_loss_does_not_cancel_or_repeat_server_cleanup(self):
        import socket
        plan=self.request('GET','/api/reset')[1]
        entered, release, done = threading.Event(), threading.Event(), threading.Event()
        original = self.doctor.remove
        calls=[]
        def delayed(*args, **kwargs):
            calls.append(args[0]); entered.set()
            if not release.wait(5): raise RuntimeError('test release timed out')
            return original(*args, **kwargs)
        from dashboard.server import Handler
        send=Handler.send
        results=[]
        def observed(handler,status,value,*args,**kwargs):
            if handler.path=='/api/reset' and handler.command=='POST':
                results.append(value); done.set()
            return send(handler,status,value,*args,**kwargs)
        with patch.object(self.doctor,'remove',side_effect=delayed), patch.object(Handler,'send',observed):
            conn=http.client.HTTPConnection('127.0.0.1',self.server.server_address[1],timeout=5)
            conn.request('POST','/api/reset',json.dumps({'confirm':plan['plan_hash']}),{'X-CSRF-Token':self.server.token,'Content-Type':'application/json'})
            try:
                self.assertTrue(entered.wait(5))
                conn.sock.shutdown(socket.SHUT_RDWR);conn.close()
            finally:
                release.set()
            self.assertTrue(done.wait(5))
        self.assertTrue(results[0]['success'],results)
        self.assertEqual(len(calls),1)
        self.assertEqual(self.request('GET','/api/jobs')[1],[])
        self.assertEqual(self.request('POST','/api/reset',{'confirm':plan['plan_hash']})[0],409)
