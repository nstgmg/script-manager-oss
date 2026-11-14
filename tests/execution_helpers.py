"""Diagnostics for fixture-owned workers; never inspect an installed data root.

Normal runs keep the real worker argv and only capture its otherwise discarded
stderr. Opt-in tracing adds timed Python stacks inside that same worker. Neither
mode retries a Run or changes the product's locks, lease, monitor or timeouts.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
from unittest.mock import patch

from runner.common import read_json, windows_pid_alive


TRACE = """import faulthandler, runpy, sys, traceback
import runner.execution as execution
faulthandler.enable()
faulthandler.dump_traceback_later(8, repeat=True)
original_write = execution.write_json
def write(path, value):
    try:
        return original_write(path, value)
    except Exception:
        print('worker JSON write failed; file=' + path.name + '; state=' + str(value.get('state')), file=sys.stderr, flush=True)
        traceback.print_exc()
        raise
execution.write_json = write
original_job = execution.WindowsJob
class TracedWindowsJob(original_job):
    def __init__(self, proc):
        super().__init__(proc)
        print('Windows Job Object assigned=' + str(self.assigned), file=sys.stderr, flush=True)
    def terminate(self):
        print('Windows Job Object terminate requested', file=sys.stderr, flush=True)
        return super().terminate()
execution.WindowsJob = TracedWindowsJob
sys.argv = ['runner', *sys.argv[1:]]
try:
    runpy.run_module('runner', run_name='__main__')
finally:
    faulthandler.cancel_dump_traceback_later()
"""


def capture_workers(test, root):
    root = Path(root).resolve()
    original = subprocess.Popen
    workers = {}

    def spawn(command, *args, **kwargs):
        # All other Popen users, including native process queries, stay real.
        if (len(command) < 8 or list(command[1:3]) != ['-m', 'runner']
                or command[3] != '--root' or Path(command[4]).resolve() != root
                or command[5] != '_worker'):
            return original(command, *args, **kwargs)
        job, run = command[6:8]
        folder = root / 'runtime/runs' / job / run
        log = folder / 'worker-stderr.log'
        if os.environ.get('SCRIPT_MANAGER_TEST_TRACE_WORKERS') == '1':
            command = [command[0], '-c', TRACE, *command[3:]]
        with log.open('wb') as error:
            proc = original(command, *args, **dict(kwargs, stderr=error))
        workers[(job, run)] = proc
        return proc

    def diagnostics(job, run):
        folder = root / 'runtime/runs' / job / run
        record = read_json(folder / 'run.json', {})
        proc = workers.get((job, run))
        lease = read_json(root / 'runtime/locks' / (job + '.run.active'), {})
        value = {k: record.get(k) for k in ('id', 'state', 'worker_pid', 'pid', 'created_at',
                 'started_at', 'heartbeat_at', 'finished_at', 'exit_code', 'error', 'lifecycle_error')}
        value.update(worker_returncode=proc.poll() if proc else None,
                     cancel_present=(folder / 'cancel').exists(), lease=lease)
        if os.name == 'nt':
            value['lease_pid_alive'] = windows_pid_alive(lease.get('pid'))
        error = folder / 'worker-stderr.log'
        value['worker_stderr'] = error.read_bytes().decode('utf-8', errors='replace')[-12000:] if error.exists() else ''
        return value

    def preserve():
        destination = os.environ.get('SCRIPT_MANAGER_TEST_DIAGNOSTICS_DIR')
        if not destination:
            return
        for job, run in workers:
            target = Path(destination).resolve() / test.id() / run
            target.mkdir(parents=True, exist_ok=True)
            (target / 'diagnostics.json').write_text(json.dumps(diagnostics(job, run), indent=2), encoding='utf-8')
            # Only known synthetic logs, never env, source or arbitrary Output.
            for name in ('worker-stderr.log', 'stdout.log', 'stderr.log'):
                source = root / 'runtime/runs' / job / run / name
                if source.exists():
                    shutil.copyfile(source, target / name)

    test.addCleanup(preserve)
    patcher = patch('runner.execution.subprocess.Popen', side_effect=spawn)
    patcher.start()
    test.addCleanup(patcher.stop)
    return diagnostics
