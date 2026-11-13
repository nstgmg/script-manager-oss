"""Explicit SSH operations only; planning never opens a connection."""
import base64
import io
import json
from pathlib import Path
import re
import shlex
import subprocess
import uuid
import zipfile

from runner.common import ManagerError, contained, digest, identifier, now, read_json, write_json
from runner.store import load_yaml, plain
from deployments.packages import Packages


class Deployment:
    def __init__(self, store, transport=None):
        self.store = store
        self.transport = transport or self._ssh

    def targets(self):
        targets = {}
        for filename in ("targets.yaml", "targets.local.yaml"):
            path = contained(self.store.root, "deployments/" + filename)
            if not path.exists():
                continue
            config = plain(load_yaml(path.read_text()))
            if not isinstance(config, dict) or config.get("version") != 1 or not isinstance(config.get("targets"), dict) or set(config) != {"version", "targets"}:
                raise ManagerError("배포 대상 파일에는 version: 1과 targets 객체가 필요합니다.")
            for key, target in config["targets"].items():
                identifier(key)
                if not isinstance(target, dict) or set(target) != {"ssh_host", "root"}:
                    raise ManagerError("대상에는 ssh_host와 root만 정의하세요.")
                host, root = target["ssh_host"], target["root"]
                if not isinstance(host, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", host):
                    raise ManagerError("ssh_host는 ~/.ssh/config의 안전한 Host 별칭이어야 합니다.")
                if not isinstance(root, str) or not re.fullmatch(r"/[A-Za-z0-9_./-]+", root) or ".." in Path(root).parts or root.rstrip("/") in ("", "/etc", "/usr", "/var", "/home", "/tmp"):
                    raise ManagerError("root는 전용 절대 디렉터리여야 합니다.")
                targets[key] = {"id": key, **target, "root": str(Path(root))}
        return list(targets.values())

    def target(self, target_id):
        identifier(target_id)
        for target in self.targets():
            if target["id"] == target_id:
                return target
        raise ManagerError("배포 대상을 찾을 수 없습니다.", 404)

    def _bundle(self, job_id, target_id, package_id):
        target = self.target(target_id)
        package = Packages(self.store).get(package_id, job_id)
        with zipfile.ZipFile(io.BytesIO(Packages(self.store)._archive(package_id, job_id))) as archive:
            files = {"source/" + rel: {"data": base64.b64encode(archive.read("source/" + rel)).decode(), **meta}
                     for rel, meta in package["manifest"]["files"].items()}
            for remote, meta in package["manifest"]["runtime_files"].items():
                files[remote] = {"data": base64.b64encode(archive.read(remote)).decode(), **meta}
            info = {"job_id": job_id, "target": target, "config": package["manifest"]["config"],
                    "config_etag": package["manifest"]["files"]["job.yaml"]["sha256"],
                    "package_id": package_id, "package_hash": package["content_hash"],
                    "files": {k: {x: v[x] for x in ("sha256", "mode")} for k, v in sorted(files.items())}}
        plan_hash = digest(json.dumps(info, sort_keys=True, ensure_ascii=False).encode())
        return {"plan_hash": plan_hash, "release": "r-" + plan_hash[:24], **info}, files

    def plan(self, job_id, target_id, package_id):
        with self.store.job_lock(job_id, "lifecycle"):
            return self._plan(job_id, target_id, package_id)

    def _plan(self, job_id, target_id, package_id):
        info, _ = self._bundle(job_id, target_id, package_id)
        info["notice"] = "서버 연결 없음. 의존성·비밀 파일·SSH known_hosts·systemd user linger는 사전 준비가 필요합니다."
        return info

    def _ssh(self, target, payload):
        helper = (base64.b64decode(payload["files"]["manager/remote_runtime.py"]["data"])
                  if payload.get("action") == "deploy" else (Path(__file__).parent / "remote_runtime.py").read_bytes())
        loader = "import base64;exec(compile(base64.b64decode(" + repr(base64.b64encode(helper).decode()) + "),'<script-manager>','exec'))"
        remote_command = "python3 -c " + shlex.quote(loader)
        try:
            result = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o",
                 "ConnectTimeout=10", "--", target["ssh_host"], remote_command],
                input=json.dumps({**payload, "root": target["root"]}), capture_output=True,
                text=True, timeout=180)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ManagerError("SSH 응답을 확인하지 못했습니다. 원격 상태를 검증한 후 재시도하세요: " + str(exc), 502)
        try:
            response = json.loads(result.stdout)
        except ValueError:
            raise ManagerError("SSH 응답 오류. 적용 여부는 불명확합니다: " + result.stderr[:2000], 502)
        if result.returncode or not response.get("ok"):
            raise ManagerError("원격 작업 실패: " + response.get("error", result.stderr[:2000]), 502)
        return response["result"]

    def _receipt(self, job_id, target_id, receipt):
        path = contained(self.store.root, "deployments/history/" + identifier(target_id) + "/" + identifier(job_id))
        path.mkdir(parents=True, exist_ok=True)
        write_json(path / (receipt["id"] + ".json"), receipt)

    def _operation(self, job_id, target_id, action, release=None, expected=None, package_id=None):
        target = self.target(target_id)
        with self.store.job_lock(job_id, "lifecycle"), self.store.job_lock(job_id, "deploy-" + target_id, False):
            payload = {"action": action, "job_id": identifier(job_id)}
            info = None
            if action == "deploy":
                info, files = self._bundle(job_id, target_id, package_id)
                if not expected or expected != info["plan_hash"]:
                    raise ManagerError("Job 또는 배포 대상이 계획 이후 변경되었습니다. 계획을 다시 확인하세요.", 409)
                payload.update(info=info, files=files)
                release = info["release"]
            elif action == "rollback":
                identifier(release)
                payload["release"] = release
            receipt = {"id": uuid.uuid4().hex, "job_id": job_id, "target": target_id,
                       "package_id": package_id if action == "deploy" else None,
                       "action": action, "release": release, "created_at": now(),
                       "status": "pending", "snapshot": info}
            self._receipt(job_id, target_id, receipt)
            try:
                result = self.transport(target, {**payload, "root": target["root"]})
                receipt.update(status="verified", result=result)
            except Exception as exc:
                receipt.update(status="unconfirmed", error=str(exc))
                raise
            finally:
                receipt["finished_at"] = now()
                self._receipt(job_id, target_id, receipt)
            return receipt

    def deploy(self, job_id, target_id, package_id, plan_hash):
        return self._operation(job_id, target_id, "deploy", expected=plan_hash, package_id=package_id)

    def rollback(self, job_id, target_id, release):
        return self._operation(job_id, target_id, "rollback", release=release)

    def verify(self, job_id, target_id):
        return self.transport(self.target(target_id), {"action": "verify", "job_id": identifier(job_id),
                                                     "root": self.target(target_id)["root"]})

    def history(self, job_id):
        identifier(job_id)
        base = contained(self.store.root, "deployments/history")
        if not base.exists():
            return []
        records = []
        for target in base.iterdir():
            if target.is_dir():
                directory = contained(base, target.name + "/" + job_id)
                if directory.is_dir():
                    records.extend(read_json(p) for p in directory.glob("*.json") if not p.is_symlink())
        return sorted(records, key=lambda r: r["created_at"], reverse=True)
