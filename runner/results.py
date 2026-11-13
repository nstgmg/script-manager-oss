"""Read-only discovery and deterministic filtering of existing file-backed results.

Natural language interpretation belongs to the calling agent. This module never
imports Job code, reads credentials, starts Jobs, or accesses the network.
"""
import csv
from copy import deepcopy
from datetime import datetime, time, timedelta, timezone
from functools import lru_cache
import io
import json
from pathlib import Path
import re
from time import perf_counter
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from runner.common import ManagerError, contained, identifier

MAX_FILE_BYTES = 32 * 1024 * 1024
SUPPORTED = {'.json', '.jsonl', '.csv', '.md', '.txt'}
RUN_FIELDS = ('id', 'state', 'created_at', 'started_at', 'finished_at', 'exit_code')
# Optional compatibility map. The generic distribution has no user Job paths.
LEGACY_FILES = {}


def timestamp(value, zone=timezone.utc):
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    try:
        if re.fullmatch(r'\d{8}', value):
            result = datetime.strptime(value, '%Y%m%d')
        else:
            result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result if result.tzinfo else result.replace(tzinfo=zone)
    except ValueError:
        return None


def field(record, key):
    value = record
    for part in key.split('.'):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def rows_from_json(document):
    """Adapt existing envelopes; do not mistake changes/diagnostics for results."""
    if isinstance(document, list):
        return [(row, {}) for row in document], {}
    if not isinstance(document, dict):
        raise ValueError('JSON 결과는 객체 또는 배열이어야 합니다.')
    for key in ('announcements', 'records', 'results', 'items'):
        if key not in document:
            continue
        values = document[key]
        if isinstance(values, list):
            return [(row, {}) for row in values], document
        if key == 'announcements' and isinstance(values, dict):
            rows = []
            for source, groups in values.items():
                if not isinstance(groups, dict):
                    raise ValueError('공고 출처별 그룹 구조가 올바르지 않습니다.')
                for status, entries in groups.items():
                    if not isinstance(entries, list):
                        raise ValueError('공고 그룹은 배열이어야 합니다.')
                    rows.extend((row, {'source': source, 'status': status}) for row in entries)
            return rows, document
        raise ValueError(key + ' 결과 구조를 지원하지 않습니다.')
    # Ordinary single-record JSON remains queryable without schema migration.
    return [(document, {})], document


@lru_cache(maxsize=4)
def load_rows(path_string, mtime_ns, size, inode, ctime_ns):
    """Small stat-keyed process cache; no persistent index or database."""
    path = Path(path_string)
    if size > MAX_FILE_BYTES:
        raise ValueError('결과 파일이 조회 한도 32 MiB를 초과합니다.')
    with path.open('rb') as stream:
        raw = stream.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError('결과 파일이 조회 한도 32 MiB를 초과합니다.')
    text = raw.decode('utf-8-sig')
    if path.suffix.lower() == '.json':
        rows, document = rows_from_json(json.loads(text))
    elif path.suffix.lower() == '.jsonl':
        rows, document = [(json.loads(line), {}) for line in text.splitlines() if line.strip()], {}
    elif path.suffix.lower() == '.csv':
        rows, document = [(dict(row), {}) for row in csv.DictReader(io.StringIO(text))], {}
    else:
        rows, document = [({'text': text}, {})], {}
    result = []
    for number, (row, context) in enumerate(rows, 1):
        if not isinstance(row, dict):
            row = {'value': row}
        # Raw API payloads duplicate searchable common fields and inflate replies.
        data = {key: value for key, value in row.items() if key != 'raw'}
        status = field(data, 'deadline.status') or data.get('recruitment_status') or data.get('status') or context.get('status')
        if not isinstance(status, (str, int, float, bool, type(None))):
            status = None
        result.append((data, context, number, status,
                       json.dumps(data, ensure_ascii=False, sort_keys=True).casefold()))
    metadata = {key: document.get(key) for key in
                ('generated_at_utc', 'generated_at', 'collected_at', 'timezone', 'complete', 'status', 'sources')}
    for key in ('last_collected_at', 'confirmed_count', 'cached_count'):
        if key in document:
            metadata[key] = document[key]
    return result, metadata


