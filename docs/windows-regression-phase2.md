# Windows 회귀 안정화 — 2차

기준은 `423a9b93b0c6853624ffa7c8a3eeefe3a024259e`의 Windows 전체 로그와 사용자 보고서다.
Windows 10 / CPython 3.12.14 / 부모·자식 UTF-8 실행에서 **338개 부모 테스트 중 FAIL 9, ERROR 2, SKIP 50**이었으며,
원문 `failures=12`는 payload subtest와 취소 cleanup 중복 실패를 포함한 이벤트 수다.
이번 작업은 그 기준 커밋이 있는 OSS 저장소에서 수행했다. 기존 설치본의 Job·예약·데이터는 조작하지 않았다.

## 우선순위 1: 실행 상태와 대기 제한

| 관측 | 확인한 사실과 분류 | 이번 처리 / 남은 진단 |
| --- | --- | --- |
| 취소 후 본문·cleanup 각각 12초 안에 terminal 미도달 | **미확정 실행 경로**. 기존 로그에는 마지막 Run 상태, worker exit, lease, Job Object 할당 여부가 없다. Windows monitor는 Job Object 할당 실패 시 `taskkill` 최대 20초를 사용할 수 있어, 이 분기와 테스트 관찰 제한도 분리해야 한다 | 12초를 늘리지 않았다. 기존 조기 취소와 별도로 자식의 ready 파일을 확인한 뒤 취소하는 테스트를 추가. 실제 worker stderr, 반환 코드, 마지막 상태·heartbeat·PID·lease·cancel 파일을 수집하고 선택적 stack trace를 준비했다 |
| Parameter Run은 stdout에 values/argv를 쓴 뒤 `interrupted`, exit 없음 | **미확정 실행 경로**. `created=17:17:57.548168Z`, `finished=17:18:27.643772Z`의 차이는 **30.095604초**로 Windows lease의 30초 startup grace와 맞는다. 관찰자가 Run lock을 얻었고 terminal 결과를 읽지 못했다는 뜻이며, 정상 script 출력만으로 worker 성공을 증명할 수 없다 | 실제 worker 종료와 PID 생존 조회 오판, monitor 종료 지연, 최종 JSON 저장 실패를 구분한다. 제품 monitor·lease·잠금·상태 저장에 추정 수정을 하지 않았다. API/CLI 동등성 테스트는 MagicMock PID 대신 실제 worker 두 개를 순서대로 성공 검증한다 |
| Dashboard 결과에 `wait_timed_out` 없음 | **재현한 제품 결함 경로 + fixture 타이밍 의존**. 남은 wait budget을 status GET timeout으로 전달한 뒤 GET이 만료되면 기존 코드는 일반 `observation_error`만 반환한다. Windows 원문은 반환 객체 없이 KeyError만 기록했으므로 그 실행이 정확히 이 경로였다고 확정할 수는 없다 | HTTP timeout을 별도 분류하고, 알려진 Run의 active 상태 관찰 중 **전체 대기 제한까지 소진한 경우** `wait_timed_out`과 같은 Run의 resume을 반환. 마지막 관찰 상태이며 terminal을 추정하지 않는다. 50ms 제한은 유지하고, 0.5초 sleep 대신 release 파일로 Job을 유지해 duplicate 검증 이후 해제한다 |

취소와 Parameter Run은 같은 detached worker·Windows monitor·최종 상태 저장을 거치므로 공통 원인 **가능성**은 있다.
다만 `interrupted`는 worker 사망/PID 판정과 final record 부재, 취소 대기는 살아 있는 worker의 지연일 수도 있다.
Dashboard는 클라이언트의 짧은 HTTP deadline만으로도 독립적으로 실패할 수 있다. 세 관측을 같은 결함으로 합치지 않는다.
빈 stderr는 기존 script stderr이며, `DEVNULL`로 버린 **worker stderr가 비었다는 증거가 아니다**.

