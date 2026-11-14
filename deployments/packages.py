"""Immutable, verified Job archives shared by download and SSH deployment."""
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import uuid
import zipfile

from runner.common import (ManagerError, contained, digest, identifier, now, private_mkdir,
                           private_temporary_directory, read_json, write_json)
from runner.execution import snapshot, source_files


OMIT_DIRS = {"data", "logs", "output", "outputs", "cache", ".cache", "dist", "build", "tmp", "temp", "runtime", "workspace", "state"}
OMIT_NAMES = {".env", "credentials", "credentials.json", "secrets.json", "id_rsa", "id_ed25519"}
OMIT_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".log", ".pid", ".sqlite", ".sqlite3", ".db", ".pyc")
RUNTIME_FILES = (("LICENSE", "manager/LICENSE"),
                 ("runner/__init__.py", "manager/runner/__init__.py"),
                 ("runner/common.py", "manager/runner/common.py"),
                 ("runner/execution.py", "manager/runner/execution.py"),
                 ("runner/parameters.py", "manager/runner/parameters.py"),
                 ("deployments/remote_runtime.py", "manager/remote_runtime.py"))


def excluded(relative, is_dir):
    parts = PurePosixPath(relative.replace(os.sep, "/")).parts
    name = parts[-1].lower()
    if any(part.lower() in OMIT_DIRS for part in parts):
        return True
    if is_dir:
        return name.startswith(".")
    return (name.startswith(".") or name in OMIT_NAMES or name.startswith(".env") or
            any(word in name for word in ("secret", "credential", "token", "password")) or
            name.endswith(OMIT_SUFFIXES))


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


