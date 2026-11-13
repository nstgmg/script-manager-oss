"""Loopback-only, single-user Dashboard. No CDN or frontend build is needed."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import platform
from pathlib import Path
import secrets
import subprocess
import traceback
from urllib.parse import parse_qs, unquote, urlsplit

from runner.common import ManagerError
from runner.execution import Execution
from runner.schedule import Scheduler
from runner.store import Store, default_job
from dashboard.overview import overview


class Dashboard(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, root, port=8765):
        self.store = Store(root)
        self.token = secrets.token_urlsafe(32)
        super().__init__(("127.0.0.1", port), Handler)


class Handler(BaseHTTPRequestHandler):
    def open_directory(self, folder, label="프로젝트"):
        command = {"Darwin": "open", "Windows": "explorer", "Linux": "xdg-open"}.get(platform.system())
        if not command:
            raise ManagerError("이 운영체제에서는 파일 탐색기를 열 수 없습니다.", 501)
        try:
            subprocess.run([command, str(folder)], check=True, timeout=15, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError) as exc:
            raise ManagerError(label + " 폴더를 열지 못했습니다: " + str(exc), 500)
        return {"ok": True}, 200

    def log_message(self, *_):
        pass  # Do not log request bodies, secrets, or query strings.

    def send(self, status, value, mime="application/json", filename=None, report=False):
        if mime == "application/json":
            data = json.dumps(value, ensure_ascii=False).encode()
        else:
            data = value if isinstance(value, bytes) else value.encode()
        self.send_response(status)
        self.send_header("Content-Type", mime + ("; charset=utf-8" if mime.startswith("text/") or mime == "application/json" else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if filename:
            self.send_header("Content-Disposition", 'attachment; filename="' + filename + '"')
        if report:
            policy = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'none'; frame-ancestors 'self'; sandbox allow-scripts allow-downloads; object-src 'none'; base-uri 'none'; form-action 'none'"
        else:
            policy = "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'"
        self.send_header("Content-Security-Policy", policy)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.dispatch()

    def do_POST(self):
        self.dispatch()

    def do_PUT(self):
        self.dispatch()

    def do_DELETE(self):
        self.dispatch()

    def dispatch(self):
        try:
            port = self.server.server_address[1]
            host = self.headers.get("Host", "")
            if host not in ("127.0.0.1:" + str(port), "localhost:" + str(port)):
                raise ManagerError("허용되지 않은 Host입니다.", 403)
            if self.command != "GET":
                if self.headers.get("Origin") not in (None, "http://" + host):
                    raise ManagerError("다른 출처의 요청은 허용하지 않습니다.", 403)
                if not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), self.server.token):
                    raise ManagerError("Dashboard 세션 토큰이 필요합니다.", 403)
            url = urlsplit(self.path)
            parts = [unquote(p) for p in url.path.strip("/").split("/") if p]
            if self.command == "GET" and (not parts or parts == ["app.js"] or parts == ["style.css"]):
                filename = "index.html" if not parts else parts[0]
                mime = {"index.html": "text/html", "app.js": "text/javascript", "style.css": "text/css"}[filename]
                return self.send(200, (Path(__file__).parent / "static" / filename).read_bytes(), mime)
            if self.command == "GET" and len(parts) == 6 and parts[:2] == ["api", "jobs"] and parts[3] == "packages" and parts[5] == "download":
                from deployments.packages import Packages
                return self.send(200, Packages(self.server.store).archive(parts[4], parts[2]),
                                 "application/zip", parts[2] + "-" + parts[4] + ".zip")
            if (self.command == "GET" and len(parts) == 5 and parts[:2] == ["api", "jobs"]
                    and parts[3] == "report" and parts[4] in ("html", "download")):
                from runner.reports import Reports
                return self.send(200, Reports(self.server.store).document(parts[2]), "text/html",
                                 parts[2] + ".html" if parts[4] == "download" else None, report=True)
            body = {}
            if self.command in ("POST", "PUT", "DELETE"):
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    raise ManagerError("Content-Length 오류입니다.")
                if not 0 <= length <= 262144:
                    raise ManagerError("요청은 256 KiB 이하여야 합니다.", 413)
                if length:
                    try:
                        raw = self.rfile.read(length)
                        if len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] == "runs":
                            from runner.parameters import parse_cli_parameters
                            body = parse_cli_parameters(raw, "실행 요청")
                        else:
                            body = json.loads(raw)
                    except (ValueError, UnicodeError):
                        raise ManagerError("JSON 요청이 필요합니다.")
                    if not isinstance(body, dict):
                        raise ManagerError("JSON 객체가 필요합니다.")
            result_query = (parts == ["api", "results", "jobs"] or
                            len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] == "results")
            value, status = self.api(parts, body, parse_qs(url.query, keep_blank_values=result_query))
            return self.send(status, value)
        except ManagerError as exc:
            self.send(exc.status, {"error": str(exc)})
        except (OSError, ValueError) as exc:
            self.send(400, {"error": str(exc)})
        except Exception:
            traceback.print_exc()
            self.send(500, {"error": "내부 오류입니다. 로컬 터미널을 확인하세요."})

    def api(self, parts, body, query):
        store = self.server.store
        execution = Execution(store)
        scheduler = Scheduler(store)
        method = self.command
        if parts == ["api", "session"] and method == "GET":
            system = platform.system()
            return {"csrf": self.server.token, "root": str(store.root), "os": system,
                    "scheduler": "launchd" if system == "Darwin" else "Windows Task Scheduler" if system == "Windows" else "unsupported"}, 200
        if parts == ["api", "project-directory", "open"] and method == "POST":
            if body or query:
                raise ManagerError("프로젝트 폴더 열기에는 인자를 지정할 수 없습니다.")
            return self.open_directory(store.root)
        if parts == ["api", "overview"] and method == "GET":
            return overview(store, execution, scheduler, query.get("period", ["today"])[0],
                            query.get("job", [""])[0]), 200
        if parts == ["api", "results", "jobs"] and method == "GET":
            from runner.results import Results
            if set(query) - {"keyword"} or any(len(v) != 1 for v in query.values()):
                raise ManagerError("지원하지 않는 결과 목록 조건입니다.")
            return Results(store).catalog(query.get("keyword", [None])[0]), 200
        if parts == ["api", "jobs"]:
            if method == "GET":
                return store.list(), 200
            if method == "POST":
                config = body.get("config")
                if config is None:
                    config = default_job(body.get("id"), body.get("name"))
                return store.create(config), 201
        if parts == ["api", "schedules"] and method == "GET":
            rows = []
            for item in store.list():
                if item.get("error"):
                    rows.append({"job_id": item["id"], "job_name": item["id"], "error": item["error"]})
                    continue
                try:
                    rows.extend(scheduler.rows(item["id"]))
                except (ManagerError, OSError) as exc:
                    rows.append({"job_id": item["id"], "job_name": item["config"]["name"], "error": str(exc)})
            return rows, 200
        if parts == ["api", "trash"] and method == "GET":
            return store.trash(), 200
        if len(parts) == 4 and parts[:2] == ["api", "trash"] and parts[3] == "restore" and method == "POST":
            return store.restore(parts[2]), 200
        if parts == ["api", "targets"] and method == "GET":
            from deployments.client import Deployment
            return Deployment(store).targets(), 200
        if len(parts) >= 3 and parts[:2] == ["api", "jobs"]:
            job_id = parts[2]
            if parts[3:] == ["report"] and method == "GET":
                from runner.reports import Reports
                return Reports(store).get(job_id), 200
            if parts[3:] == ["report", "destination"] and method == "POST":
                from runner.reports import Reports
                store.get(job_id)
                if query or set(body) - {"output_dir", "filename"}:
                    raise ManagerError("저장 경로 확인에는 output_dir, filename만 지정할 수 있습니다.")
                target = Reports(store).validate_destination(job_id, body)
                return {"path": str(target), "directory": str(target.parent)}, 200
            if parts[3:] == ["report", "open-directory"] and method == "POST":
                from runner.reports import Reports
                if body or query:
                    raise ManagerError("보고서 폴더 열기에는 인자를 지정할 수 없습니다.")
                info = Reports(store).get(job_id)
                if not info.get("available"):
                    raise ManagerError("생성된 보고서가 없습니다.", 404)
                return self.open_directory(Path(info["path"]).parent, "보고서")
            if parts[3:] == ["results"] and method == "GET":
                from runner.results import Results
                allowed = {"keyword", "status", "source", "from", "to", "date_field", "timezone",
                           "stale_hours", "run", "all_runs", "file", "limit", "offset"}
                if set(query) - allowed or any(len(v) != 1 for k, v in query.items() if k != "keyword"):
                    raise ManagerError("지원하지 않거나 중복된 결과 조회 조건입니다.")
                values = {k: v[0] for k, v in query.items() if k != "keyword"}
                if values.get("all_runs", "false") not in ("true", "false"):
                    raise ManagerError("all_runs는 true 또는 false여야 합니다.")
                try:
                    limit = int(values.get("limit", "20"))
                    offset = int(values.get("offset", "0"))
                    stale_hours = float(values.get("stale_hours", "24"))
                except ValueError:
                    raise ManagerError("limit, offset, stale_hours는 숫자여야 합니다.")
                return Results(store).query(job_id, keywords=query.get("keyword", []),
                    status=values.get("status"), source=values.get("source"),
                    date_from=values.get("from"), date_to=values.get("to"),
                    date_field=values.get("date_field", "collected_at"),
                    timezone_name=values.get("timezone", "Asia/Seoul"), stale_hours=stale_hours,
                    run_id=values.get("run"), all_runs=values.get("all_runs") == "true",
                    file=values.get("file"), limit=limit, offset=offset), 200
            if parts[3:4] == ["lifecycle"]:
                from runner.lifecycle import Lifecycle
                lifecycle = Lifecycle(store)
                if parts[3:] == ["lifecycle"]:
                    if method == "GET":
                        return lifecycle.preview(job_id), 200
                    if method == "PUT":
                        return lifecycle.save(job_id, body), 200
                if parts[3:] == ["lifecycle", "cleanup"] and method == "POST":
                    return lifecycle.cleanup(job_id, body.get("resource"), body.get("expected")), 200
                if parts[3:] == ["lifecycle", "restore"] and method == "POST":
                    return lifecycle.restore(job_id, body.get("run_id")), 200
            if parts[3:] == ["packages"]:
                from deployments.packages import Packages
                packages = Packages(store)
                if method == "GET":
                    return packages.list(job_id), 200
                if method == "POST":
                    return packages.create(job_id), 201
            if len(parts) >= 5 and parts[3] == "packages":
                from deployments.packages import Packages
                packages = Packages(store)
                if len(parts) == 5 and method == "GET":
                    return packages.get(parts[4], job_id), 200
                if len(parts) == 6 and parts[5] == "difference" and method == "GET":
                    return packages.difference(job_id, parts[4]), 200
            if len(parts) == 3:
                if method == "GET":
                    return store.get(job_id), 200
                if method == "PUT":
                    if "fields" in body:
                        if "yaml" in body or "schedule" in body:
                            raise ManagerError("fields와 yaml/schedule을 함께 지정할 수 없습니다.")
                        return store.update_fields(job_id, body["fields"], body.get("etag")), 200
                    if "schedule" in body:
                        if "yaml" in body:
                            raise ManagerError("yaml과 schedule을 동시에 지정할 수 없습니다.")
                        return store.update_schedule(job_id, body["schedule"], body.get("etag")), 200
                    if not isinstance(body.get("yaml"), str):
                        raise ManagerError("yaml 문자열이 필요합니다.")
                    return store.update(job_id, body["yaml"], body.get("etag")), 200
                if method == "DELETE":
                    return store.delete(job_id, body.get("etag")), 200
            if parts[3:] == ["runs"]:
                if method == "GET":
                    return execution.list(job_id), 200
                if method == "POST":
                    if set(body) - {"parameters"} or query:
                        raise ManagerError("실행 요청에는 parameters 객체만 허용합니다.")
                    if "parameters" in body:
                        if not isinstance(body["parameters"], dict):
                            raise ManagerError("parameters는 JSON 객체여야 합니다.")
                        return execution.start(job_id, parameters=body["parameters"]), 202
                    return execution.start(job_id), 202
            if len(parts) == 5 and parts[3] == "runs" and method == "GET":
                return execution.get(job_id, parts[4]), 200
            if len(parts) == 6 and parts[3] == "runs":
                if parts[5] == "cancel" and method == "POST":
                    return execution.cancel(job_id, parts[4]), 202
                if parts[5] == "logs" and method == "GET":
                    try:
                        offset = int(query.get("offset", ["0"])[0])
                    except ValueError:
                        raise ManagerError("offset은 정수여야 합니다.")
                    return execution.logs(job_id, parts[4], query.get("stream", ["stdout"])[0], offset), 200
            if parts[3:] == ["schedules"]:
                if method == "GET":
                    return scheduler.rows(job_id), 200
                if method == "POST":
                    schedule = body.get("schedule")
                    if not isinstance(schedule, dict):
                        raise ManagerError("schedule 객체가 필요합니다.")
                    return scheduler.save(job_id, schedule.get("id"), schedule, body.get("etag"), create=True), 201
            if len(parts) == 5 and parts[3] == "schedules":
                if method in ("PUT", "DELETE"):
                    if method == "PUT" and not isinstance(body.get("schedule"), dict):
                        raise ManagerError("schedule 객체가 필요합니다.")
                    return scheduler.save(job_id, parts[4], body.get("schedule") if method == "PUT" else None,
                                          body.get("etag"), legacy_registration=method == "DELETE" and body.get("legacy_registration") is True), 200
            if parts[3:] == ["schedule"]:
                if method == "GET":
                    plan = scheduler.plan(job_id)
                    return {"plan": plan, "state": scheduler.observed(job_id, plan["schedule_id"])}, 200
                if method == "POST":
                    return scheduler.apply(job_id, body.get("etag")), 200
                if method == "DELETE":
                    return scheduler.remove(job_id), 200
            if len(parts) == 4 and parts[3] in ("deploy-plan", "deploy", "rollback", "verify", "deployments"):
                from deployments.client import Deployment
                deployer = Deployment(store)
                action = parts[3]
                if action == "deployments" and method == "GET":
                    return deployer.history(job_id), 200
                if method == "POST":
                    target = body.get("target")
                    if action == "deploy-plan":
                        return deployer.plan(job_id, target, body.get("package_id")), 200
                    if action == "deploy":
                        return deployer.deploy(job_id, target, body.get("package_id"), body.get("plan_hash")), 200
                    if action == "rollback":
                        return deployer.rollback(job_id, target, body.get("release")), 200
                    if action == "verify":
                        return deployer.verify(job_id, target), 200
        raise ManagerError("요청한 경로가 없습니다.", 404)