Dashboard 회귀는 논리 시계를 사용해 제한 시점의 status timeout, 제한 전 timeout, HTTP 500, 일반 관찰 오류를 구분한다.
동일 테스트를 메모리에서 기준 커밋의 `run()`에 적용하면 제한 시점 timeout만 예상대로 실패한다.
POST 응답 timeout은 계속 `submission_uncertain`이고 한 번만 제출한다. HTTP 500/일반 오류도 관찰 오류를 유지한다.
같은 Run의 resume, 중복 409, Run 개수, success의 terminal/exit 0 조건을 함께 검증한다.
Python 3.9의 `socket.timeout`과 이후 버전의 `TimeoutError`, `URLError.reason` 포장 모두 분류한다.

## 우선순위 2: 삭제와 경로 안전성

- **missing ZIP fixture**: Package는 ZIP을 `0400`으로 만든다. Windows에서는 readonly 삭제가 거부될 수 있다.
  테스트 소유 archive **하나만** `0600`으로 만든 뒤 제거해 missing-ZIP preflight에 도달시킨다.
  배포 계획·배포 모두 거부, SSH 호출 없음, 배포 이력 없음, 원본 metadata 바이트 보존을 검증한다.
  Windows에서 writable 전환 뒤에도 삭제가 실패하면 열린 handle/ACL 문제는 별도 미해결이며 예외를 숨기지 않는다.
- **제품 ZIP cleanup**: 기존 제품은 Windows에서 writable 전환 후 unlink한다. 이 정책은 변경하지 않았다.
  모의 Windows 분기에서 chmod 거부와 unlink 권한/공유 거부를 각각 주입해 `completed=[]`, 대상 오류,
  ZIP·metadata 바이트와 pin된 Package 보존을 검증한다. 이후 같은 후보의 정상 정리와 metadata 보존도 검증한다.
  모의 실패는 실제 Windows ACL 또는 열린 handle 검증을 대신하지 않는다.
- **부분 삭제 fixture**: POSIX의 `os.unlink('main.py', dir_fd=...)`와 Windows의 `Path.unlink(전체 경로)`를
  같은 basename으로 식별한다. Python 3.9의 cached pathlib accessor와 이후 버전 양쪽을 가로챈다.
  주입 도달, 부분 삭제 목록, 실패 보고, 남은 main.py, 새 preview 후 재개를 검증한다.
  별도 테스트는 Mac에서도 실제 maintenance의 경로 기반 삭제 분기를 실행한다.
  제품의 승인 hash·inventory·ancestor·reparse 검사와 삭제 동작은 유지한다.
- **결과 file filter 제품 계약**: Windows에서 `/tmp/file`과 `C:file`은 `is_absolute()`가 False일 수 있다.
  `PurePosixPath`와 `PureWindowsPath`의 anchor 및 `..` 검사를 함께 사용해 drive 절대/상대,
  drive 없는 rooted 경로, UNC·device 경로, 양쪽 구분자의 traversal과 NUL을 호스트와 무관하게 거부한다.
  HTTP 400, 결과 loader 호출 없음, 정상 basename/저장 상대 경로 동작, artifact 집합 밖 파일 미열기를 검증한다.
  기존에도 입력은 artifact 후보의 **필터**일 뿐 읽기 경로가 아니었고 실제 읽기는 `contained`를 통한다.
  이번 관측은 입력 검증 결함이며 외부 파일 읽기 취약점이 입증된 것은 아니다. 공용 `contained`는 변경하지 않았다.

## 나머지 fixture

| 항목 | 변경과 검증 경계 |
| --- | --- |
| workspace 문자열 | `/workspace` substring 대신 로그의 전체 경로를 `Path`로 비교. succeeded, exit 0, Output trash 이동, State 보존 검증 유지 |
| 독립 ZIP 실행 | 현재 테스트의 `sys.executable`로 추출된 `source/main.py`를 실행. `python3` alias 존재와 분리. Script Manager를 실행하지 않는 독립 소스 검증 유지 |
| report LF/CRLF | UTF-8 바이트로 LF와 CRLF fixture를 각각 기록하고 HTML payload가 그 **기록 원문 전체**와 같음을 검증. 악성 payload escaping·CSP·원문 다운로드 계약 유지 |
| Parameter API mock | 직렬화 불가능한 mock PID를 보정하는 대신 실제 acceptance→동일 Run 관찰→CLI Run을 사용. parameters·resolved_command·contract version·terminal·Run 개수 검증 |
| native ACL | Windows PowerShell의 `$PSHOME` 아래 Security module manifest를 명시적으로 import해 자동 module 탐색 의존성을 제거하고 실패 시 module/PSVersion을 출력. import 실패는 여전히 FAIL이며 ACL assertion·보안 설정은 유지. 원래 module load 실패 원인과 이 fixture의 native 실행 결과는 **미검증** |

