"""File-backed retention. Only registered run outputs and package ZIPs are managed."""
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import stat

from runner.common import ManagerError, contained, identifier, read_json, write_json

DEFAULT_POLICY = {"package_keep": 5, "package_auto": False, "output_days": None,
                  "output_runs": None, "output_auto": False, "pins": [], "rollback_packages": []}


def tree_size(path):
    if not path.exists() and not path.is_symlink():
        return 0
    if path.is_symlink():
        raise ManagerError("심볼릭 링크 데이터는 관리할 수 없습니다.", 409)
    if path.is_file():
        return path.stat().st_size
    total = 0
    for base, dirs, files in os.walk(path, followlinks=False):
        for name in dirs + files:
            entry = Path(base) / name
            if entry.is_symlink() or not (entry.is_dir() or stat.S_ISREG(entry.stat().st_mode)):
                raise ManagerError("일반 파일과 디렉터리만 관리할 수 있습니다.", 409)
            if entry.is_file():
                total += entry.stat().st_size
    return total


class Lifecycle:
    def __init__(self, store):
        self.store = store

    def path(self, relative):
        return contained(self.store.root, relative)

    def policy_path(self, job_id):
        return self.path("runtime/lifecycle/" + identifier(job_id) + ".json")

    def policy(self, job_id):
        return {**DEFAULT_POLICY, **read_json(self.policy_path(job_id), {})}

    def save(self, job_id, values):
        if not isinstance(values, dict) or values.keys() - DEFAULT_POLICY.keys():
            raise ManagerError("알 수 없는 보존 정책입니다.")
        with self.store.job_lock(job_id, "lifecycle"), self.store.job_lock(job_id):
            policy = {**self.policy(job_id), **values}
            for key in ("package_keep", "output_days", "output_runs"):
                value = policy[key]
                if value is None and key != "package_keep":
                    continue
                if type(value) is not int or value < 0:
                    raise ManagerError("보존 값은 0 이상의 정수 또는 무기한(null)이어야 합니다.")
            for key in ("package_auto", "output_auto"):
                if type(policy[key]) is not bool:
                    raise ManagerError("자동 정리는 boolean이어야 합니다.")
            from deployments.packages import Packages
            for key in ("pins", "rollback_packages"):
                if not isinstance(policy[key], list):
                    raise ManagerError("보호 Package는 배열이어야 합니다.")
                for package_id in policy[key]:
                    Packages(self.store).metadata(package_id, job_id)
            write_json(self.policy_path(job_id), policy)
            return policy

    def paths(self, job_id, run_id=None, create=False):
        base = "runtime/job-data/" + identifier(job_id)
        result = {"SCRIPT_MANAGER_JOB_DATA_DIR": self.path(base),
                  "SCRIPT_MANAGER_OUTPUT_ROOT": self.path(base + "/output"),
                  "SCRIPT_MANAGER_STATE_DIR": self.path(base + "/state"),
                  "SCRIPT_MANAGER_JOB_DATA_ROOT": self.path("runtime/job-data"),
                  "SCRIPT_MANAGER_WORKSPACE_DIR": self.path("workspace")}
        if run_id is not None:
            self.run_id(run_id)
            result["SCRIPT_MANAGER_OUTPUT_DIR"] = self.path(base + "/output/" + run_id)
            result["SCRIPT_MANAGER_RUN_ID"] = run_id
        if create:
            for key, value in result.items():
                if key.endswith(("DIR", "ROOT")):
                    value.mkdir(parents=True, exist_ok=True, mode=0o700)
        return {key: str(value) for key, value in result.items()}

    @staticmethod
    def run_id(value):
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
            raise ManagerError("잘못된 실행 ID입니다.")
        return value

    def protected(self, job_id, policy):
        from deployments.client import Deployment
        records = Deployment(self.store).history(job_id)
        reasons = {}
        def protect(pid, reason):
            if pid:
                reasons.setdefault(pid, []).append(reason)
        for pid in policy["pins"]:
            protect(pid, "pin")
        for pid in policy["rollback_packages"]:
            protect(pid, "rollback")
        # Resolve rollback releases through immutable deploy receipts. Uncertain operations
        # retain every referenced ZIP: a failed SSH response may already have switched current.
        mapping = {(r['target'], r.get('release')): r.get('package_id') for r in reversed(records)
                   if r.get('action') == 'deploy' and r.get('package_id')}
        targets = {}
        for row in records:
            if row.get('status') in ('pending', 'unconfirmed'):
                protect(row.get('package_id') or mapping.get((row['target'], row.get('release'))), 'unconfirmed')
            if row.get('status') != 'verified' or row.get('action') not in ('deploy', 'rollback'):
                continue
            seen = targets.setdefault(row['target'], [])
            release = row.get('release')
            if release not in seen and len(seen) < 2:
                protect(mapping.get((row['target'], release)), 'current' if not seen else 'rollback')
                seen.append(release)
        return reasons

    def packages(self, job_id):
        from deployments.packages import Packages
        policy = self.policy(job_id)
        protected = self.protected(job_id, policy)
        rows = Packages(self.store).list(job_id)
        available = [row for row in rows if row['zip_available']]
        retained = {row['id'] for row in available[:policy['package_keep']]}
        for row in rows:
            row['protection'] = protected.get(row['id'], [])
            row['cleanup_candidate'] = row['zip_available'] and row['id'] not in retained and not row['protection']
        return rows

    def outputs(self, job_id):
        # Old scripts and arbitrary directories without the manager's exact run reference
        # are deliberately excluded from retention.
        base = "runtime/job-data/" + identifier(job_id)
        rows = []
        policy = self.policy(job_id)
        runs = self.path("runtime/runs/" + job_id)
        if not runs.exists():
            return rows
        records = []
        for entry in runs.iterdir():
            if not re.fullmatch(r"[0-9a-f]{32}", entry.name):
                continue
            record_path = self.path("runtime/runs/" + job_id + "/" + entry.name + "/run.json")
            record = read_json(record_path, {})
            if (record.get('id') == entry.name and record.get('job_id') == job_id
                    and record.get('managed_output') == base + '/output/' + entry.name):
                records.append(record)
        records.sort(key=lambda r: r['created_at'], reverse=True)
        completed = 0
        for record in records:
            run_id = record['id']
            output = self.path(base + '/output/' + run_id)
            trash = self.path(base + '/trash/' + run_id)
            if output.exists() and trash.exists():
                raise ManagerError("Output과 휴지통 경로가 충돌합니다.", 409)
            trashed = trash.exists()
            if not output.exists() and not trashed:
                continue
            active = record['state'] in ('queued', 'running')
            candidate = False
            if not trashed and not active:
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(record.get('finished_at') or record['created_at'])).total_seconds() / 86400
                candidate = ((policy['output_runs'] is not None and completed >= policy['output_runs']) or
                             (policy['output_days'] is not None and age >= policy['output_days']))
                completed += 1
            rows.append({'id': run_id, 'bytes': tree_size(trash if trashed else output),
                         'trashed': trashed, 'active': active, 'cleanup_candidate': candidate})
        return rows

    def preview(self, job_id):
        packages, outputs = self.packages(job_id), self.outputs(job_id)
        paths = self.paths(job_id)
        usage = {'packages': sum(p['zip_bytes'] for p in packages),
                 'output': sum(p['bytes'] for p in outputs if not p['trashed']),
                 'trash': sum(p['bytes'] for p in outputs if p['trashed']),
                 'state': tree_size(Path(paths['SCRIPT_MANAGER_STATE_DIR'])),
                 'workspace': tree_size(Path(paths['SCRIPT_MANAGER_WORKSPACE_DIR']))}
        return {'policy': self.policy(job_id), 'paths': paths, 'usage': usage,
                'packages': packages, 'outputs': outputs,
                'package_reclaim_bytes': sum(p['zip_bytes'] for p in packages if p['cleanup_candidate']),
                'output_move_bytes': sum(p['bytes'] for p in outputs if p['cleanup_candidate']),
                'last_automatic': {resource: read_json(self.path('runtime/lifecycle/' + identifier(job_id) + '-' + resource + '-last.json')) for resource in ('packages', 'output')}}

    def cleanup(self, job_id, resource, expected=None):
        if resource not in ('packages', 'output'):
            raise ManagerError("packages 또는 output만 정리할 수 있습니다.")
        # Same ordering as execution start/delete. Refuse any active run, even if
        # its record is stale. All package consumers share the lifecycle lock.
        with self.store.job_lock(job_id, 'operation'), self.store.job_lock(job_id, 'run', False), self.store.job_lock(job_id, 'lifecycle'), self.store.job_lock(job_id):
            rows = self.packages(job_id) if resource == 'packages' else self.outputs(job_id)
            candidates = [r for r in rows if r['cleanup_candidate']]
            ids = [r['id'] for r in candidates]
            if expected is not None and expected != ids:
                raise ManagerError("정리 대상이 변경되었습니다. 미리보기를 다시 확인하세요.", 409)
            completed, errors = [], []
            for row in candidates:
                try:
                    if resource == 'packages':
                        # ZIP presence is the authoritative status. Metadata and receipts
                        # are immutable and never need a second write after unlink.
                        archive = self.path('deployments/packages/' + row['id'] + '/package.zip')
                        from deployments.packages import Packages
                        package = Packages(self.store).get(row["id"], job_id)
                        write_json(self.path("deployments/packages/" + row["id"] + "/manifest.json"), package["manifest"])
                        if os.name == "nt":
                            archive.chmod(0o600)
                        archive.unlink()
                    else:
                        base = 'runtime/job-data/' + identifier(job_id)
                        source = self.path(base + '/output/' + row['id'])
                        target = self.path(base + '/trash/' + row['id'])
                        target.parent.mkdir(parents=True, exist_ok=True)
                        if target.exists():
                            raise ManagerError("휴지통 경로가 이미 존재합니다.", 409)
                        os.rename(source, target)
                    completed.append(row['id'])
                except (OSError, ManagerError) as exc:
                    errors.append({'id': row['id'], 'error': str(exc)})
            return {'completed': completed, 'errors': errors}

    def restore(self, job_id, run_id):
        self.run_id(run_id)
        with self.store.job_lock(job_id, 'operation'), self.store.job_lock(job_id, 'run', False), self.store.job_lock(job_id, 'lifecycle'):
            row = next((r for r in self.outputs(job_id) if r['id'] == run_id and r['trashed']), None)
            if row is None:
                raise ManagerError("복구 가능한 Output이 없습니다.", 404)
            base = 'runtime/job-data/' + identifier(job_id)
            dest = self.path(base + '/output/' + run_id)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                raise ManagerError("복구 경로가 이미 존재합니다.", 409)
            os.rename(self.path(base + '/trash/' + run_id), dest)
            return {'restored': run_id}

    def automatic(self, job_id, resources=("packages", "output")):
        for resource, key in (('packages', 'package_auto'), ('output', 'output_auto')):
            if resource in resources and self.policy(job_id)[key]:
                try:
                    result = self.cleanup(job_id, resource)
                except (OSError, ManagerError) as exc:
                    result = {'errors': [{'error': str(exc)}]}
                write_json(self.path('runtime/lifecycle/' + identifier(job_id) + '-' + resource + '-last.json'), result)
