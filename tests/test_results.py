"""Saved-result contracts; all records and compatibility paths are synthetic."""
from contextlib import ExitStack, redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfoNotFoundError

from runner.__main__ import main
from runner.common import ManagerError, write_json
from runner.results import Results, load_rows
from runner.store import Store, default_job


class ResultsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root)
        config = default_job('support', '합성 항목 수집')
        config['description'] = '합성 source-a/source-b 결과 저장'
        self.store.create(config)
        self.results = Results(self.store)
        self.clock = datetime(2026, 11, 13, 3, tzinfo=timezone.utc)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(load_rows.cache_clear)
        legacy_map = patch.dict("runner.results.LEGACY_FILES",
            {"legacy-sample": ("runtime/legacy-sample/releases.jsonl",)})
        legacy_map.start()
        self.addCleanup(legacy_map.stop)

    def save(self, document, run='a' * 32, created='2026-11-13T00:00:00+00:00', state='succeeded', filename='announcements.json'):
        relative = f'runtime/job-data/support/output/{run}'
        write_json(self.root / relative / filename, document)
        write_json(self.root / f'runtime/runs/support/{run}/run.json', {
            'id': run, 'job_id': 'support', 'state': state, 'created_at': created,
            'started_at': created, 'finished_at': created, 'managed_output': relative})
        return self.root / relative / filename

    def grouped(self):
        return {'generated_at_utc': '2026-11-13T00:00:00+00:00', 'timezone': 'Asia/Seoul', 'complete': True,
                'sources': {'source-a': {'status': 'success'}},
                'announcements': {'source-a': {'open': [
                    {'uid': 'source-a:1', 'title': '용인 AI 창업', 'url': 'https://example.test/1', 'end_raw': '20261120', 'raw': {'ignored': 'secretword'}},
                    {'uid': 'source-a:2', 'title': '서울 AI 창업', 'end_raw': '20261121'}],
                    'uncertain': [{'uid': 'source-a:3', 'title': '용인 교육', 'end_raw': ''}]}}}

    def query(self, **kwargs):
        return self.results.query('support', now=self.clock, **kwargs)

    def codes(self, result):
        return {w['code'] for w in result['warnings']}

    def test_catalog_exposes_purpose_artifacts_and_last_run_without_code(self):
        path = self.save(self.grouped())
        row = self.results.catalog('합성')['jobs'][0]
        self.assertEqual(row['purpose'], '합성 source-a/source-b 결과 저장')
        self.assertEqual(row['last_run']['id'], 'a' * 32)
        self.assertEqual(row['artifacts'][0]['path'], str(path.relative_to(self.root)))
        self.assertNotIn('config', row)
        self.assertEqual(self.results.catalog('없는목적')['jobs'], [])

    def test_natural_language_conditions_are_translated_to_deterministic_filters(self):
        # "오늘 수집한 용인 AI 모집 중 공고" -> literal existing status open.
        self.save(self.grouped())
        result = self.query(keywords=['용인', 'ai'], status='open', source='SOURCE-A',
                            date_from='2026-11-13', date_to='2026-11-13')
        self.assertEqual(result['total'], 1)
        item = result['items'][0]
        self.assertEqual(item['data']['uid'], 'source-a:1')
        self.assertEqual(item['provenance']['run_id'], 'a' * 32)
        self.assertEqual(item['provenance']['url'], 'https://example.test/1')
        self.assertEqual(item['collected_at'], '2026-11-13T00:00:00+00:00')
        self.assertFalse(item['stale'])
        self.assertNotIn('raw', item['data'])
        self.assertEqual(result['available_statuses'], ['open', 'uncertain'])
        self.assertEqual(self.query(keywords=['secretword'])['total'], 0)

    def test_research_format_record_collection_time_and_stored_status(self):
        self.save({'generated_at': '2026-11-13T09:00:00+09:00', 'status': '완료',
                   'announcements': [{'title': 'AI 연구', 'source': 'source-b', 'fresh': False,
                                      'last_seen_at': '2026-11-01T09:00:00+09:00',
                                      'deadline': {'status': '모집 중', 'ends_at': '2026-11-20T12:00:00+09:00'}}]}, filename='report.json')
        result = self.query(status='모집 중')
        self.assertIn('stale_data', self.codes(result))
        self.assertEqual(result['items'][0]['collected_at'], '2026-11-01T09:00:00+09:00')
        self.assertEqual(self.query(date_from='2026-11-13')['total'], 0)
        self.assertEqual(self.query(date_field='deadline.ends_at', date_from='2026-11-20', date_to='2026-11-20')['total'], 1)

    def test_yongin_substring_counts_and_cross_source_rows_are_preserved(self):
        # Literal keyword search also matches 고용인원/고용인력. Relevance exclusions belong
        # to the answer; similar titles across sources are not silently merged.
        rows = [{'uid': f'source-b:{i}', 'title': f'용인 사업 {i}', 'source': 'source-b'}
                for i in range(8)]
        rows += [{'uid': 'source-a:jobs', 'title': '청년 지원', 'target': '용인 소재 기업', 'source': 'source-a'},
                 {'uid': 'source-b:jobs', 'title': '청년 지원', 'target': '용인 소재 기업', 'source': 'source-b'}]
        excluded = {f'source-b:other{i}' for i in range(4)}
        rows += [{'uid': uid, 'title': '타지역 지원', 'summary': '상시고용인원 요건'} for uid in sorted(excluded)]
        rows[-1].update(title='경남 신규고용인력 지원', summary='선정된 고용인원 지원')
        self.save({'announcements': rows}, filename='report.json')
        result = self.query(keywords=['용인'], limit=100)
        self.assertEqual((result['total'], len(result['items']), result['has_more']), (14, 14, False))
        displayed = [r for r in result['items'] if r['data']['uid'] not in excluded]
        self.assertEqual(result['total'] - len(excluded) - 0, len(displayed))
        self.assertEqual(len(displayed), 10)
        self.assertTrue({'source-a:jobs', 'source-b:jobs'} <= {r['data']['uid'] for r in displayed})

    def test_date_boundaries_timezone_and_missing_dates(self):
        self.save([{'title': '직전', 'collected_at': '2026-11-12T14:59:59+00:00'},
                   {'title': '시작', 'collected_at': '2026-11-12T15:00:00+00:00'},
                   {'title': '끝', 'collected_at': '2026-11-13T14:59:59.999999+00:00'},
                   {'title': '이후', 'collected_at': '2026-11-13T15:00:00+00:00'}])
        result = self.query(date_from='2026-11-13', date_to='2026-11-13')
        self.assertEqual([r['data']['title'] for r in result['items']], ['시작', '끝'])
        self.assertEqual(self.query(date_field='missing', date_from='2026-11-13')['total'], 0)

    def test_cached_failure_separates_generation_collection_and_original_run(self):
        collected = '2026-11-13T00:00:00+00:00'
        row = {'uid': 'source-a:1', 'title': '용인', 'fresh': True, 'last_seen_at': collected}
        self.save({'announcements': [row], 'generated_at': collected}, filename='report.json')
        generated = '2026-11-13T02:00:00+00:00'
        self.save({'announcements': [{**row, 'fresh': False}], 'generated_at': generated, 'status': '실패'},
                  run='b' * 32, created=generated, state='failed', filename='report.json')
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result = self.query()
        snapshot = result['snapshots'][0]
        self.assertEqual(snapshot['generated_at'], generated)
        self.assertEqual(snapshot['collected_at'], collected)
        self.assertEqual((snapshot['confirmed_count'], snapshot['cached_count']), (0, 1))
        self.assertTrue(snapshot['stale'])
        provenance = result['items'][0]['provenance']
        self.assertEqual(provenance['run_id'], 'b' * 32)
        self.assertEqual(provenance['collection_run_id'], 'a' * 32)
        self.assertEqual(provenance['collection_run_basis'], 'saved_record_match')
        self.assertIn('partial_result', self.codes(result))
        self.assertIn('stale_data', self.codes(result))
        after = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_collection_run_is_unknown_without_unique_fresh_evidence(self):
        collected = '2026-11-13T00:00:00+00:00'
        fresh = {'uid': 'source-a:1', 'fresh': True, 'last_seen_at': collected}
        self.save({'announcements': [fresh]}, filename='report.json')
        self.save({'announcements': [fresh]}, run='c' * 32, filename='report.json')
        self.save({'announcements': [{**fresh, 'fresh': False},
                                     {'uid': 'missing', 'fresh': False, 'last_seen_at': collected}]},
                  run='b' * 32, created='2026-11-13T02:00:00+00:00', state='failed', filename='report.json')
        for item in self.query()['items']:
            self.assertIsNone(item['provenance']['collection_run_id'])
            self.assertEqual(item['provenance']['collection_run_basis'], 'unknown')

    def test_empty_failed_report_does_not_substitute_generation_for_collection(self):
        self.save({'announcements': [], 'status': '실패', 'generated_at': '2026-11-13T00:00:00+00:00',
                   'last_collected_at': None, 'confirmed_count': 0, 'cached_count': 0},
                  state='failed', filename='report.json')
        result = self.query()
        self.assertIsNone(result['snapshots'][0]['collected_at'])
        self.assertIn('unknown_collection_time', self.codes(result))
        self.assertIn('partial_result', self.codes(result))

    def test_partial_result_preserves_current_and_cached_origins(self):
        collected = '2026-11-13T00:00:00+00:00'
        row = {'uid': 'source-a:1', 'fresh': True, 'last_seen_at': collected}
        self.save({'announcements': [row]}, filename='report.json')
        generated = '2026-11-13T02:00:00+00:00'
        self.save({'generated_at': generated, 'status': '부분 실패', 'announcements': [
            {**row, 'fresh': False}, {'uid': 'source-b:2', 'fresh': True, 'last_seen_at': generated}]},
            run='b' * 32, created=generated, state='failed', filename='report.json')
        result = self.query()
        self.assertEqual((result['snapshots'][0]['confirmed_count'], result['snapshots'][0]['cached_count']), (1, 1))
        self.assertEqual([m['provenance']['collection_run_id'] for m in result['items']], ['a' * 32, 'b' * 32])

    def test_compact_dates_and_pagination(self):
        self.save(self.grouped())
        result = self.query(date_field='end_raw', date_from='2026-11-20', date_to='2026-11-20')
        self.assertEqual(result['total'], 1)
        result = self.query(limit=1, offset=1)
        self.assertEqual(result['total'], 3)
        self.assertTrue(result['has_more'])
        self.assertEqual(result['items'][0]['data']['uid'], 'source-a:2')
        self.assertEqual(self.query(offset=999)['items'], [])

    def test_default_korean_timezone_without_os_timezone_database(self):
        self.save(self.grouped())
        with patch('runner.results.ZoneInfo', side_effect=ZoneInfoNotFoundError):
            self.assertEqual(self.query(date_from='2026-11-13', date_to='2026-11-13')['total'], 3)
            self.assertEqual(self.query(timezone_name='UTC')['total'], 3)
            with self.assertRaises(ManagerError):
                self.query(timezone_name='America/New_York')

    def test_empty_missing_and_old_are_distinct(self):
        self.assertIn('no_saved_results', self.codes(self.query()))
        self.save({'announcements': [], 'generated_at': '2020-01-01T00:00:00+00:00'})
        result = self.query()
        self.assertIn('no_matches', self.codes(result))
        self.assertIn('stale_data', self.codes(result))
        self.assertNotIn('no_saved_results', self.codes(result))
        self.assertEqual(len(result['snapshots']), 1)

    def test_no_match_does_not_fallback_to_older_snapshot(self):
        self.save([{'title': 'old AI'}], created='2026-11-12T00:00:00+00:00')
        self.save([], run='b' * 32)
        result = self.query(keywords=['AI'])
        self.assertEqual(result['total'], 0)
        self.assertEqual(result['snapshots'][0]['run']['id'], 'b' * 32)
        self.assertEqual(self.query(keywords=['AI'], all_runs=True)['total'], 1)
        self.assertEqual(self.query(run_id='a' * 32)['total'], 1)

    def test_latest_failure_missing_output_and_partial_result(self):
        self.save(self.grouped())
        self.save({'complete': False, 'announcements': []}, run='b' * 32,
                  created='2026-11-13T01:00:00+00:00', state='failed')
        result = self.query()
        self.assertIn('partial_result', self.codes(result))
        self.assertEqual(result['total'], 0)
        path = self.root / ('runtime/job-data/support/output/' + 'b' * 32 + '/announcements.json')
        path.unlink()
        result = self.query()
        self.assertIn('older_run', self.codes(result))
        self.assertEqual(result['last_run']['state'], 'failed')
        self.assertEqual(result['total'], 3)

    def test_running_output_is_not_read_or_recovered(self):
        self.save(self.grouped(), state='running')
        result = self.query()
        self.assertIn('no_saved_results', self.codes(result))
        record = json.loads((self.root / ('runtime/runs/support/' + 'a' * 32 + '/run.json')).read_text())
        self.assertEqual(record['state'], 'running')

    def test_no_network_execution_credentials_or_source_reads(self):
        self.save(self.grouped())
        original = Path.open
        def guarded(path, *args, **kwargs):
            self.assertNotEqual(path.name, '.env')
            self.assertNotEqual(path.suffix, '.py')
            self.assertNotIn('source', path.parts)
            return original(path, *args, **kwargs)
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with ExitStack() as stack:
            stack.enter_context(patch('pathlib.Path.open', guarded))
            for target in ('socket.create_connection', 'subprocess.Popen', 'runner.execution.Execution.start'):
                stack.enter_context(patch(target, side_effect=AssertionError(target)))
            self.results.catalog()
            self.assertEqual(self.query()['total'], 3)
        after = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_json_markdown_are_not_double_counted_and_explicit_file_works(self):
        self.save({'announcements': []}, filename='report.json')
        base = self.root / ('runtime/job-data/support/output/' + 'a' * 32)
        (base / 'report.md').write_text('# 보고서\n용인 AI')
        write_json(base / 'api-diagnostics.json', {'status': 200})
        self.assertEqual(self.query()['scanned'], 0)
        self.assertEqual(self.query(file='report.md', keywords=['용인'])['total'], 1)
        self.assertEqual(self.query(file='missing.json')['total'], 0)

    def test_csv_jsonl_and_generic_json_compatibility(self):
        path = self.save([])
        path.unlink()
        (path.parent / 'records.csv').write_text('title,status,source\nAI,open,source-b\n', encoding='utf-8-sig')
        (path.parent / 'records.jsonl').write_text('{"title":"AI", "status":"open"}\n')
        result = self.query(status='open')
        self.assertEqual(result['total'], 2)
        write_json(path, {'items': [{'title': '교육'}]})
        self.assertEqual(self.query(file=path.name)['items'][0]['data']['title'], '교육')

    def test_legacy_file_retains_location_and_record_timestamp(self):
        self.store.create(default_job('legacy-sample'))
        path = self.root / 'runtime/legacy-sample/releases.jsonl'
        path.parent.mkdir()
        path.write_text('{"repository":"a/b", "detected_at":"2026-11-13T00:00:00Z", "html_url":"https://example.test/r"}\n')
        result = self.results.query('legacy-sample', now=self.clock)
        self.assertEqual(result['total'], 1)
        self.assertIsNone(result['items'][0]['provenance']['run_id'])
        self.assertFalse(result['items'][0]['stale'])
        self.assertEqual(result['items'][0]['provenance']['url'], 'https://example.test/r')

    def test_cache_invalidates_on_update_and_callers_cannot_mutate_it(self):
        path = self.save(self.grouped())
        result = self.query()
        result['items'][0]['data']['title'] = 'mutated'
        self.assertEqual(self.query()['items'][0]['data']['title'], '용인 AI 창업')
        write_json(path, [])
        self.assertEqual(self.query()['total'], 0)

    def test_corrupt_output_is_reported_without_falling_back(self):
        path = self.save(self.grouped())
        path.write_text('{broken')
        result = self.query()
        self.assertIn('unreadable_result', self.codes(result))
        self.assertIn('no_saved_results', self.codes(result))

    def test_symlinks_are_not_followed(self):
        path = self.save(self.grouped())
        path.unlink()
        outside = self.root / 'outside.json'
        outside.write_text('[{"title":"must not read"}]')
        path.symlink_to(outside)
        result = self.query()
        self.assertEqual(result['total'], 0)
        self.assertIn('unreadable_output', self.codes(result))

    def test_bad_filters_are_rejected(self):
        for arguments in ({'limit': 0}, {'offset': -1}, {'stale_hours': float('nan')},
                          {'stale_hours': float('inf')}, {'date_from': 'bad'},
                          {'date_from': '2026-11-14', 'date_to': '2026-11-13'},
                          {'date_field': ''}, {'timezone_name': 'invalid'}, {'keywords': 'AI'},
                          {'keywords': ['']}, {'file': '../.env'}, {'file': '/tmp/file'},
                          {'run_id': '../'}, {'run_id': 'a' * 32, 'all_runs': True}):
            with self.subTest(arguments=arguments), self.assertRaises(ManagerError):
                self.query(**arguments)

    def test_unknown_run_and_job(self):
        with self.assertRaises(ManagerError) as error:
            self.query(run_id='b' * 32)
        self.assertEqual(error.exception.status, 404)
        with self.assertRaises(ManagerError):
            self.results.query('../')

    def test_file_size_limit_and_unknown_time(self):
        path = self.save([{'title': 'AI'}])
        with patch('runner.results.MAX_FILE_BYTES', 1):
            self.assertIn('unreadable_result', self.codes(self.query()))
        load_rows.cache_clear()
        path.unlink()
        self.store.create(default_job('legacy-sample'))
        legacy = self.root / 'runtime/legacy-sample/releases.jsonl'
        legacy.parent.mkdir()
        legacy.write_text('{"repository":"unknown"}\n')
        self.assertIn('unknown_collection_time', self.codes(self.results.query('legacy-sample')))

    def test_cli_and_error_exit_codes(self):
        self.save(self.grouped())
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(['--root', str(self.root), 'result-jobs', '--keyword', '합성']), 0)
        self.assertEqual(json.loads(output.getvalue())['jobs'][0]['id'], 'support')
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(['--root', str(self.root), 'results', 'support', '--keyword', '용인', '--status', 'open']), 0)
        self.assertEqual(json.loads(output.getvalue())['total'], 1)
        with redirect_stderr(io.StringIO()):
            self.assertEqual(main(['--root', str(self.root), 'results', 'support', '--from', 'bad']), 1)


if __name__ == '__main__':
    unittest.main()