연결 단절 테스트의 `ConnectionAbortedError`는 원문에서 PASS 테스트의 서버 thread 관측이었다.
기존 서버의 응답/보안 정책을 추정 수정하거나 이를 추가 unittest ERROR로 세지 않았다.

## Windows에서 필요한 진단

일반 전체 실행부터 수행하고, 기존 Job이나 이전 Run을 재제출하지 않는다. 아래 테스트들은 새로운 임시 합성 루트를 사용한다.
실제 Task Scheduler/launchd opt-in은 끈다. 기존 venv·의존성·ACL·Developer Mode·상주 Dashboard를 변경하지 않는다.

```powershell
$env:PYTHONUTF8 = '1'
Remove-Item Env:SCRIPT_MANAGER_TEST_WINDOWS -ErrorAction SilentlyContinue
Remove-Item Env:SCRIPT_MANAGER_TEST_LAUNCHD -ErrorAction SilentlyContinue
Remove-Item Env:SCRIPT_MANAGER_TEST_TRACE_WORKERS -ErrorAction SilentlyContinue
$phase2Evidence = Join-Path (Get-Location) ('.cache/windows-phase2-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $phase2Evidence -ErrorAction Stop | Out-Null
$env:SCRIPT_MANAGER_TEST_DIAGNOSTICS_DIR = Join-Path $phase2Evidence 'workers'
& '.\.venv\Scripts\python.exe' -X utf8 -m unittest discover -v *> (Join-Path $phase2Evidence 'full.log')
$phase2Exit = $LASTEXITCODE
Write-Output ('full exit=' + $phase2Exit)
```

`tests/execution_helpers.py`는 execution/DashboardRun/ParameterHTTP fixture의 **실제 worker argv를 유지**하면서
기존에 버리던 worker stderr만 test-owned `worker-stderr.log`로 받는다.
실패 assertion과 cleanup 증거에 worker returncode, PID·heartbeat·lease, Windows PID 조회, cancel 존재를 남긴다.
지정 디렉터리에 선택한 상태 필드와 합성 stdout/stderr만 보존한다. env·source·임의 Output은 복사하지 않는다.
trace가 꺼진 최초 전체 결과를 먼저 남겨 진단에 따른 타이밍 변화를 구분한다.

취소/Parameter worker 실패가 남으면 같은 코드·venv에서 별도의 **진단 테스트 실행**을 한다.
이것은 기존 운영 Run을 다시 제출하는 명령이 아니며, 최초 전체 결과를 대체하지 않는다.

```powershell
$env:SCRIPT_MANAGER_TEST_TRACE_WORKERS = '1'
$env:SCRIPT_MANAGER_TEST_DIAGNOSTICS_DIR = Join-Path $phase2Evidence 'traced-workers'
& '.\.venv\Scripts\python.exe' -X utf8 -m unittest -v tests.test_execution tests.test_parameters_http tests.test_dashboard_run *> (Join-Path $phase2Evidence 'traced.log')
$phase2TraceExit = $LASTEXITCODE
Write-Output ('trace exit=' + $phase2TraceExit)
Remove-Item Env:SCRIPT_MANAGER_TEST_TRACE_WORKERS -ErrorAction SilentlyContinue
Remove-Item Env:SCRIPT_MANAGER_TEST_DIAGNOSTICS_DIR -ErrorAction SilentlyContinue
```

