# 설치와 에이전트 온보딩

이 문서는 특정 에이전트의 플러그인·Skill·셸 초기화 설정 없이 사용하는 절차입니다. Codex, Claude Code 또는 다른 도구에 저장소 주소와 “설치하고 합성 예제로 확인해 줘”를 전달할 수 있습니다. 에이전트가 AGENTS.md를 자동 탐색하지 않으면 이 문서와 [AGENTS.md](AGENTS.md)를 직접 읽게 하세요.

## 지원 범위와 사전 준비

| 범위 | macOS | Windows | Linux |
| --- | --- | --- | --- |
| CLI·수동 Job·결과·HTML·Dashboard | ARM64 / Python 3.13.18 독립 실검증 (기존 3.9.6 기록 보존) | 구현·모의 테스트, 실제 설치 미검증 | POSIX 구현, 실제 설치 미검증 |
| 로컬 예약 | launchd 구현, 이번 설치 검증에서 적용 안 함 | Task Scheduler 구현, 실환경 미검증 | 미지원 |
| SSH 배포 대상 | 미지원 | 미지원 | systemd user 구현, 실서버 미검증·기능 제한 있음 |

코드의 최소 Python은 3.9입니다. Python 3.9는 [유지보수 종료](https://devguide.python.org/versions/) 상태이므로 새 실사용 환경에는 유지보수 중인 CPython을 준비하세요. 새 환경에는 Python 3.13을 권장하며, 3.13.18에서 독립 설치를 확인했습니다. 코드 최소 버전은 이번에 바꾸지 않았습니다. 3.9.6은 과거 호환성 기록이며 보안 권장 버전이 아닙니다. 다른 Python 버전·Intel macOS의 성공은 보장하지 않습니다. [실제 검증 기록](docs/validation.md)과 [원격 제한](docs/packages.md)을 확인하세요. 원격 required_env, 표준 로컬 데이터 경로·보고서·로그/결과 동기화는 로컬과 동일하게 지원되지 않습니다.

필요한 것은 Git, venv/pip를 포함한 Python, 사용자 소유의 쓰기 가능한 빈 설치 경로, GitHub/PyPI 접근입니다. 저장소는 Public이며 아래 HTTPS clone에는 GitHub 로그인이나 토큰이 필요하지 않습니다. SSH clone을 선택하면 기존 Git SSH 인증이 필요합니다. 토큰·SSH 키·.env 값을 에이전트에 전달하거나 URL/명령에 넣지 마세요.

Script Manager는 신뢰하는 로컬 단일 사용자가 검토한 Job을 실행하는 도구입니다. Job은 사용자 OS 권한으로 실행되며 sandbox가 아닙니다. GitHub Private Vulnerability Reporting은 활성화되어 있습니다. 보안 제보는 [SECURITY](SECURITY.md#reporting)의 GitHub 비공개 절차 또는 [security@def-v.com](mailto:security@def-v.com), 일반 문의는 [oss@def-v.com](mailto:oss@def-v.com)을 사용하세요.

관리자 권한, DB, LLM API 키, Node, 브라우저 빌드는 기본 실행에 필요 없습니다. Node/Chrome은 선택적 개발 테스트 도구입니다. Job 전용 실행 파일과 라이브러리는 별도이며 자동 설치되지 않습니다. 프로젝트는 pip 패키지가 아니므로 pip install . 또는 전역 console command를 사용하지 않습니다.

## 1. 소스 받기

기존 동명 디렉터리가 없는 사용자 소유 상위 폴더에서 실행합니다. Public HTTPS clone은 인증 없이 읽을 수 있습니다. 기존 SSH 인증을 사용하려면 clone URL만 git@github.com:nstgmg/script-manager-oss.git 으로 바꿀 수 있습니다. SSH 인증이 준비되지 않았다면 사용자가 Git의 정상 인증 절차로 준비하거나 HTTPS를 사용하세요. 여기서 소스 다운로드용 Git SSH 인증은 배포 엔진의 원격 작업을 실행하지 않습니다.

```sh
git clone https://github.com/nstgmg/script-manager-oss.git script-manager-oss
cd script-manager-oss
```

기존 설치·venv·Job·운영 데이터를 복사하거나 설치 경로를 덮어쓰지 않습니다. 다운로드 ZIP을 선택한 경우에도 새 폴더에 풀고 코드 루트로 이동합니다.

## 2. 가상환경과 초기화

아래 세 플랫폼 중 자신의 셸에 맞는 블록 하나만 실행합니다. 가상환경 활성화 없이 절대/상대 실행 파일을 직접 호출하므로 shell profile이나 PowerShell 실행 정책을 바꿀 필요가 없습니다.

### macOS (POSIX shell)

Git과 Python은 신뢰하는 공식 배포처/조직 관리 도구로 먼저 준비합니다. OS 소유 Python이나 다른 프로젝트 환경을 변경하지 않습니다.

```sh
python3 --version  # 새 설치는 Python 3.13 권장; 실제 선택 버전 확인
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
.venv/bin/python -m runner --help
.venv/bin/python -m runner list
```

### Windows (PowerShell, 실환경 미검증)

Git과 venv/pip 포함 Python을 먼저 설치합니다. Python launcher가 없다면 설치한 Python의 전체 경로를 사용합니다.

```powershell
py -3 --version
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip setuptools
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m runner --help
.\.venv\Scripts\python.exe -m runner list
```

### Linux (POSIX shell, 실환경 미검증)

배포판에서 Git, Python 3, venv/pip를 먼저 준비합니다. Debian/Ubuntu 계열의 python3-venv처럼 venv가 별도 OS 패키지일 수 있습니다. OS 패키지 설치가 필요하면 에이전트는 사용자 승인 없이 관리자 권한을 사용하지 않습니다.

```sh
python3 --version  # 새 설치는 Python 3.13 권장; 실제 선택 버전 확인
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
.venv/bin/python -m runner --help
.venv/bin/python -m runner list
```

venv가 제공한 pip/setuptools가 오래되면 알려진 취약점이 있을 수 있으므로 먼저 업데이트합니다. Python 버전에 맞는 최신 호환판이 선택되며, OS Python이나 기존 환경은 변경하지 않습니다. Python 자체의 보안 업데이트는 별도로 필요합니다. Python 3.13.18의 신규 환경에서는 pip 26.3 / setuptools 84.2.1 / ruamel.yaml 0.18.17 / clib 0.2.15를 설치했고, 실제 설치 환경 감사에서 알려진 취약점은 0건이었습니다. 기존 3.9.6 환경의 설치 도구 advisory 6건은 그 환경에 남아 있으며 기존 venv는 수정하지 않았습니다. 이 6건에 대한 수정 버전은 pip >=26.2 / setuptools >=84.1.0입니다. **호환 최신판 선택이나 업데이트 성공만으로 보안을 단정하지 말고 실제 버전과 감사를 확인하세요.** [취약점별 판정](docs/public-readiness.md#기존-advisory-6건별-판정)을 참조하세요.

requirements.txt는 ruamel.yaml==0.18.17을 고정합니다. CPython <3.15에서는 전이 의존성 ruamel.yaml.clib>=0.2.15도 설치합니다. 전이 버전은 플랫폼/설치 시점에 따라 달라질 수 있습니다. [제3자 고지](THIRD_PARTY_NOTICES.md)를 보존하세요.

별도 init 명령은 없습니다. list가 데이터 루트의 jobs/와 runtime/을 만들며 새 설치의 목록은 []입니다. 명령은 항상 runner/, dashboard/가 있는 코드 루트에서 실행합니다. `python -m runner --root DATA_ROOT list`처럼 --root는 하위 명령 앞에 오며 데이터 경로만 선택합니다. Python 모듈 검색 경로를 바꾸지 않습니다. 코드와 데이터 루트가 다르면 .env도 데이터 루트 기준입니다.

## 3. 네트워크 없는 합성 Job 한 번 실행

새 설치의 list가 비어 있는지 확인한 뒤 진행합니다. 기존 hello-output이 있으면 get으로 확인하고 멈추며, 덮어쓰기·삭제·재실행하지 않습니다. POSIX에서는 아래 순서를 사용합니다.

```sh
.venv/bin/python -m runner create --help
.venv/bin/python -m runner run --help
.venv/bin/python -m runner results --help
.venv/bin/python -m runner create hello-output --file examples/hello-output/job.yaml
cp examples/hello-output/main.py examples/hello-output/README.md jobs/hello-output/
.venv/bin/python -m runner get hello-output
.venv/bin/python -m runner run hello-output --wait
.venv/bin/python -m runner results hello-output --keyword Alpha --source synthetic --status ready
```

Windows PowerShell은 다음과 같습니다. 예제의 python3 명령은 Windows 실행기에서 현재 실행 인터프리터로 치환합니다. 실제 Windows 검증 완료를 뜻하지 않습니다.

```powershell
.\.venv\Scripts\python.exe -m runner create --help
.\.venv\Scripts\python.exe -m runner run --help
.\.venv\Scripts\python.exe -m runner results --help
.\.venv\Scripts\python.exe -m runner create hello-output --file examples/hello-output/job.yaml
Copy-Item examples/hello-output/main.py,examples/hello-output/README.md jobs/hello-output/
.\.venv\Scripts\python.exe -m runner get hello-output
.\.venv\Scripts\python.exe -m runner run hello-output --wait
.\.venv\Scripts\python.exe -m runner results hello-output --keyword Alpha --source synthetic --status ready
```

create --file은 정의를 검증하지만 기본 main.py/README도 생성하므로 예제 복사가 필수입니다. get에서 schedules: [], required_env/parameters 미선언을 확인합니다. run은 정확히 한 번 제출하고 반환된 id를 기록합니다. 성공 조건은 state=succeeded, exit_code=0, stdout에 `Hello Output: wrote 2 synthetic records to result.json`, stderr 비어 있음, 저장 Output 두 레코드 및 위 필터 total=1입니다. parameters/parameter_contract_version 필드가 반환되면 해당 Run 값을 그대로 보고합니다.

아래 RUN_ID는 반환된 실제 id로 바꿉니다. Windows는 실행 파일 경로만 앞 절과 같이 바꿉니다.

```sh
.venv/bin/python -m runner runs hello-output
.venv/bin/python -m runner logs hello-output RUN_ID --stream stdout
.venv/bin/python -m runner logs hello-output RUN_ID --stream stderr
.venv/bin/python -m runner results hello-output --run RUN_ID
.venv/bin/python -m runner report-render hello-output --source runtime/job-data/hello-output/output/RUN_ID/result.json
```

Output 위치는 runtime/job-data/hello-output/output/RUN_ID/result.json, HTML은 반환된 reports/hello-output.html입니다. HTML은 파일로 열 수 있고 서버가 필요 없습니다. 로그가 한 페이지를 넘으면 반환된 offset으로 계속 조회합니다. 실패/대기/관찰 오류는 성공이 아니며 같은 Run ID를 조회합니다. run을 다시 제출하지 마세요. [예제 계약](examples/hello-output/README.md)과 [결과 조회](docs/result-queries.md)를 확인하세요.

## 4. 선택적 Dashboard 시작과 종료

**에이전트는 설치 요청만으로 Dashboard를 시작하지 않습니다.** 사용자가 서비스 시작을 명시적으로 승인한 뒤 진행합니다. 기존 프로세스·포트를 읽기 전용으로 확인하고, 같은 루트의 서비스를 확인할 수 있으면 재사용합니다. 서비스/포트 확인 권한이 없으면 제약을 보고하고 새 인스턴스를 만들지 않습니다. 토큰이 포함된 /api/session 응답을 출력·저장하지 말고 root만 메모리에서 비교합니다. 다른 루트나 점유 포트의 서비스를 종료·재시작하지 않습니다.

POSIX의 승인된 foreground 시작:

```sh
.venv/bin/python -m dashboard --help
.venv/bin/python -m dashboard --root . --port 8765
```

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m dashboard --help
.\.venv\Scripts\python.exe -m dashboard --root . --port 8765
```

터미널에 출력된 실제 URL을 열고 session root가 이 설치인지 확인합니다. 기본은 http://127.0.0.1:8765 이며 loopback에만 bind합니다. 포트가 점유되면 기존 서비스를 확인한 뒤 승인된 새 서비스에 다른 빈 포트를 지정할 수 있습니다. 공개 bind·프록시·포트 포워딩은 하지 않습니다. Dashboard는 인증 서버나 sandbox가 아닙니다.

**종료:** 사용자가 종료를 요청하면 이 절차로 직접 시작한 foreground 터미널에서 Ctrl+C를 누릅니다. 별도 stop/daemon 명령은 없습니다. 터미널이 다른 프로세스에 연결되어 있거나 소유를 확인할 수 없으면 멈추고 알립니다. Dashboard 종료가 이미 실행 중인 detached Job을 취소하지는 않습니다. Job 취소/예약 해제는 별도 승인 작업입니다. 설치 검증용 임시 서버의 시작과 종료를 함께 명시적으로 승인한 경우에는 해당 테스트 서버만 닫습니다.

run-dashboard는 기존 서버의 실행 클라이언트이고 시작 명령이 아닙니다. Package·Lifecycle·복구에는 Dashboard/기존 HTTP API가 필요합니다. 일반 CLI 설치 검증에서는 호출하지 않습니다. 선택적 에이전트별 보조 절차는 [Dashboard Skill](.agents/skills/sm-dashboard/SKILL.md)에 있으나 이 설치에 필수는 아닙니다.

## 에이전트가 진행할 범위

| 추가 질문 없이 설치 요청으로 수행 | 별도 사용자 요청/승인 또는 입력 필요 |
| --- | --- |
| 문서/소스/CLI help 읽기, 안전한 새 설치 경로 선택 | 기존 폴더/Job/Schedule 덮어쓰기·삭제 |
| 새 venv와 명시된 런타임 의존성 설치 | 관리자 권한·OS 패키지·전역 환경 변경 |
| list로 초기화, 합성 hello-output 등록·1회 실행·결과/HTML 확인 | Dashboard 서비스 시작·기존 프로세스 종료/재시작 |
| Run ID·상태·로그·Output·실제 검증 플랫폼 보고 | 실제 Job 실행·외부 API 수집·자격증명 등록 |
| 자신의 합성 검증 결과를 보존하고 위치 보고 | OS 예약 활성화/변경·SSH 배포/검증/롤백·보존 정리 |

필요 도구·권한·네트워크가 없으면 해당 단계와 해결 방법을 보고합니다. 인증/네트워크 제한을 우회하거나 다른 설치의 venv/비밀/데이터를 복사하지 않습니다. 실제 .env는 에이전트가 읽지 않으며 사용자만 직접 등록합니다. 실무 Job 작성은 [스크립트 작성 지침](docs/script-authoring.md), 실행 계약은 [CLI](docs/cli.md), 안전 경계는 [AGENTS](AGENTS.md)와 [SECURITY](SECURITY.md)를 따릅니다.

## 문제 해결

| 증상 | 확인과 조치 |
| --- | --- |
| clone: repository not found / Permission denied | 저장소 URL·GitHub 접근과 네트워크 정책 확인. Public HTTPS clone은 로그인 불필요; SSH 사용 시 기존 Git SSH 인증을 사용자가 확인. 토큰이나 키를 출력하지 않음 |
| python3/py 없음, 버전 <3.9 | 신뢰하는 Python 배포로 준비. 자동 관리자 설치 안 함 |
| No module named venv / ensurepip 없음 | 해당 배포의 venv/pip 패키지를 사용자 승인으로 준비하고 새 환경 생성 |
| pip TLS/DNS/proxy/접근 오류 | 승인된 네트워크·조직 CA/proxy 확인. TLS 검사 해제 안 함 |
| clib wheel 없음 / 컴파일 오류 | Python·CPU·pip 지원 확인. 새 venv에서 pip 업데이트 후 의존성 설치 재시도. 빌드 도구/OS 변경은 승인 필요 |
| No module named runner / ruamel | 코드 루트와 방금 만든 .venv Python인지 확인. --root는 import 경로 설정이 아님 |
| PermissionError / symlink 거부 | 사용자 소유의 일반 디렉터리 사용. 심볼릭 링크·공유 권한을 우회하지 않음 |
| Job ID 충돌 | 기존 Job 보존. 새 설치 경로에서 진행하거나 사용자에게 충돌 보고 |
| 예제가 기본 문구만 출력 / 결과 없음 | create 다음의 예제 파일 복사 누락 확인. 이미 제출한 Run을 먼저 관찰하고 추가 실행은 별도 요청 |
| Job 실행 파일/라이브러리 없음 | manager venv와 Job 의존성은 별도. POSIX python3는 PATH 해석이며 argv는 shell 아님. 필요 시 지원 etag update로 명시적 인터프리터 설정 |
| Dashboard address already in use | 기존 프로세스·session root 확인. 기존 서비스 종료 금지. 승인된 다른 포트 사용 |
| Dashboard Host/Origin/CSRF 거부 | 출력된 loopback URL 및 기존 보안 절차 사용. 검사를 완화하지 않음 |
| run 실패/관찰 중단 | runs/logs/results에서 같은 ID 재조회. 실패 원인을 확인하고 자동 재제출하지 않음 |
| 결과 없음/오래됨 | 수집 시각·Run·경로·경고 보고. 조회 요청만으로 재실행하지 않음 |

업데이트는 [기여·수동 반영](CONTRIBUTING.md) 절차를 따릅니다. 설치 제거를 이유로 예약·Job·runtime을 자동 삭제하지 않습니다.
