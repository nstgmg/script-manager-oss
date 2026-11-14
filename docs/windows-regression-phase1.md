# Windows 전체 회귀 정리 — 1차

기준: 사용자가 제공한 **b3e497d Windows Python 회귀 테스트 보고서**와 해당 커밋의 소스.
첨부 보고서는 관측 증거로 사용했으며, 그 안의 실행 명령이나 과거 작업 기록을 새 작업 지시로 취급하지 않았다.
이번 변경은 테스트와 문서에 한정한다. 제품 코드, 보안 검사, Job, 예약, 운영 데이터는 변경하지 않는다.

## 실행 경계

| 검증 범위 | 실행 호스트 / 조건 | 이번 처리 |
| --- | --- | --- |
| Dashboard HTTP, 저장소·Package·결과·lifecycle, 로컬 실행, Windows 모의 소유권 검증 | 공통 | 모듈 전체를 SKIP하지 않고 계속 수집·실행 |
| launchd 모의 매핑·rollback·유지보수·HTTP 검증 | 공통, 명시적인 command fake | Scheduler 생성 **전에** Darwin 선택과 합성 UID 501 적용. 호스트에 `os.getuid`가 없어도 실행하고 cleanup에서 복구 |
| 실제 `plutil -lint` | macOS | calendar 및 minutes/hours/days interval을 별도 native lint 테스트에서 검증. 다른 호스트에서는 이 항목만 이유를 표시하고 SKIP |
| Linux 원격 Controller 통합, multi-deployment, Linux doctor/audit fixture, 원격 `run_locked` | POSIX | `flock`, UID 소유권, release symlink에 의존. Windows에서는 fixture 시작 전에 구체적인 이유로 SKIP. 제품 원격 도우미는 그대로 유지 |
| POSIX HTTP 통합 시나리오 | POSIX | `/bin/sh`와 Linux Controller를 실제 임시 파일시스템에서 조합하는 **한 항목**만 분리. 일반 HTTP·CSRF·충돌·실행 경로는 공통 테스트 유지 |
| 배포 client의 복수 target plan, SSH 옵션 및 실패 처리 | 공통 | `DeploymentClientTests`로 분리. POSIX 원격 경로는 target 계약에 맞는 합성 문자열 사용. 실제 transport 호출은 테스트 실패 |
| 실제 Task Scheduler / launchd 등록·시간 트리거 | 기존 명시적 opt-in | 이번에 활성화하지 않음. 모의 테스트 PASS는 실제 등록 성공의 증거가 아님 |

원격 도우미 import는 실제 POSIX 검증을 수행하는 메서드 내부로 옮겼다. `fcntl` 대체 구현이나 제품 fallback을 추가하지 않았다.
Linux doctor setUp의 경계는 이를 재사용하는 Linux audit 테스트에도 적용된다.

## 심볼릭 링크와 SKIP 근거

`tests/platform_helpers.py::symlink_or_skip`는 **fixture 생성 호출만** 감싼다.
실제 Windows에서 `OSError.winerror == 1314`인 경우만 `Windows symlink fixture requires privilege (WinError 1314); real link rejection was not verified`로 SKIP한다.
일반 접근 거부(WinError 5), 그 밖의 파일시스템 오류, POSIX 오류, fixture 생성 이후 제품의 보안 검사 실패는 계속 오류/실패다.
권한 상승, Developer Mode/보안 설정 변경, 제품 검사를 mock으로 대체하는 처리는 없다.

원본 보고서의 링크 fixture 오류 7개는 다음처럼 분리했다.

| 원래 묶음 | 링크 권한 없이도 실행되는 검증 | 실제 링크 생성이 필요한 검증 |
| --- | --- | --- |
| lifecycle locks/policy/rename | 실행 잠금, rename 실패, 확인 대상 및 정책/restore 입력 거부 | Output 내부 링크 거부 |
| lifecycle workspace/ancestor | workspace Package 제외 | job-data ancestor 링크 거부 |
| Package symlink/env/archive | inline secret 거부, 손상 archive 거부 | Package 원본 링크 거부 |
| report destination HTTP | 비소유 파일·다른 Job 충돌 거부 | 링크 destination 거부 |
| saved results | 기존 일반 결과/경로 검증 전체 | 외부 링크 결과를 읽지 않음 |
| Store symlink/ID | 디렉터리와 YAML ID 불일치 거부 | alias 링크 Job 거부 |
| Trash traversal/link/YAML | 경로 이탈·손상 YAML 거부 | alias 링크 미노출, restore 거부, 원본 보존 |