trace 모드만 worker를 같은 interpreter의 Python trampoline으로 시작한다.
8초마다 stack, Job Object assigned/terminate 관측, JSON 저장 예외 traceback을 기록하며 lock·lease·timeout·결과는 바꾸지 않는다.
타이밍에 영향을 줄 수 있으므로 일반 실행과 구분한다. Mac에서 trace 경로도 검증했다.

1. `worker_returncode`가 실제 종료를 보이는지, `lease_pid_alive`와 일치하는지 비교한다.
   PID 조회가 다르면 정상 권한에서 **같은 fixture PID**의 OS 조회 결과·접근 오류를 보존한다.
   sandbox의 CIM/프로세스 조회 실패는 프로세스 부재로 해석하지 않는다.
2. worker stderr에 JSON write `PermissionError`가 있는지 확인한다. heartbeat/terminal 저장과 동시 read·공유 제약은
   가능한 가설일 뿐이다. 증거 없이 atomic replace 재시도·lease 유예 축소를 추가하지 않는다.
3. 살아 있는 취소 worker라면 stack이 Job Object 호출, `taskkill`, `proc.wait`, pipe reader join, maintenance gate 중
   어디에 있는지 확인한다. Job Object 할당 실패와 fallback 소요를 구분한다. 기존/무관 프로세스를 종료하지 않는다.
4. Dashboard 실패는 assertion의 **전체 반환 객체**와 기존 Run ID, timings/events를 함께 보존한다.
   terminal 실패였다면 timeout 수정으로 해결됐다고 보지 않는다. 관찰 오류 뒤에는 같은 ID만 관찰한다.
5. ZIP 삭제가 계속 거부되면 **임시 Package**의 readonly 속성을 writable 전환 전후 비교하고,
   Windows ACL readback·동일 파일 handle 보유 여부를 확인한다. 실제 Package 권한을 완화하거나 삭제하지 않는다.
6. ACL 테스트 실패 시 출력된 `$PSHOME` manifest 존재·Import-Module 오류·PSVersion과 Get-Acl 오류를 분리한다.
   import 성공 후 SDDL·inheritance·재열기 보존 assertion까지 도달해야 ACL 검증 성공이다. 실패를 SKIP하지 않는다.

## 로컬 검증

macOS 15.6.1 ARM64, 기존 venv CPython 3.9.6, Node v20.11.1. 의존성 변경 없음.
최초 제한 환경 focused 실행은 loopback bind와 OS 조회 권한으로 오류가 났다.
이를 제품/fixture 결함으로 처리하거나 SKIP하지 않고 승인된 로컬 접근으로 검증했다.

- 수정 중심 129개: PASS, 8.779초.
- trace 모드 execution/ParameterHTTP/DashboardRun 26개: PASS, 5.563초. 이후 socket 타입 호환성과 부분 삭제 분기 검증을 보강했다.
- 전체 346개: FAIL/ERROR 0, SKIP 7, 45.682초. 이후 Python 3.9 socket timeout 분류와 Windows 경로 기반 부분 삭제 회귀를 추가했다.
- **최종 전체 347개: PASS 340, FAIL/ERROR 0, SKIP 7, 45.222초, exit 0.** 위 실행들을 합산하지 않는다.
  SKIP은 native PowerShell parser 1, native ACL 1, 명시적 opt-in 없는 실제 예약 5개다.
  새 SKIP 조건은 추가하지 않았다. Mac에서 실행 가능한 browser·POSIX 원격 fixture도 전체 실행에 포함됐다.
- Node UI: 71개 PASS, SKIP 0.
- `git diff --check`: 정상.

실제 Windows 재실행·ACL·Job Object·파일 공유·symlink privilege 조건은 이 Mac 실행으로 확인하지 못했다.
Windows 일반 전체 회귀와 남은 worker 진단이 끝나기 전에는 Windows 전체 안정화 완료로 판정하지 않는다.
테스트에 새 무조건 SKIP을 추가하거나 대기 시간을 늘리지 않았고 실제 예약·SSH·상주 서비스 작업은 수행하지 않았다.
