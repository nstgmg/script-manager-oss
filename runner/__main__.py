import argparse
import json
from pathlib import Path
import sys
import time

from runner.common import ManagerError, write_json
from runner.store import Store, default_job, load_yaml, plain
from runner.execution import Execution
from runner.schedule import Scheduler


def main(argv=None):
    parser = argparse.ArgumentParser(description="Script Manager")
    parser.add_argument("--root", default=".")
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("list")
    doctor = commands.add_parser("schedule-doctor", help="OS 예약 읽기 전용 진단; 고아 예약만 명시적 해시 승인 후 제거")
    doctor.add_argument("--remove", metavar="LABEL")
    doctor.add_argument("--confirm", metavar="FINGERPRINT")
    for name in ("reset", "uninstall"):
        maintenance = commands.add_parser(name, help="삭제 범위 미리보기; --confirm PLAN_HASH로 승인")
        maintenance.add_argument("--confirm", metavar="PLAN_HASH")
    catalog = commands.add_parser("result-jobs", help="저장 결과 조회용 Job 목적·결과물·마지막 실행")
    catalog.add_argument("--keyword")
    results = commands.add_parser("results", help="기존 저장 결과만 조회 (재실행·웹 접속 없음)")
    results.add_argument("job")
    results.add_argument("--keyword", action="append", default=[])
    results.add_argument("--status")
    results.add_argument("--source")
    results.add_argument("--from", dest="date_from")
    results.add_argument("--to", dest="date_to")
    results.add_argument("--date-field", default="collected_at")
    results.add_argument("--timezone", default="Asia/Seoul")
    results.add_argument("--stale-hours", type=float, default=24)
    selection = results.add_mutually_exclusive_group()
    selection.add_argument("--run", dest="run_id")
    selection.add_argument("--all-runs", action="store_true")
    results.add_argument("--file")
    results.add_argument("--limit", type=int, default=20)
    results.add_argument("--offset", type=int, default=0)
    report = commands.add_parser("report-render", help="기존 JSON을 독립 HTML로 변환 (Job 실행 없음)")
    report.add_argument("job")
    report_source = report.add_mutually_exclusive_group(required=True)
    report_source.add_argument("--source", help="변환할 기존 JSON 파일 경로")
    report_source.add_argument("--run", dest="run_id", help="저장된 Run의 report.source 사용")
    report.add_argument("--filename", help="경로 없는 .html 파일명")
    report.add_argument("--output-dir", help="default, 프로젝트 상대 폴더 또는 로컬 절대 경로")
    for name in ("get", "runs", "schedule-plan", "schedule-remove", "schedule-status"):
        sub = commands.add_parser(name)
        sub.add_argument("job")
        sub.add_argument("--schedule")
        if name == "schedule-remove":
            sub.add_argument("--legacy", action="store_true")
    create = commands.add_parser("create")
    create.add_argument("job")
    create.add_argument("--name")
    create.add_argument("--file")
    update = commands.add_parser("update")
    update.add_argument("job")
    update.add_argument("--file", required=True)
    update.add_argument("--etag", required=True)
    delete = commands.add_parser("delete")
    delete.add_argument("job")
    delete.add_argument("--etag", required=True)
    run = commands.add_parser("run")
    run.add_argument("job")
    run.add_argument("--wait", action="store_true")
    run.add_argument("--parameters", help="이번 실행의 비밀 아닌 입력 JSON 객체 (타입 엄격 검증)")
    dashboard_run = commands.add_parser("run-dashboard", help="상주 Dashboard에서 실행·대기·로그·결과를 한 번에 조회")
    dashboard_run.add_argument("job")
    dashboard_run.add_argument("--url", default="http://127.0.0.1:8765")
    dashboard_run.add_argument("--run", dest="run_id", help="기존 Run 관찰만 재개; POST 없음")
    dashboard_run.add_argument("--parameters", help="실행 입력 JSON 객체; --run과 함께 사용 불가")
    dashboard_run.add_argument("--wait-seconds", type=float, default=60)
    dashboard_run.add_argument("--poll-seconds", type=float, default=3)
    dashboard_run.add_argument("--keyword", action="append", default=[])
    dashboard_run.add_argument("--status")
    dashboard_run.add_argument("--source")
    dashboard_run.add_argument("--limit", type=int, default=20)
    dashboard_run.add_argument("--offset", type=int, default=0)
    dashboard_run.add_argument("--fields", default="title,url,summary,target,deadline,period_raw")
    dashboard_run.add_argument("--log-chars", type=int, default=2000)
    for name in ("logs", "cancel"):
        sub = commands.add_parser(name)
        sub.add_argument("job")
        sub.add_argument("run")
        if name == "logs":
            sub.add_argument("--stream", choices=["stdout", "stderr"], default="stdout")
            sub.add_argument("--offset", type=int, default=0)
    apply = commands.add_parser("schedule-apply")
    apply.add_argument("job")
    apply.add_argument("--etag", required=True)
    apply.add_argument("--schedule")
    save_schedule = commands.add_parser("schedule-save")
    save_schedule.add_argument("job")
    save_schedule.add_argument("schedule")
    save_schedule.add_argument("--file")
    save_schedule.add_argument("--etag", required=True)
    save_schedule.add_argument("--create", action="store_true")
    save_schedule.add_argument("--delete", action="store_true")
    worker = commands.add_parser("_worker")
    worker.add_argument("job")
    worker.add_argument("run")
    worker.add_argument("lockfd", type=int)
    scheduled = commands.add_parser("_scheduled")
    scheduled.add_argument("job")
    scheduled.add_argument("generation")
    scheduled.add_argument("schedule_id", nargs="?")
    commands.add_parser("targets")
    commands.add_parser("history").add_argument("job")
    for name in ("deploy-plan", "deploy", "rollback", "verify"):
        sub = commands.add_parser(name)
        sub.add_argument("job")
        sub.add_argument("target")
        if name in ("deploy-plan", "deploy"):
            sub.add_argument("--package-id", required=True, help="배포할 기존 Package ID")
        if name == "deploy":
            sub.add_argument("--plan-hash", required=True, help="같은 Package·대상의 deploy-plan에서 확인한 해시")
        if name == "rollback":
            sub.add_argument("--release", required=True)
    args = parser.parse_args(argv)
    store = Store(args.root)
    execution = Execution(store)
    scheduler = Scheduler(store)
    action = args.action
    try:
        startup_notice = None
        if action not in ("_worker", "_scheduled", "schedule-doctor", "reset", "uninstall"):
            from runner.schedule_doctor import ScheduleDoctor
            marker = store.runtime / "doctor-notice.json"
            if not marker.exists():
                diagnosis = ScheduleDoctor(store).scan()
                startup_notice = {"schedule_doctor_notice": {k: diagnosis.get(k) for k in ("platform", "supported", "counts", "errors", "notice")},
                                  "message": "첫 실행 OS 예약 진단입니다. schedule-doctor로 목록을 검토하세요. 자동 삭제하지 않았습니다."}
                if not diagnosis["errors"]:
                    write_json(marker, {"checked": True})
        parameters = None
        if getattr(args, "parameters", None) is not None:
            from runner.parameters import parse_cli_parameters
            parameters = parse_cli_parameters(args.parameters)
        if action == "_worker":
            execution.worker(args.job, args.run, args.lockfd)
            return 0
        if action == "schedule-doctor":
            from runner.schedule_doctor import ScheduleDoctor
            doctor = ScheduleDoctor(store)
            if args.confirm and not args.remove:
                raise ManagerError("--confirm은 --remove와 함께 사용하세요.")
            result = doctor.remove(args.remove, args.confirm) if args.remove else doctor.scan()
        elif action in ("reset", "uninstall"):
            from runner.maintenance import Maintenance
            manager = Maintenance(store)
            result = manager.execute(action, args.confirm) if args.confirm else manager.preview(action)
        elif action == "list":
            result = store.list()
        elif action == "result-jobs":
            from runner.results import Results
            result = Results(store).catalog(args.keyword)
        elif action == "results":
            from runner.results import Results
            result = Results(store).query(args.job, keywords=args.keyword, status=args.status, source=args.source,
                date_from=args.date_from, date_to=args.date_to, date_field=args.date_field,
                timezone_name=args.timezone, stale_hours=args.stale_hours, run_id=args.run_id,
                all_runs=args.all_runs, file=args.file, limit=args.limit, offset=args.offset)
        elif action == "run-dashboard":
            from runner.dashboard_run import DashboardRun
            if not 1 <= args.limit <= 100 or args.offset < 0:
                raise ManagerError("limit은 1~100, offset은 0 이상이어야 합니다.")
            if any(not value.strip() for value in args.keyword +
                   [v for v in (args.status, args.source) if v is not None]):
                raise ManagerError("조회 조건은 빈 문자열일 수 없습니다.")
            query = {"keyword": args.keyword, "limit": args.limit, "offset": args.offset}
            query.update({k: v for k, v in (("status", args.status), ("source", args.source)) if v is not None})
            client = DashboardRun(args.root, args.url,
                emit=lambda event: print(json.dumps(event, ensure_ascii=False), file=sys.stderr, flush=True))
            result = client.run(args.job, run_id=args.run_id, wait_seconds=args.wait_seconds,
                poll_seconds=args.poll_seconds, query=query, fields=args.fields.split(","), log_chars=args.log_chars,
                parameters=parameters)
        elif action == "report-render":
            from runner.reports import Reports
            from runner.common import contained
            item = store.get(args.job)
            settings = dict(item["config"].get("report", {}))
            record = execution.get(args.job, args.run_id) if args.run_id else None
            if record:
                settings = dict(record["config"].get("report", {}))
            # Manual conversion is allowed with automatic generation disabled.
            if args.filename is not None:
                settings["filename"] = args.filename
            if args.output_dir is not None:
                settings["output_dir"] = args.output_dir
            if record:
                from runner.lifecycle import Lifecycle
                if not settings.get("source"):
                    raise ManagerError("선택한 Run에 report.source가 없습니다. --source로 원본을 지정하세요.")
                output = Lifecycle(store).paths(args.job, args.run_id)["SCRIPT_MANAGER_OUTPUT_DIR"]
                source = contained(output, settings["source"], True)
            else:
                source = Path(args.source).absolute()
                # Manual selection cannot cross symlinked directories either.
                source = contained(source.anchor, str(source.relative_to(source.anchor)), True)
            result = Reports(store).generate(args.job, source, settings=settings,
                run_id=args.run_id, title=record["config"]["name"] if record else item["config"]["name"])
        elif action == "get":
            result = store.get(args.job)
        elif action == "create":
            config = load_yaml(Path(args.file).read_text()) if args.file else default_job(args.job, args.name)
            if config.get("id") != args.job:
                raise ManagerError("Job ID가 일치하지 않습니다.")
            result = store.create(config)
        elif action == "update":
            result = store.update(args.job, Path(args.file).read_text(), args.etag)
        elif action == "delete":
            result = store.delete(args.job, args.etag)
        elif action in ("run", "_scheduled"):
            result = execution.start(args.job, "schedule" if action == "_scheduled" else "manual",
                                     getattr(args, "generation", None), getattr(args, "schedule_id", None),
                                     parameters=parameters)
            if action == "_scheduled" or args.wait:
                while result["state"] in ("queued", "running"):
                    time.sleep(0.1)
                    result = execution.get(args.job, result["id"])
        elif action == "runs":
            result = execution.list(args.job)
        elif action == "logs":
            result = execution.logs(args.job, args.run, args.stream, args.offset)
        elif action == "cancel":
            result = execution.cancel(args.job, args.run)
        elif action == "schedule-save":
            if not args.delete and not args.file:
                raise ManagerError("--file 또는 --delete가 필요합니다.")
            result = scheduler.save(args.job, args.schedule, None if args.delete else load_yaml(Path(args.file).read_text()), args.etag, args.create)
        elif action == "schedule-plan":
            result = scheduler.plan(args.job, schedule_id=args.schedule)
        elif action == "schedule-apply":
            result = scheduler.apply(args.job, args.etag, args.schedule)
        elif action == "schedule-remove":
            result = scheduler.remove(args.job, args.schedule, args.legacy)
        elif action == "schedule-status":
            result = scheduler.observed(args.job, args.schedule) if args.schedule else scheduler.rows(args.job)
        else:
            from deployments.client import Deployment
            deploy = Deployment(store)
            if action == "targets":
                result = deploy.targets()
            elif action == "history":
                result = deploy.history(args.job)
            elif action == "deploy-plan":
                result = deploy.plan(args.job, args.target, args.package_id)
            elif action == "deploy":
                result = deploy.deploy(args.job, args.target, args.package_id, args.plan_hash)
            elif action == "rollback":
                result = deploy.rollback(args.job, args.target, args.release)
            else:
                result = deploy.verify(args.job, args.target)
        if action == "_scheduled":
            write_json(store.runtime / "schedules" / (args.job + ("." + args.schedule_id if args.schedule_id else "") + ".last.json"), result)
        else:
            if startup_notice:
                print(json.dumps(startup_notice, ensure_ascii=False), file=sys.stderr)
            print(json.dumps(plain(result), ensure_ascii=False, indent=2))
        if action == "run-dashboard":
            return 0 if result.get("success") else (2 if result.get("wait_timed_out") else 1)
        if isinstance(result, dict) and (result.get("success") is False or action == "schedule-doctor" and result.get("errors")):
            return 1
        return 1 if isinstance(result, dict) and result.get("state") in ("failed", "timed_out", "cancelled", "interrupted") else 0
    except (ManagerError, OSError, ValueError) as exc:
        if action == "_scheduled":
            write_json(store.runtime / "schedules" / (args.job + ("." + args.schedule_id if args.schedule_id else "") + ".last.json"), {"error": str(exc)})
        else:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