class Results:
    def __init__(self, store):
        self.store = store

    def collection_origins(self, job_id, runs, matches):
        """Resolve cached records from saved evidence, without changing State/Output.

        A matching timestamp alone is insufficient: require the same uid and an
        explicit fresh record in that run. Missing/ambiguous evidence stays unknown.
        """
        needed = {(m['data'].get('uid'), m['collected_at']) for m in matches
                  if m['data'].get('fresh') is False and isinstance(m['data'].get('uid'), str)
                  and isinstance(m['collected_at'], str)}
        if not needed:
            return {}
        found = {key: set() for key in needed}
        for run in runs:
            start = timestamp(run.get('started_at') or run.get('created_at'))
            end = timestamp(run.get('finished_at'))
            if run.get('state') in ('queued', 'running') or not start or not end or not any(
                    start <= timestamp(t) <= end for _, t in needed if timestamp(t)):
                continue
            try:
                for artifact in self.files(job_id, run):
                    if artifact['format'] != 'json' or Path(artifact['path']).name == 'api-diagnostics.json':
                        continue
                    path = contained(self.store.root, artifact['path'], True)
                    stat = path.stat()
                    rows, _ = load_rows(str(path), stat.st_mtime_ns, stat.st_size, stat.st_ino, stat.st_ctime_ns)
                    for data, *_ in rows:
                        if not isinstance(data.get('uid'), str) or not isinstance(data.get('last_seen_at'), str):
                            continue
                        key = (data.get('uid'), data.get('last_seen_at'))
                        if key in found and data.get('fresh') is True:
                            found[key].add(run['id'])
            except (ManagerError, OSError, ValueError, UnicodeError):
                continue
        return {key: next(iter(ids)) for key, ids in found.items() if len(ids) == 1}

    def runs(self, job_id):
        """Read run metadata directly: Execution.get may recover/write run state."""
        folder = contained(self.store.runtime, 'runs/' + identifier(job_id))
        rows, warnings = [], []
        if folder.exists():
            for entry in folder.iterdir():
                if not re.fullmatch(r'[0-9a-f]{32}', entry.name):
                    continue
                try:
                    path = contained(folder, entry.name + '/run.json', True)
                    if path.stat().st_size > 2 * 1024 * 1024:
                        raise ValueError('실행 메타데이터 크기 초과')
                    row = json.loads(path.read_text(encoding='utf-8'))
                    if not isinstance(row, dict) or row.get('id') != entry.name or row.get('job_id') != job_id:
                        raise ValueError('실행 메타데이터 식별자 불일치')
                    rows.append(row)
                except (ManagerError, OSError, ValueError) as exc:
                    warnings.append({'code': 'unreadable_run', 'path': str(entry.relative_to(self.store.root)), 'message': str(exc)})
        rows.sort(key=lambda row: (timestamp(row.get('created_at')) or datetime.min.replace(tzinfo=timezone.utc), row['id']), reverse=True)
        return rows, warnings

    def files(self, job_id, run):
        expected = 'runtime/job-data/' + job_id + '/output/' + run['id']
        if run.get('managed_output') != expected:
            return []
        base = contained(self.store.root, expected)
        if not base.exists():
            return []
        files = []
        for entry in sorted(base.rglob('*')):
            path = contained(self.store.root, str(entry.relative_to(self.store.root)))
            if path.is_file() and not path.name.startswith('.'):
                files.append(self.file_info(path))
        return files

    def file_info(self, path):
        stat = path.stat()
        return {'path': str(path.relative_to(self.store.root)), 'bytes': stat.st_size,
                'format': path.suffix.lower().lstrip('.'), 'queryable': path.suffix.lower() in SUPPORTED}

    def legacy_files(self, job_id):
        result = []
        for relative in LEGACY_FILES.get(job_id, ()):
            path = contained(self.store.root, relative)
            if path.is_file():
                result.append(self.file_info(path))
        return result

    def catalog(self, keyword=None):
        start = perf_counter()
        if keyword is not None and (not isinstance(keyword, str) or not keyword.strip()):
            raise ManagerError('keyword는 비어 있지 않은 문자열이어야 합니다.')
        jobs = []
        for item in self.store.list():
            if item.get('error'):
                jobs.append({'id': item['id'], 'error': item['error']})
                continue
            config = item['config']
            if keyword and keyword.casefold() not in (' '.join((item['id'], config['name'], config.get('description', '')))).casefold():
                continue
            runs, warnings = self.runs(item['id'])
            artifacts = []
            result_run = None
            for run in runs:
                if run.get('state') in ('queued', 'running'):
                    continue
                try:
                    artifacts = self.files(item['id'], run)
                except (ManagerError, OSError) as exc:
                    warnings.append({'code': 'unreadable_output', 'message': str(exc)})
                if artifacts:
                    result_run = run
                    break
            artifacts.extend(self.legacy_files(item['id']))
            jobs.append({'id': item['id'], 'name': config['name'], 'purpose': config.get('description', ''),
                         'readme': 'jobs/' + item['id'] + '/README.md',
                         'last_run': self.run_summary(runs[0]) if runs else None,
                         'result_run': self.run_summary(result_run), 'artifacts': artifacts, 'warnings': warnings})
        return {'jobs': jobs, 'elapsed_ms': round((perf_counter() - start) * 1000, 3)}

    @staticmethod
    def run_summary(run):
        return {key: run.get(key) for key in RUN_FIELDS} if run else None

    def query(self, job_id, *, keywords=(), status=None, source=None, date_from=None, date_to=None,
              date_field='collected_at', timezone_name='Asia/Seoul', stale_hours=24,
              run_id=None, all_runs=False, file=None, limit=20, offset=0, now=None):
        start = perf_counter()
        self.store.get(job_id)
        if any(value is not None and (not isinstance(value, str) or not value.strip()) for value in (status, source, file)):
            raise ManagerError('status, source, file은 비어 있지 않은 문자열이어야 합니다.')
        if file and (Path(file).is_absolute() or '..' in Path(file).parts or '\x00' in file):
            raise ManagerError('file은 결과 파일명 또는 프로젝트 내부 상대 경로여야 합니다.')
        if type(limit) is not int or not 1 <= limit <= 200 or type(offset) is not int or offset < 0:
            raise ManagerError('limit은 1~200, offset은 0 이상의 정수여야 합니다.')
        if isinstance(keywords, str) or not isinstance(keywords, (list, tuple)) or any(not isinstance(k, str) or not k.strip() for k in keywords):
            raise ManagerError('keywords는 비어 있지 않은 문자열 배열이어야 합니다.')
        if isinstance(stale_hours, bool) or not isinstance(stale_hours, (int, float)) or not 0 <= stale_hours <= 876000:
            raise ManagerError('stale_hours는 0~876000의 유한한 숫자여야 합니다.')
        if not isinstance(date_field, str) or not re.fullmatch(r'[\w]+(?:\.[\w]+)*', date_field):
            raise ManagerError('date_field는 점으로 구분한 필드 이름이어야 합니다.')
        try:
            zone = timezone.utc if timezone_name in ('UTC', 'Etc/UTC') else ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            # Windows may lack an IANA database. Keep modern Korean Job dates
            # queryable without adding a dependency solely for the default zone.
            if timezone_name != 'Asia/Seoul':
                raise ManagerError('해당 IANA timezone 데이터를 사용할 수 없습니다.')
            zone = timezone(timedelta(hours=9), 'Asia/Seoul')
        except (ValueError, TypeError):
            raise ManagerError('올바른 IANA timezone이 필요합니다.')
        def bound(value, end=False):
            if value is None:
                return None
            parsed = timestamp(value, zone)
            if parsed is None:
                raise ManagerError('날짜는 YYYY-MM-DD 또는 ISO 8601이어야 합니다.')
            if end and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
                parsed = datetime.combine(parsed.date(), time.max, zone)
            return parsed
        lower, upper = bound(date_from), bound(date_to, True)
        if lower and upper and lower > upper:
            raise ManagerError('시작 날짜는 종료 날짜보다 늦을 수 없습니다.')
        if type(all_runs) is not bool:
            raise ManagerError('all_runs는 boolean이어야 합니다.')
        if run_id is not None and (not isinstance(run_id, str) or not re.fullmatch(r'[0-9a-f]{32}', run_id) or all_runs):
            raise ManagerError('올바른 run ID를 지정하고 all_runs와 함께 사용하지 마세요.')
        runs, warnings = self.runs(job_id)
        selected = []
        for run in runs:
            if run_id and run['id'] != run_id:
                continue
            if run.get('state') in ('queued', 'running'):
                continue
            try:
                artifacts = self.files(job_id, run)
            except (ManagerError, OSError) as exc:
                warnings.append({'code': 'unreadable_output', 'run_id': run['id'], 'message': str(exc)})
                artifacts = []
            if artifacts:
                selected.append((run, artifacts))
                if not all_runs:
                    break
        if run_id and not any(run['id'] == run_id for run in runs):
            raise ManagerError('실행 기록이 없습니다.', 404)
        if selected and runs and selected[0][0]['id'] != runs[0]['id']:
            warnings.append({'code': 'older_run', 'message': '마지막 실행에 조회 가능한 Output이 없어 이전 저장 결과를 사용합니다.'})
        if not selected and not run_id:
            legacy = self.legacy_files(job_id)
            if legacy:
                selected = [(None, legacy)]
                warnings.append({'code': 'legacy_output', 'message': '기존 누적 결과 파일입니다. 실행 ID와 연결되지 않습니다.'})
        matches, snapshots = [], []
        scanned = 0
        statuses, sources = set(), set()
        current = now or datetime.now(timezone.utc)
        for run, artifacts in selected:
            candidates = [a for a in artifacts if a['queryable']]
            if file:
                candidates = [a for a in candidates if a['path'] == file or Path(a['path']).name == file]
            elif any(a['format'] in ('json', 'jsonl', 'csv') for a in candidates):
                candidates = [a for a in candidates if a['format'] in ('json', 'jsonl', 'csv') and Path(a['path']).name != 'api-diagnostics.json']
            for artifact in candidates:
                try:
                    path = contained(self.store.root, artifact['path'], True)
                    stat = path.stat()
                    rows, meta = load_rows(str(path), stat.st_mtime_ns, stat.st_size, stat.st_ino, stat.st_ctime_ns)
                except (ManagerError, OSError, ValueError, UnicodeError, csv.Error) as exc:
                    warnings.append({'code': 'unreadable_result', 'path': artifact['path'], 'message': str(exc)})
                    continue
                generated = meta.get('generated_at_utc') or meta.get('generated_at') or meta.get('collected_at')
                run_time = (run.get('started_at') or run.get('created_at')) if run else None
                snapshot_time = generated or run_time
                record_times = [data.get('last_seen_at') for data, *_ in rows if timestamp(data.get('last_seen_at'))]
                research_rows = [data for data, *_ in rows if isinstance(data.get('fresh'), bool)]
                if record_times or research_rows or 'last_collected_at' in meta:
                    snapshot_time = meta.get('last_collected_at') or max(record_times, key=timestamp, default=None)
                snapshot = {**artifact, 'run': self.run_summary(run), 'collected_at': snapshot_time,
                            'generated_at': generated,
                            'last_collected_at': snapshot_time,
                            'time_basis': ('record' if record_times else 'unknown' if snapshot_time is None else 'result' if generated else 'run_started_at' if run and run.get('started_at')
                                           else 'run_created_at' if run_time else 'unknown'),
                            'complete': meta.get('complete'), 'status': meta.get('status'), 'sources': meta.get('sources')}
                snapshot['stale'] = self.stale(snapshot_time, current, stale_hours)
                if not rows and 'confirmed_count' in meta:
                    snapshot.update(confirmed_count=0, cached_count=0)
                if research_rows:
                    snapshot.update(confirmed_count=sum(data['fresh'] for data in research_rows),
                                    cached_count=sum(not data['fresh'] for data in research_rows))
                    if not snapshot['confirmed_count']:
                        snapshot['stale'] = True
                snapshots.append(snapshot)
                for data, context, number, row_status, searchable in rows:
                    scanned += 1
                    row_source = data.get('source') or context.get('source')
                    if row_status is not None:
                        statuses.add(str(row_status))
                    if isinstance(row_source, str):
                        sources.add(row_source)
                    record_time = data.get('last_seen_at') or data.get('collected_at') or data.get('observed_at') or data.get('detected_at')
                    collected = record_time or (None if data.get('fresh') is False else snapshot_time)
                    value = collected if date_field == 'collected_at' else field(data, date_field)
                    date = timestamp(value, zone)
                    if ((lower and (date is None or date < lower)) or (upper and (date is None or date > upper))
                            or any(k.casefold() not in searchable for k in keywords)
                            or (status is not None and str(row_status).casefold() != status.casefold())
                            or (source is not None and str(row_source).casefold() != source.casefold())):
                        continue
                    stale = self.stale(collected, current, stale_hours)
                    if data.get('fresh') is False:
                        stale = True
                    matches.append({'data': data, 'status': row_status, 'source': row_source,
                                    'collected_at': collected, 'stale': stale,
                                    'provenance': {'job_id': job_id, 'run_id': run['id'] if run else None,
                                                   'path': artifact['path'], 'record': number, 'url': data.get('url') or data.get('html_url'),
                                                   'time_basis': 'record' if record_time else snapshot['time_basis']}})
        origins = self.collection_origins(job_id, runs, matches)
        for match in matches:
            data, provenance = match['data'], match['provenance']
            fresh = data.get('fresh')
            origin = provenance['run_id'] if fresh is True else (
                origins.get((data.get('uid'), match['collected_at']))
                if isinstance(data.get('uid'), str) and isinstance(match['collected_at'], str) else None)
            provenance.update(collection_run_id=origin,
                              collection_run_basis='current_run' if fresh is True else 'saved_record_match' if origin else 'unknown')
        if not snapshots:
            warnings.append({'code': 'no_saved_results', 'message': '조회 가능한 저장 결과가 없습니다. 재수집하지 않았습니다.'})
        elif not matches:
            warnings.append({'code': 'no_matches', 'message': '저장 결과에 조건과 일치하는 항목이 없습니다.'})
        if any(s['stale'] is True for s in snapshots) or any(m['stale'] is True for m in matches):
            warnings.append({'code': 'stale_data', 'message': '오래됐거나 이번 수집에서 확인되지 않은 저장 자료입니다. 현재 상태를 보장하지 않습니다.'})
        if any(s['stale'] is None for s in snapshots) or any(timestamp(m['collected_at']) is None for m in matches):
            warnings.append({'code': 'unknown_collection_time', 'message': '수집 시각을 확인할 수 없는 자료가 있습니다.'})
        if any(s['complete'] is False or s['run'] and s['run']['state'] != 'succeeded' or s['status'] in ('부분 실패', '실패') for s in snapshots):
            warnings.append({'code': 'partial_result', 'message': '실패 또는 불완전한 실행의 저장 결과가 포함되어 있습니다.'})
        return deepcopy({'job_id': job_id, 'mode': 'saved_results_only', 'queried_at': current.isoformat(),
                'filters': {'keywords': list(keywords), 'status': status, 'source': source, 'date_from': date_from,
                            'date_to': date_to, 'date_field': date_field, 'timezone': timezone_name, 'stale_hours': stale_hours},
                'last_run': self.run_summary(runs[0]) if runs else None, 'snapshots': snapshots,
                'total': len(matches), 'scanned': scanned, 'offset': offset, 'limit': limit,
                'available_statuses': sorted(statuses), 'available_sources': sorted(sources),
                'has_more': offset + limit < len(matches), 'items': matches[offset:offset + limit],
                'warnings': warnings, 'elapsed_ms': round((perf_counter() - start) * 1000, 3)})

    @staticmethod
    def stale(value, current, hours):
        parsed = timestamp(value)
        return (current - parsed > timedelta(hours=hours)) if parsed else None