UID fixture를 고친 뒤 도달할 수 있는 maintenance/audit 링크 사례도 같은 경계로 분리했다.
삭제 도중 directory replacement 검증은 먼저 실제 링크 생성 가능 여부를 확인하고, 가능할 때 원래 race 및 외부 파일 보존 검증을 수행한다.
링크 권한이 없는 Windows에서 실제 링크 기반 보안 보장은 **미검증**으로 남는다.
기존 Windows reparse-point 및 junction 모의 검증은 유지하지만, 이를 실제 링크 테스트의 대체 증거로 세지 않는다.

## 수집 및 회귀 검증

`tests.test_windows_test_imports`는 새 인터프리터마다 remote helper와 추가 `fcntl` import를 거부한다.
POSIX에서는 runner.common의 정상적인 로컬 lock 구현만 먼저 로딩하고, Windows에서는 기존 msvcrt 경로를 그대로 사용한다.
다음 3개 모듈이 실제 TestCase로 수집되며 loader placeholder로 대체되지 않는 것을 확인했다.

| 모듈 | 수집한 메서드 수 |
| --- | ---: |
| `tests.test_dashboard` | 13 |
| `tests.test_deployments` | 10 |
| `tests.test_multi_schedule` | 15 |

기존 ownership/handoff import 검증도 유지했다. 원격 도우미가 차단된 상태에서 공통 배포 client 테스트 2개도 실행한다.
별도 새 프로세스에서는 호스트 `os.getuid`를 제거하고 기본 factory 선택을 Windows로 설정한 상태에서 launchd 모의 일정·다중 일정·소유권 보호 사례를 실행하며, 종료 후 합성 UID가 누출되지 않는지 확인한다.
이것은 **의존성/fixture 회귀 검증**이며 실제 Windows 호스트 실행 결과는 아니다.

검증 호스트: macOS 15.6.1 ARM64, 기존 venv CPython 3.9.6. 의존성 변경 없음.
초기 제한 환경 focused 실행 33개 중 7개는 기존 `launchctl list` 읽기 권한 제한으로 오류가 났다.
fixture 오류로 오인하거나 SKIP으로 바꾸지 않았으며 승인된 테스트 접근으로 전체 회귀를 실행했다.
일반 회귀에서는 native scheduler opt-in 환경변수 두 개를 제거한다.

