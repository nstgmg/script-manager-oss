---
name: sm-dashboard
description: 사용자가 Script Manager Dashboard 서비스를 명시적으로 요청했을 때 기존 서비스를 확인해 접속 주소를 반환하거나 미실행 상태에서 기존 CLI로 시작한다. 일반 Job 실행·결과 조회에는 사용하지 않는다.
---

# Script Manager Dashboard

서비스 시작을 명시적으로 요청받았을 때만 이 절차를 수행한다. `$sm-dashboard` 호출은 이 절차에 따른 미실행 서비스 시작 요청으로 해석한다. 상태/주소만 물었다면 조회만 하고 시작하지 않는다. [AGENTS.md](../../../AGENTS.md)의 보존·접근 정책과 [CLI 설명서](../../../docs/cli.md#선택적-dashboard)를 따른다.

## 1. 프로젝트와 실행 환경 확인

- 이 Skill이 속한 저장소 루트를 절대 경로로 확정하고 해당 루트에서 작업한다. 다른 checkout의 프로세스를 이 프로젝트 서비스로 취급하지 않는다.
- `.venv/bin/python -m dashboard --help`를 확인한다. Windows에서는 `.venv\Scripts\python.exe`를 사용한다. 진입점은 `dashboard/__main__.py`, 서비스 구현은 `dashboard/server.py`다.
- 기존 옵션은 `--root`, `--port`뿐이다. Runner 하위 명령이나 서비스 start/status/stop CLI를 만들지 않는다. 의존성이 없으면 설치 필요 사항을 보고하고 임의 설치·설정 변경으로 범위를 넓히지 않는다.

## 2. 기존 서비스와 포트 확인

기본 포트는 8765이며 사용자 지정 포트와 다른 포트에서 실행 중인 동일 프로젝트도 확인한다. 조회만 수행하고 기존 프로세스나 Job을 종료·취소·재시작하지 않는다.

- macOS/Linux: `ps -axo pid=,command=`에서 `python ... -m dashboard` 실행 인자와 PID를 확인한다. macOS에서는 `lsof -nP -a -p PID -iTCP -sTCP:LISTEN`, `lsof -a -p PID -d cwd`로 리스너·작업 디렉터리를 확인할 수 있다. Linux에서는 사용 가능한 `ss -ltnp`와 `/proc/PID/cwd` 조회를 이용한다. 환경변수 전문은 조회하지 않는다.
- Windows: PowerShell의 `Get-CimInstance Win32_Process`에서 Python Dashboard의 `ProcessId`, `CommandLine`만 확인하고 `Get-NetTCPConnection -State Listen`의 `OwningProcess`와 연결한다. 프로세스 인자의 상대 `--root`만으로 프로젝트를 추정하지 않는다.
- 후보 URL은 `http://127.0.0.1:PORT`다. 승인된 loopback 접근으로 `GET /api/session`을 조회하고 메모리 안에서 `root`를 확정한 프로젝트 절대 경로와 비교한다. 응답 전문이나 `csrf` 값은 출력·파일 저장하지 않는다. 표시가 필요하면 `root`, `os`, `scheduler`만 선택한다. 읽기 GET에 변경용 토큰은 필요 없다. Host/Origin/CSRF 검사를 약화하지 않고 프록시·redirect로 다른 호스트에 연결하지 않는다.
- **동일 프로젝트의 응답하는 서비스가 있으면** 새로 시작하지 않고 기존 주소와 확인 결과를 보고한다. 사용자 요청 포트와 다르면 그 사실과 기존 주소를 알린다. 여러 개면 확인된 주소들을 보고하며 정리하지 않는다.
- **발견이 불확실하면** 시작하지 않는다. 프로세스/소켓 조회 권한 부족, loopback 접근 거부·timeout, 시작 중인 동일 프로젝트 프로세스, 다른 프로젝트/서비스의 포트 점유, session root 불일치를 구분해 보고한다. 연결 실패 하나만으로 미실행이라고 판단하지 않는다. 승인된 조회 접근이 필요하면 환경의 승인 절차를 사용하고, 불가능하면 제한을 보고한다.

## 3. 미실행인 경우에만 기존 명령으로 시작

프로세스·리스너 조회가 성공했고 동일 프로젝트 서비스가 없으며 요청 포트가 비어 있을 때만, 저장소 루트에서 다음 기존 명령을 실행한다. 다른 포트를 명시적으로 요청받았으면 `8765`를 그 값으로 바꾼다.

```sh
.venv/bin/python -m dashboard --root . --port 8765
```

Windows PowerShell:

```powershell
.venv\Scripts\python.exe -m dashboard --root . --port 8765
```

포그라운드 서버이므로 호스트가 유지할 수 있는 터미널/실행 세션을 사용한다. Python 서비스의 기존 실행·종료 코드에 프로세스 제어를 맡긴다. 별도 wrapper, daemon, PID 파일, supervisor, OS 예약, 새 HTTP API를 만들지 않는다. 호스트가 장기 실행 세션이나 포트 바인딩을 지원하지 않으면 시작 지원 불가로 보고한다.

중복 확인과 bind 사이의 경합으로 `Address already in use`가 발생하면 새 프로세스를 재시도하거나 기존 점유자를 종료하지 않는다. 2단계의 읽기 조회로 기존 서비스 여부를 확인하고 결과를 보고한다. 다른 포트로 임의 우회하지 않는다.

## 4. 성공 확인과 보고

- 시작 로그의 `Script Manager: http://127.0.0.1:PORT`와 프로세스 유지 여부를 확인한 뒤, 해당 주소의 `GET /api/session`이 성공하고 `root`가 일치하는지 확인한다. 짧은 제한 시간으로 조회하며 시작 명령은 반복 제출하지 않는다.
- 명령 접수나 URL 출력만으로 성공을 선언하지 않는다. 확인에 실패하면 “시작 요청 후 응답 확인 불가”와 알려진 세션/PID·주소·접근 제한을 보고한다. 자동 재시작하지 않는다.
- 최종 응답에는 `기존 서비스 사용` 또는 `새 서비스 시작`, 검증된 접속 URL, 프로젝트 루트와 확인 결과를 간결하게 적는다. 시작한 세션의 유지 제약이 있으면 함께 알린다. `csrf`는 포함하지 않는다.

이 Skill은 절차만 정의한다. 기존 CLI에는 전역 singleton, 서비스 검색·중지·재시작·daemon 기능이 없으며 이를 추가하지 않는다. 저장소 Skill 검색/명시적 호출 정책을 지원하지 않는 에이전트, 호스트 접근 없는 클라우드 환경, 필요한 조회·loopback·유지 세션 권한이 없는 환경에서는 자동 실행 지원을 주장하지 않는다. Windows 절차는 구현 인터페이스에 맞춘 안내이며 이 저장소의 이번 문서 검증에서는 실환경 시작을 시험하지 않았다.