class Packages:
    def __init__(self, store):
        self.store = store
        self.root = contained(store.root, "deployments/packages")
        private_mkdir(self.root, parents=True, exist_ok=True)

    def _directory(self, package_id):
        return contained(self.root, identifier(package_id), True)

    def _metadata(self, directory):
        try:
            meta = read_json(contained(directory, "metadata.json", True))
        except (ValueError, UnicodeError) as exc:
            raise ManagerError("Package 메타데이터를 읽을 수 없습니다.", 409) from exc
        if not isinstance(meta, dict) or not isinstance(meta.get("job_id"), str):
            raise ManagerError("Package 메타데이터가 손상되었습니다.", 409)
        return meta

    def _manifest(self, job_id, config, created_at, package_id, files, runtime_files):
        return {"version": 1, "id": package_id, "job_id": job_id, "created_at": created_at,
                "config": config, "files": files, "runtime_files": runtime_files,
                "requirements": {"created_on": platform.system(),
                                 "standalone_platform": "OS compatible with the command and Job files; not bundled",
                                 "command": config["command"], "cwd": config.get("cwd", "."),
                                 "env_file_required": config.get("env_file"),
                                 "dependency_files": [name for name in ("requirements.txt", "pyproject.toml", "Pipfile", "package.json", "package-lock.json") if name in files],
                                 "ssh_platform": "Linux with Python 3, systemd user services, and SSH"}}

    def _instructions(self, manifest):
        req = manifest["requirements"]
        return ("# Script Manager Package " + manifest["id"] + "\n\n"
                "This ZIP is a fixed snapshot of Job " + manifest["job_id"] + ". Extract it to a private directory.\n"
                "Inspect package.json for file hashes, execution settings, and platform requirements.\n"
                "Preserve manager/LICENSE for bundled Script Manager helper code. Job source may have a separate license.\n"
                "Install the runtime and dependencies required by the Job on the destination host.\n"
                "Dependency declarations in this archive: " + (", ".join(req["dependency_files"]) or "none") + ".\n"
                "From the source/ directory, use cwd " + json.dumps(req["cwd"]) + " and run the command array " + json.dumps(req["command"], ensure_ascii=False) + ".\n"
                "The configured timeout and schedules are in source/job.yaml; install a scheduler separately if needed.\n"
                "Provide credentials and environment values on the destination host."
                + (" The env_file path " + json.dumps(req["env_file_required"]) + " is required but excluded from this ZIP." if req["env_file_required"] else "") + "\n"
                "Download only exports this archive; it does not install dependencies or run the Job.\n")

    def create(self, job_id):
        identifier(job_id)
        with self.store.job_lock(job_id, "lifecycle"), self.store.job_lock(job_id):
            item = self.store.get(job_id)
            if item["config"].get("env"):
                raise ManagerError("Package에 인라인 환경 변수 값을 포함할 수 없습니다. env_file로 옮긴 뒤 다시 생성하세요.")
            package_id = "p-" + uuid.uuid4().hex
            created_at = now()
            with private_temporary_directory(self.store.runtime / "deployments") as temporary:
                source = Path(temporary) / "source"
                source_manifest = snapshot(self.store.job_dir(job_id), source, item["config"].get("env_file"), excluded)
                if source_manifest.get("job.yaml", {}).get("sha256") != item["etag"]:
                    raise ManagerError("Package 생성 중 Job 설정이 변경되었습니다.", 409)
                files = {Path(rel).as_posix(): meta for rel, meta in source_manifest.items()}
                code_root = Path(__file__).resolve().parent.parent
                runtime_data = {remote: (code_root / local).read_bytes() for local, remote in RUNTIME_FILES}
                runtime_files = {name: {"sha256": digest(data), "mode": 0o600} for name, data in runtime_data.items()}
                manifest = self._manifest(job_id, item["config"], created_at, package_id, files, runtime_files)
                manifest["content_hash"] = digest(canonical({"config": manifest["config"], "files": files,
                                                             "runtime_files": runtime_files}))
                archive = Path(temporary) / "package.zip"
                with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
                    for rel, meta in sorted(files.items()):
                        entry = zipfile.ZipInfo("source/" + rel.replace(os.sep, "/"))
                        entry.external_attr = (stat.S_IFREG | meta["mode"]) << 16
                        entry.compress_type = zipfile.ZIP_DEFLATED
                        output.writestr(entry, (source / rel).read_bytes())
                    for name, data in sorted(runtime_data.items()):
                        entry = zipfile.ZipInfo(name)
                        entry.external_attr = (stat.S_IFREG | 0o600) << 16
                        entry.compress_type = zipfile.ZIP_DEFLATED
                        output.writestr(entry, data)
                    for name, data in (("package.json", canonical(manifest) + b"\n"),
                                       ("RUNME.md", self._instructions(manifest).encode())):
                        output.writestr(name, data)
                metadata = {"id": package_id, "job_id": job_id, "created_at": created_at,
                            "content_hash": manifest["content_hash"], "zip_sha256": digest(archive.read_bytes()),
                            "requirements": manifest["requirements"], "file_count": len(files)}
                destination = contained(self.root, package_id)
                private_mkdir(destination)
                try:
                    shutil.copyfile(archive, destination / "package.zip")
                    write_json(destination / "metadata.json", metadata)
                    write_json(destination / "manifest.json", manifest)
                    self.get(package_id, job_id)
                    os.chmod(destination / "package.zip", 0o400)
                    os.chmod(destination / "metadata.json", 0o400)
                except Exception:
                    shutil.rmtree(destination)
                    raise
        from runner.lifecycle import Lifecycle
        Lifecycle(self.store).automatic(job_id, ("packages",))
        return self.metadata(package_id, job_id)

    def metadata(self, package_id, job_id=None):
        directory = self._directory(package_id)
        meta = self._metadata(directory)
        if meta.get("id") != package_id or (job_id and meta.get("job_id") != job_id):
            raise ManagerError("Package 메타데이터가 일치하지 않습니다.", 409)
        archive = contained(directory, "package.zip")
        return {**meta, "zip_available": archive.is_file(),
                "zip_bytes": archive.stat().st_size if archive.is_file() else 0}

    def get(self, package_id, job_id=None):
        directory = self._directory(package_id)
        meta = self._metadata(directory)
        if not isinstance(meta, dict) or meta.get("id") != package_id or (job_id and meta.get("job_id") != job_id):
            raise ManagerError("Package 메타데이터가 일치하지 않습니다.", 409)
        archive = contained(directory, "package.zip")
        if not archive.exists():
            return {**self.metadata(package_id, job_id), "manifest": read_json(contained(directory, "manifest.json"))}
        data = archive.read_bytes()
        if digest(data) != meta.get("zip_sha256"):
            raise ManagerError("Package ZIP 무결성 검증에 실패했습니다.", 409)
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = zf.namelist()
                if len(names) != len(set(names)) or any(PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts or "\\" in name for name in names):
                    raise ValueError("Unsafe ZIP member")
                manifest = json.loads(zf.read("package.json"))
                expected = {"package.json", "RUNME.md"} | {"source/" + rel for rel in manifest["files"]} | set(manifest["runtime_files"])
                if set(names) != expected or manifest.get("id") != package_id or manifest.get("job_id") != meta["job_id"]:
                    raise ValueError("Package manifest mismatch")
                if digest(canonical({"config": manifest["config"], "files": manifest["files"],
                                     "runtime_files": manifest["runtime_files"]})) != meta["content_hash"] or manifest["content_hash"] != meta["content_hash"]:
                    raise ValueError("Package content hash mismatch")
                for rel, expected_meta in manifest["files"].items():
                    if rel.startswith("/") or ".." in PurePosixPath(rel).parts or excluded(rel, False):
                        raise ValueError("Unsafe source member")
                    name = "source/" + rel
                    info = zf.getinfo(name)
                    if stat.S_IFMT(info.external_attr >> 16) != stat.S_IFREG or digest(zf.read(name)) != expected_meta["sha256"]:
                        raise ValueError("Package source checksum mismatch")
                if set(manifest["runtime_files"]) != {remote for _, remote in RUNTIME_FILES}:
                    raise ValueError("Package runtime manifest mismatch")
                for name, expected_meta in manifest["runtime_files"].items():
                    info = zf.getinfo(name)
                    if stat.S_IFMT(info.external_attr >> 16) != stat.S_IFREG or digest(zf.read(name)) != expected_meta["sha256"]:
                        raise ValueError("Package runtime checksum mismatch")
                if manifest["files"]["job.yaml"]["sha256"] != digest(zf.read("source/job.yaml")):
                    raise ValueError("Job configuration mismatch")
        except (KeyError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
            raise ManagerError("Package ZIP 검증에 실패했습니다: " + str(exc), 409) from exc
        return {**self.metadata(package_id, job_id), "manifest": manifest}

    def archive(self, package_id, job_id):
        with self.store.job_lock(job_id, "lifecycle"):
            return self._archive(package_id, job_id)

    def _archive(self, package_id, job_id):
        if not self.metadata(package_id, job_id)["zip_available"]:
            raise ManagerError("정리된 Package ZIP은 다운로드·배포할 수 없습니다.", 409)
        self.get(package_id, job_id)
        return contained(self._directory(package_id), "package.zip", True).read_bytes()

    def list(self, job_id):
        identifier(job_id)
        records = []
        for path in self.root.iterdir():
            if path.is_dir() and re.fullmatch(r"p-[0-9a-f]{32}", path.name):
                path = contained(self.root, path.name, True)
                meta = self._metadata(path)
                if meta.get("job_id") == job_id:
                    records.append(self.get(path.name, job_id))
        return sorted(records, key=lambda item: item["created_at"], reverse=True)

    def difference(self, job_id, package_id):
        package = self.get(package_id, job_id)
        item = self.store.get(job_id)
        if item["config"].get("env"):
            return {"changed": True, "reason": "인라인 환경 변수 설정", "added": [], "removed": [], "modified": []}
        current = {Path(rel).as_posix(): meta for rel, meta in source_files(
            self.store.job_dir(job_id), item["config"].get("env_file"), excluded).items()}
        if not package.get("manifest"):
            raise ManagerError("Package manifest가 없습니다.", 409)
        old = package["manifest"]["files"]
        return {"changed": current != old, "added": sorted(current.keys() - old.keys()),
                "removed": sorted(old.keys() - current.keys()),
                "modified": sorted(name for name in current.keys() & old.keys() if current[name] != old[name])}
