"""Client orchestration only: execution remains in the resident Dashboard."""
import json
import math
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler

from runner.common import ManagerError


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class DashboardRun:
    def __init__(self, root, base, emit=lambda event: None):
        parsed = urlsplit(base)
        if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost')
                or not parsed.port or parsed.username or parsed.password
                or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
            raise ManagerError('Dashboard URL은 명시적 포트가 있는 loopback HTTP 주소여야 합니다.')
        self.root = str(Path(root).resolve())
        self.base = base.rstrip('/')
        self.emit = emit
        self.metrics = []
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, path, stage, token=None, timeout=10, body=None):
        headers = {}
        if token:
            headers = {'Origin': self.base, 'X-CSRF-Token': token,
                       'Content-Type': 'application/json'}
        request = Request(self.base + path,
                          data=json.dumps(body if body is not None else {}, allow_nan=False).encode() if token else None,
                          headers=headers)
        # A POST is never retried. Read failures are returned with the known Run ID.
        start = time.monotonic()
        try:
            with self.opener.open(request, timeout=timeout) as response:
                return json.load(response)
        except HTTPError as exc:
            # Never expose headers/session token or arbitrary server error bodies.
            raise ManagerError('Dashboard HTTP ' + str(exc.code) + ' (' + stage + ')', exc.code) from None
        except (OSError, URLError, ValueError):
            raise ManagerError('Dashboard 접근/응답 오류 (' + stage + ')') from None
        finally:
            self.metrics.append({'stage': stage, 'elapsed_ms': round((time.monotonic()-start)*1000, 3)})

    def run(self, job, *, run_id=None, wait_seconds=60, poll_seconds=3,
            query=None, fields=('title', 'url', 'summary', 'target', 'deadline', 'period_raw'),
            log_chars=2000, parameters=None):
        if run_id and parameters is not None:
            raise ManagerError('--run 관찰 재개에는 parameters를 지정할 수 없습니다.')
        if not re.fullmatch(r'[a-zA-Z0-9_-]+', job):
            raise ManagerError('잘못된 Job ID입니다.')
        if run_id and not re.fullmatch(r'[0-9a-f]{32}', run_id):
            raise ManagerError('잘못된 Run ID입니다.')
        if (not math.isfinite(wait_seconds) or wait_seconds <= 0 or
                not math.isfinite(poll_seconds) or poll_seconds < .1 or
                not 0 <= log_chars <= 65536):
            raise ManagerError('대기 시간은 양수, 조회 간격은 0.1초 이상, 로그 길이는 0~65536이어야 합니다.')
        self.metrics = []
        start = time.monotonic()
        prefix = '/api/jobs/' + job
        result = {'job_id': job, 'run_id': run_id, 'success': False}
        submitted = False

        def event(stage, record=None):
            value = {'stage': stage, 'observed_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                     'job_id': job, 'run_id': result['run_id']}
            if record:
                value.update({k: record.get(k) for k in ('state', 'created_at', 'started_at', 'finished_at')})
            self.emit(value)

        try:
            session = self.request('/api/session', 'session')
            if session.get('root') != self.root:
                raise ManagerError('Dashboard 프로젝트 루트가 일치하지 않습니다.')
            item = self.request(prefix, 'identify')
            result['name'] = item['config']['name']
            event('identified')
            if run_id:
                record = self.request(prefix + '/runs/' + run_id, 'status')
            else:
                from runner.parameters import resolve_parameters
                # Validate the discovered contract before the one and only POST.
                applied = resolve_parameters(item['config'], parameters)
                submitted = True
                record = self.request(prefix + '/runs', 'submit', session['csrf'],
                                      body={'parameters': applied} if item['config'].get('parameters') else {})
                result['run_id'] = run_id = record['id']
                event('accepted', record)
            if 'parameters' in record:
                result.update(parameters=record['parameters'],
                              parameter_contract_version=record['parameter_contract_version'])
            deadline = time.monotonic() + wait_seconds
            previous = None
            while record['state'] in ('queued', 'running'):
                if record['state'] != previous:
                    event('waiting', record)
                    previous = record['state']
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    event('wait_timeout', record)
                    result.update({k: record.get(k) for k in ('created_at', 'started_at', 'finished_at')})
                    result.update(state=record['state'], wait_timed_out=True,
                                  resume='run-dashboard ' + job + ' --run ' + run_id)
                    return result
                time.sleep(min(poll_seconds, remaining))
                if time.monotonic() >= deadline:
                    continue
                record = self.request(prefix + '/runs/' + run_id, 'status',
                                      timeout=min(10, max(.001, deadline-time.monotonic())))
            result.update({k: record.get(k) for k in ('state', 'exit_code', 'created_at', 'started_at', 'finished_at')})
            result['success'] = record['state'] == 'succeeded' and record.get('exit_code') == 0
            event('completed' if result['success'] else 'failed', record)
            result['logs'] = {}
            for stream in ('stdout', 'stderr'):
                page = self.request(prefix + '/runs/' + run_id + '/logs?' + urlencode({'stream': stream, 'offset': 0}), 'logs')
                excerpt = page['text'][:log_chars]
                result['logs'][stream] = {'text': excerpt, 'next_offset': (page['offset'] if excerpt == page['text'] else len(excerpt.encode('utf-8'))),
                    'fetched_offset': page['offset'], 'excerpt_limited': len(excerpt) < len(page['text']),
                    'may_have_more': page['offset'] >= 65536, 'truncated': page['truncated']}
            event('results')
            params = dict(query or {})
            params['run'] = run_id
            saved = self.request(prefix + '/results?' + urlencode(params, doseq=True), 'results')
            for item in saved.get('items', []):
                item['data'] = {k: v for k, v in item['data'].items() if k in fields}
            result['results'] = saved
            return result
        except ManagerError as exc:
            result.update(success=False, observation_error=str(exc))
            event('observation_failed')
            if run_id:
                result['resume'] = 'run-dashboard ' + job + ' --run ' + run_id
            elif submitted:
                result['submission_uncertain'] = exc.status != 409
                result['next_action'] = 'runs ' + job + '; inspect existing runs before any new submission'
                # A response can be lost after acceptance. Read history once; never guess
                # which concurrent request owns a Run and never repeat the POST.
                try:
                    runs = self.request(prefix + '/runs', 'reconcile')
                    result['existing_runs'] = [{k: r.get(k) for k in
                        ('id', 'state', 'created_at', 'started_at', 'finished_at')} for r in runs[:5]]
                except ManagerError:
                    pass
            return result
        finally:
            result['timings'] = {'total_ms': round((time.monotonic()-start)*1000, 3),
                                 'http_requests': len(self.metrics), 'requests': self.metrics}