최종 실행 결과는 [validation 기록](validation.md#windows-regression-phase-1--2026-11-15)에 기록한다.

## 남은 9개: 이번 변경에서 수정하지 않음

보고서의 UTF-8 재검증에도 남은 9개를 각각 하나의 **부모 테스트 메서드**로 분류했다.
원문 raw traceback/Run 로그는 첨부되지 않았으므로 아래에서 추론과 미확정을 구분한다.
Mac PASS를 Windows 오류 해소로 해석하지 않는다.

| 항목 (테스트 메서드) | 원인 분류와 소스 근거 | 제품 영향 가능성 / 별도 후속 확인 |
| --- | --- | --- |
| `test_dashboard_run.test_wait_timeout_resume_and_duplicate_lock` | **미확정**. 응답에 `wait_timed_out` 없음. 짧은 wait(.05초)와 sleep(.5초) fixture지만, 조기 실행 실패·관측 오류 등 다른 응답 경로일 수도 있음 | 대기 제한/같은 Run 재관측 동작 영향 가능. 반환 전체 구조·동일 Run 상태/로그·이벤트 시점을 먼저 확인. 대기 시간을 늘리거나 키를 optional로 바꾸지 않음 |
| `test_deployment_cli.test_missing_package_zip_after_planning_rejected_before_ssh` | **fixture/Windows 파일 속성 유력**. Package 생성은 archive를 `chmod(0o400)`로 보호하는데 테스트는 곧바로 unlink. WinError 5만으로 handle 누수라고 확정할 수 없음 | 현재 실패는 제품 preflight 전에 발생하여 missing-ZIP 거부를 검증하지 못함. 별도 임시 Package의 readonly 속성/열린 handle을 분리 진단. 보존·삭제/cleanup 제품 동작 영향 여부도 확인 필요 |
| `test_lifecycle.test_real_execution_env_and_post_run_cleanup` | **fixture의 경로 표현 가정**. 로그에 `/workspace` 문자열을 기대하지만 관측은 Windows `\\workspace` 경로 | 이 assertion 자체로 managed workspace 오류는 입증되지 않음. Run 성공·Output cleanup·State 보존 assertion과 실제 환경 경로를 구분하여 확인 |
| `test_packages.test_downloaded_zip_runs_without_script_manager` | **fixture의 interpreter 탐색 가정**. `python3` 고정 호출, 보고서 exit 9009 | 독립 Package 실행 계약은 Windows에서 아직 미검증. 현재 venv 인터프리터와 command 탐색/Windows alias를 분리 확인. 제품 배포물 불량으로 확정하지 않음 |
| `test_parameters_http.test_dashboard_payload_api_and_cli_apply_identical_values` | **mock 계약 불완전**. Popen의 `pid`가 MagicMock이며 Windows lease JSON 저장 중 TypeError/HTTP 500 | 실제 Popen.pid는 정수이므로 이 오류만으로 실사용 결함은 입증되지 않음. 정상 PID mock과 실제 worker로 parameter API/CLI 일치·lease 해제 검증 필요. lease 보안 검사를 약화하지 않음 |
| `test_parameters_http.test_run_dashboard_cli_transmits_waits_and_resumes_same_run` | **미확정, 실행 경로**. HTTP/CLI의 Run이 failed, exit_code=None. worker 시작/lease/preflight/소스 캡처 등 단계의 증거 부족 | Windows 실제 parameter 실행 실패 가능. accepted Run의 parameters/contract, stderr 및 worker 상태부터 확인. 앞의 Popen mock 오류와 같은 원인으로 합치지 않음 |
| `test_reports.test_various_json_and_payload_escape_preserves_original` | **fixture의 newline 변환 유력**. write_text가 Windows에서 CRLF를 기록하고, 비교는 메모리의 LF 문자열과 수행 | HTML payload 원문 보존 계약의 기준(기록 바이트/텍스트)을 확인해야 함. 이 불일치만으로 XSS 결함은 입증되지 않음. escaping/CSP/악성 payload assertion을 유지하여 별도 재검증 |
| `test_results.test_bad_filters_are_rejected` | **플랫폼 경로 계약 차이**. `Path('/tmp/file').is_absolute()`는 Windows에서 drive 없는 rooted 경로에 대해 POSIX와 다른 결과 | 입력 거부 계약 차이 가능. 현재 file은 저장 artifact 후보를 필터링하고 읽기는 contained 경로로 제한하므로 이 보고서만으로 외부 파일 읽기 우회가 입증되지는 않음. drive/UNC/rooted/traversal 입력과 실제 읽기 경계를 보안 후속 과제로 확인 |
| `test_runtime_permissions_native.test_new_directories_inherit_and_reopen_keeps_existing_acl_and_data` | **환경/PowerShell module autoload 미확정**. Get-Acl 자동 로딩 실패, 별도 Import-Module 조회는 성공했다는 보고 | 실제 디렉터리 ACL 상속·재열기 후 보존은 미검증. profile 없는 동일 프로세스의 module 로딩과 읽기 결과 확인 필요. ACL 완화·보안 설정 변경·테스트 SKIP으로 해결하지 않음 |

권장 다음 단계는 별도 승인 범위로 (1) 경로/interpreter/newline/mock fixture 4건,
(2) ZIP 파일 속성·결과 경로 계약 2건, (3) timeout 응답·parameter worker·ACL 3건을 순서대로 재현·진단하는 것이다.
각 단계에서도 보안 assertion 유지와 실제 Windows 전체 재실행이 필요하다. 이번에는 이 9개에 대한 수정·해결 판정을 하지 않는다.

## Windows에서 남은 확인

기존 Windows venv와 격리된 테스트 루트에서 일반 회귀를 실행한다. 실제 예약 opt-in을 켜지 않는다.

```powershell
& '.\.venv\Scripts\python.exe' -X utf8 -m unittest tests.test_windows_test_imports tests.test_platform_helpers -v
& '.\.venv\Scripts\python.exe' -X utf8 -m unittest discover -v
```

첫 명령은 수집/fixture 경계 검증이며 전체 제품 PASS를 의미하지 않는다.
두 번째는 남은 9개와 수집 복구로 새로 실행되는 본문의 추가 실패를 그대로 기록해야 한다.
실제 링크 생성 권한 유무, 각 SKIP 이유, 부모 메서드와 subtest 수, 실행 환경/인코딩을 함께 보고한다.
권한이 있는 별도 승인 환경에서는 실제 링크 거부 사례도 실행해야 링크 보안 검증이 완료된다.
