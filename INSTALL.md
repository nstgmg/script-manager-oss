# 설치와 에이전트 온보딩

이 문서는 특정 에이전트의 플러그인·Skill·셸 초기화 설정 없이 사용하는 절차입니다. Codex, Claude Code 또는 다른 도구에 저장소 주소와 “설치하고 합성 예제로 확인해 줘”를 전달할 수 있습니다. 에이전트가 AGENTS.md를 자동 탐색하지 않으면 이 문서와 [AGENTS.md](AGENTS.md)를 직접 읽게 하세요. **사용자가 사용할 OS와 파일시스템에서 직접 설치합니다.** Windows 요청을 에이전트의 Linux 컨테이너·WSL·원격 macOS에서 대신 설치하고 Windows 설치 완료라고 보고하지 않습니다. 대상 OS 터미널에 접근할 수 없으면 준비 가능한 명령과 접근 제약을 보고합니다.

설치 후 가능한 일은 [기능 안내](docs/capabilities.md), 자연어 요청 방법은 [사용자 가이드](USER_GUIDE.md)를 따릅니다. 설치 완료 보고에는 실제 설치 경로·사용한 Python·합성 Run과 결과 위치·미완료 단계를 적고, “이걸로 뭘 할 수 있어?” 또는 “만든 작업들과 실행 결과를 보여줘”로 이어갈 수 있음을 안내하세요.

## 지원 범위와 사전 준비

| 범위 | macOS | Windows | Linux |
| --- | --- | --- | --- |
| CLI·수동 Job·결과·HTML·Dashboard | ARM64 / Python 3.13.18 독립 실검증 (기존 3.9.6 기록 보존) | 외부 PC / Python 3.14.3 설치·예제 실행·결과 조회 성공 보고 (9 PASS / 1 SKIP); HTML·Dashboard 및 이번 복구 경로는 실검증 대기 | POSIX 구현, 실제 설치 미검증 |
| 로컬 예약 | launchd 구현, 이번 설치 검증에서 적용 안 함 | Task Scheduler 구현, 실환경 미검증 | 미지원 |
| SSH 배포 대상 | 미지원 | 미지원 | systemd user 구현, 실서버 미검증·기능 제한 있음 |

코드의 최소 Python은 3.9입니다. Python 3.9는 [유지보수 종료](https://devguide.python.org/versions/) 상태이므로 새 실사용 환경에는 유지보수 중인 CPython을 준비하세요. 새 환경에는 Python 3.13을 권장하며, 3.13.18에서 독립 설치를 확인했습니다. 코드 최소 버전은 이번에 바꾸지 않았습니다. 3.9.6은 과거 호환성 기록이며 보안 권장 버전이 아닙니다. 다른 Python 버전·Intel macOS의 성공은 보장하지 않습니다. [실제 검증 기록](docs/validation.md)과 [원격 제한](docs/packages.md)을 확인하세요. 원격 required_env, 표준 로컬 데이터 경로·보고서·로그/결과 동기화는 로컬과 동일하게 지원되지 않습니다.

필요한 것은 Git, venv/pip를 포함한 Python, 사용자 소유의 쓰기 가능한 빈 설치 경로, GitHub/PyPI 접근입니다. 저장소는 Public이며 아래 HTTPS clone에는 GitHub 로그인이나 토큰이 필요하지 않습니다. SSH clone을 선택하면 기존 Git SSH 인증이 필요합니다. 토큰·SSH 키·.env 값을 에이전트에 전달하거나 URL/명령에 넣지 마세요.

Script Manager는 신뢰하는 로컬 단일 사용자가 검토한 Job을 실행하는 도구입니다. Job은 사용자 OS 권한으로 실행되며 sandbox가 아닙니다. GitHub Private Vulnerability Reporting은 활성화되어 있습니다. 보안 제보는 [SECURITY](SECURITY.md#reporting)의 GitHub 비공개 절차 또는 [security@def-v.com](mailto:security@def-v.com), 일반 문의는 [oss@def-v.com](mailto:oss@def-v.com)을 사용하세요.

관리자 권한, DB, LLM API 키, Node, 브라우저 빌드는 기본 실행에 필요 없습니다. Node/Chrome은 선택적 개발 테스트 도구입니다. Job 전용 실행 파일과 라이브러리는 별도이며 자동 설치되지 않습니다. 프로젝트는 pip 패키지가 아니므로 pip install . 또는 전역 console command를 사용하지 않습니다.

## 1. 소스 받기

**clone 전에** 사용자 OS·현재 셸·절대 프로젝트/설치 경로를 확인하고 숨김 파일을 포함해 대상과 주변의 기존 설치를 확인합니다. 알려진 설치 경로가 있으면 먼저 재사용 여부를 판별합니다. 전체 디스크를 검색하거나 비밀 파일을 읽을 필요는 없습니다. 같은 폴더 안에 다시 clone해서 `script-manager-oss/script-manager-oss`를 만들지 않습니다.

| 관찰한 상태 | 다음 행동 |
| --- | --- |
| 기존 코드 + 작동하는 venv | 로컬 VERSION/HEAD/worktree와 아래 bootstrap 상태부터 확인. 기존 CLI로 list → 필요한 get/runs/results 조회. 재설치·pip 업그레이드·합성 재실행 금지 |
| 코드만 있음 / 의존성 설치 중 실패 | 같은 checkout에서 상태 확인 후 누락 단계만 재시도. clone·venv 복사·코드 덮어쓰기 금지 |
| jobs/runtime/.env 등 데이터 있음 + 환경 손상 | 기존 설치로 취급. 데이터와 실행 상태를 보존해 진단하고 [UPDATE](UPDATE.md)의 복구 절차 검토. 자동 새 설치/환경 교체 금지 |
| 다른 내용·불완전 clone·정체 불명 폴더 | 그대로 보존하고 보고. 실패한 clone을 같은 비어 있지 않은 폴더에 반복하지 않음; 필요 시 충돌 없는 새 경로 사용 |
| 대상 없음 / 숨김 파일까지 완전히 빈 폴더 | 아래 새 설치 진행 |

Public HTTPS clone은 인증 없이 읽을 수 있습니다. 기존 SSH 인증을 사용하려면 clone URL만 git@github.com:nstgmg/script-manager-oss.git 으로 바꿀 수 있습니다. SSH 인증이 준비되지 않았다면 사용자가 Git의 정상 인증 절차로 준비하거나 HTTPS를 사용하세요. 여기서 소스 다운로드용 Git SSH 인증은 배포 엔진의 원격 작업을 실행하지 않습니다.

```sh
git clone https://github.com/nstgmg/script-manager-oss.git script-manager-oss
# clone 종료 코드가 0일 때만 다음 명령 수행
cd script-manager-oss
```

PowerShell 5.1에는 `&&`가 없습니다. 예를 들어 새 설치의 clone은 아래처럼 실패 즉시 멈춥니다. 기존 경로가 있으면 이 블록을 실행하지 말고 먼저 위 표대로 판별합니다.

```powershell
if (Test-Path -LiteralPath '.\script-manager-oss') { throw 'Destination exists: inspect before cloning' }
git clone https://github.com/nstgmg/script-manager-oss.git script-manager-oss
if ($LASTEXITCODE -ne 0) { throw 'clone failed; preserve and inspect the destination' }
Set-Location -LiteralPath '.\script-manager-oss'
```

기존 설치·venv·Job·운영 데이터를 복사하거나 설치 경로를 덮어쓰지 않습니다. 다운로드 ZIP을 선택한 경우에도 새 폴더에 풀고 코드 루트로 이동합니다.

사용자가 이미 만든 프로젝트 폴더 안에 설치를 요청했다면 숨김 파일까지 확인합니다. 완전히 빈 폴더에서는 위 clone의 마지막 인자를 `.`으로 바꾸고 그 폴더를 코드 루트로 사용해도 됩니다(`cd script-manager-oss` 생략). 비어 있지 않으면 기존 내용을 보존하고 충돌 없는 새 하위 폴더를 선택해 실제 경로를 알립니다. 기존 설치로 확인되면 새 설치로 취급하거나 합성 예제를 다시 실행하지 말고 현재 상태부터 조회합니다.

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

### Windows (PowerShell 5.1/7, 새 복구 경로는 실검증 대기)

Git과 venv/pip 포함 Python을 먼저 준비합니다. `py -3 --version`으로 실제 선택 버전을 확인합니다. 외부 PC에서는 3.14.3으로 기본 설치를 완료했지만 모든 3.14 조합의 호환성을 뜻하지 않습니다. Python launcher가 없다면 `& 'C:\path with spaces\python.exe' ...`처럼 확인한 실행 파일을 직접 호출합니다. `py -3`이 실행되지 않거나 다른 OS에서 작업 중이면 먼저 보고합니다.

코드 루트에서 표준 라이브러리 전용 [bootstrap](scripts/bootstrap.py)의 **상태 조회부터** 실행합니다. 이 조회는 pip 네트워크 접근·초기화·Job·예약·서비스 변경 없이 `.venv`와 설치된 의존성을 확인하며 `.env` 내용은 읽지 않습니다. `data_paths`는 기본 코드 루트의 데이터 흔적만 찾습니다. 별도 `--root`를 쓰던 설치라면 그 데이터 경로와 기존 서비스도 별도로 확인하세요.

```powershell
py -3 --version
if ($LASTEXITCODE -ne 0) { throw 'Python unavailable' }
py -3 scripts/bootstrap.py
if ($LASTEXITCODE -ne 0) { throw 'Inspect failed; stop here' }
```

`state=ready`이면 재설치하지 않습니다. **신규/부분 설치이고 기존 데이터가 없음**을 확인한 경우에만 다음을 실행합니다.

```powershell
py -3 scripts/bootstrap.py --prepare
if ($LASTEXITCODE -ne 0) { throw 'Runtime preparation failed; inspect before retry' }
& '.\.venv\Scripts\python.exe' -m runner --help
if ($LASTEXITCODE -ne 0) { throw 'CLI import failed' }
& '.\.venv\Scripts\python.exe' -m runner list
if ($LASTEXITCODE -ne 0) { throw 'Initialization failed' }
```

bootstrap은 새 `.venv`만 생성하고 작동하는 부분 venv는 재사용합니다. pip가 없으면 그 venv의 ensurepip를 사용하고 pip/setuptools → requirements → pip check 순서로 **실패 즉시 중단**합니다. 실행은 Python argv 배열이며 `shell=True`, Activate.ps1, 관리자 권한, 실행 정책 변경, 전역 pip 설치를 사용하지 않습니다. `runtime_ready=true`는 의존성 준비 판정뿐이며 **설치 완료는 3절의 실행·로그·결과 파일 검증 후**입니다. 준비된 환경은 재호출해도 의존성을 다시 설치하지 않습니다.

pip에는 `--progress-bar off --no-color`와 자식 프로세스 범위의 비대화형 설정을 사용합니다. PowerShell 5.1의 native 실패는 `$ErrorActionPreference='Stop'`만으로 처리하지 않고 바로 `$LASTEXITCODE`를 검사합니다. 공백·한글 경로는 따옴표와 `&`로 호출하며 PowerShell 7 전용 `&&`, `||`, `??`, 삼항 연산자를 섞지 않습니다. 이 명령 구성은 모의 검증과 실제 OS 검증을 구분합니다.

### 부분 설치 재시도

| 실패 지점 | 안전한 복구 |
| --- | --- |
| pip 다운로드/requirements 실패, 아직 데이터 없음 | 같은 폴더에서 bootstrap 조회 → 원인 해결 → `--prepare` 재호출. 이미 설치된 패키지를 재사용하고 이후 단계는 성공 후에만 수행 |
| `.venv`는 있지만 python/pyvenv.cfg 없음, 실행 불가, 외부 링크/잘못된 prefix | 자동 삭제·재생성하지 않고 `partial_venv`/`broken_venv`/`unsafe_venv` 보고. 파일을 보존해 원인을 확인하고 별도 복구 결정; 같은 명령 재시도는 안전하게 중단 |
| 초기화가 시작되어 jobs/runtime 등이 있음 | `--prepare`로 의존성을 자동 변경하지 않음. 환경이 정상이라면 기존 CLI로 상태 확인; 손상 시 운영 데이터 보존 후 별도 복구 |
| 예제 create/copy 뒤 중단 | 기존 hello-output을 get/runs로 확인. 자동 덮어쓰기·재등록·제출 금지. 이번 설치 요청에서 직접 만든 예제이고 Run이 없음을 확인한 경우에는 기존 승인 범위에서 누락 단계만 이어서 수행. 소유/내용이 불명확하면 보존하고 보고 |
| Run 제출 뒤 관찰/조회 중단 | 저장한 ID의 runs/logs/results만 재조회. ID를 못 받았으면 runs에서 접수 여부를 먼저 확인; 새 Run 제출 금지 |

bootstrap의 `--prepare`는 새 환경 준비 도구이며 기존 설치 업데이트/복구 명령이 아닙니다. 운영 중인 환경이나 동시에 다른 에이전트가 설치 중인 폴더에서 실행하지 않습니다. macOS/Linux에서도 `python3 scripts/bootstrap.py`와 명시적인 `--prepare`를 사용할 수 있으며 아래 수동 명령 역시 **새 설치에서만** 사용합니다.

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

### Codex 프로젝트의 Dashboard Skill 등록

Codex에서 GitHub 주소와 설치 요청을 받은 에이전트는 이 단계까지 설치 과정으로 수행합니다. 사용자가 Skill을 수동 등록하거나 폴더를 다시 열게 하지 않습니다. 다른 에이전트의 CLI 설치에는 필수 단계가 아닙니다. Skill 등록은 Dashboard 실행 승인이 아니며 `allow_implicit_invocation: false`를 유지합니다.

설치 폴더로 `cd`하기 **전**의 Codex 프로젝트 루트(호스트의 프로젝트/작업 경로 또는 사용자가 지정한 경로)와 실제 저장소 루트를 각각 확정합니다. `git rev-parse --show-toplevel`은 저장소만 알려 주며 상위 Codex 프로젝트를 판별하지 못합니다. 현재 경로에서 임의로 상위 폴더를 고르지 않습니다. 루트가 불명확하면 후보 경로를 제시해 확인하고, 외부 경로 쓰기 권한이 없으면 필요한 등록 위치와 권한을 안내합니다. 권한 거부를 우회하거나 전역 Skill 경로에 대신 설치하지 않습니다.

| 설치 구조 | 등록 위치와 방법 |
| --- | --- |
| A. 프로젝트 루트 = 저장소 | 저장소의 `.agents/skills/sm-dashboard` 원본을 그대로 확인. 추가 링크/복사 없음 |
| B. 프로젝트 루트 아래 `script-manager-oss/` 저장소 | 프로젝트 루트의 `.agents/skills/sm-dashboard` → 저장소 원본. macOS/Linux는 상대 심볼릭 링크, Windows는 디렉터리 복사와 `script-manager-source.json` 원본 경로 기록 |

확정한 **절대 프로젝트 경로**를 아래 인자에 넣고, 저장소 코드 루트에서 실행합니다. Windows에서는 실행 파일을 `.\.venv\Scripts\python.exe`로 바꿉니다. 표준 라이브러리만 사용하며 Job/API/운영 데이터는 건드리지 않습니다.

```sh
.venv/bin/python scripts/register_dashboard_skill.py --project-root "/absolute/project"
.venv/bin/python scripts/register_dashboard_skill.py --project-root "/absolute/project" --check
```

등록 스크립트는 저장소가 해당 프로젝트 내부인지와 링크 경계를 검사하고 `mode`, `skill_path`, `source_path`, 두 루트를 반환합니다. 원본은 유지하며 기존 정상 링크 또는 변경 없는 자체 복사본은 재사용합니다. 기존 파일·다른 Skill·끊어진 링크·수정된/오래된 복사본은 덮어쓰거나 제거하지 않고 오류로 보고합니다. POSIX에서 링크 권한이 거부되어도 복사로 자동 우회하지 않습니다. Windows 복사는 관리자/Developer Mode의 링크 권한을 요구하지 않는 선택이지만 실제 Windows Codex 검색은 별도 실검증 대상입니다. 복사본은 스냅샷이므로 원본 업데이트 시 자동 동기화하지 않습니다. 충돌 경로를 사용자가 검토하기 전에는 교체하지 않습니다.

[공식 Codex Skill 탐색 규칙](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills)에 따르면 CWD부터 저장소 루트까지의 `.agents/skills`를 탐색하고 Skill 디렉터리의 심볼릭 링크를 따라갑니다. 프로젝트 루트에서 시작한 세션이 임의의 하위 저장소까지 탐색한다고 가정하지 않습니다. 공식 문서는 Skill 변경 자동 감지도 설명하지만, 호스트·버전별 반영 성공은 실제 확인해야 합니다.

설치 에이전트는 등록 후 현재 호스트가 제공하는 Skill 목록/선택기에서 `sm-dashboard`의 경로를 확인합니다. 지원되는 목록 새로고침이 있으면 사용하되, 없는 명령/API를 만들거나 전역 설정을 바꾸지 않습니다. [Codex App Server](https://learn.chatgpt.com/docs/app-server#api-overview)를 직접 사용하는 클라이언트는 **현재 세션을 제공하는 서버**의 `skills/list`에 `cwds: [프로젝트 절대 경로]`, `forceReload: true`를 전달해 다시 검색할 수 있습니다. 이는 runner CLI가 아니며 별도 서버에서 조회한다고 현재 앱의 캐시가 갱신되는 것은 아닙니다. 해당 기능이 노출되지 않은 호스트에서 임의의 서버 관리·재시작을 시도하지 않습니다.

새 Codex 세션 검증은 같은 프로젝트 루트에서 자동 검색된 Skill 경로와 명시적 호출 정책을 확인하며, 서비스를 실행할 필요는 없습니다. `--check` 성공과 파일 직접 읽기는 검색 성공의 증거가 아닙니다. 새 세션 검색과 설치 중 세션의 자동 반영은 별개입니다. 현재 세션에서 등록이 보이지 않고 지원되는 새로고침도 사용할 수 없다면 “등록 검증 완료, 현재 세션 자동 반영 미확인”으로 보고합니다. 목록 접근이나 새 세션 검증 자체가 불가능하면 “등록 검증 완료, Codex 자동 검색 미검증”으로 보고합니다. 명시적 Dashboard 요청 시에는 원본 Skill을 직접 읽어 수행할 수 있으며 폴더 재열기를 정상 설치 절차로 요구하지 않습니다. 실제 호스트별 결과는 [검증 기록](docs/validation.md)을 확인합니다.

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

Windows PowerShell은 다음과 같습니다. 예제의 python3 명령은 Windows 실행기에서 현재 실행 인터프리터로 치환합니다. 먼저 list가 빈 새 설치인지 확인합니다. 외부 PC의 기존 예제 성공 보고와 이번 명령/복구 경로의 실검증은 별개입니다.

```powershell
if (Test-Path -LiteralPath '.\jobs\hello-output') { throw 'Existing example: inspect get/runs; do not overwrite' }
& '.\.venv\Scripts\python.exe' -m runner create --help
if ($LASTEXITCODE -ne 0) { throw 'create help failed' }
& '.\.venv\Scripts\python.exe' -m runner run --help
if ($LASTEXITCODE -ne 0) { throw 'run help failed' }
& '.\.venv\Scripts\python.exe' -m runner results --help
if ($LASTEXITCODE -ne 0) { throw 'results help failed' }
& '.\.venv\Scripts\python.exe' -m runner create hello-output --file examples/hello-output/job.yaml
if ($LASTEXITCODE -ne 0) { throw 'create failed; do not copy or run' }
Copy-Item -LiteralPath 'examples/hello-output/main.py','examples/hello-output/README.md' -Destination 'jobs/hello-output/' -ErrorAction Stop
& '.\.venv\Scripts\python.exe' -m runner get hello-output
if ($LASTEXITCODE -ne 0) { throw 'get failed; stop before submission' }
& '.\.venv\Scripts\python.exe' -m runner run hello-output --wait
if ($LASTEXITCODE -ne 0) { throw 'Run failed or observation lost: inspect runs, do not resubmit' }
& '.\.venv\Scripts\python.exe' -m runner results hello-output --keyword Alpha --source synthetic --status ready
if ($LASTEXITCODE -ne 0) { throw 'Saved-result query failed; do not resubmit' }
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

Output 위치는 runtime/job-data/hello-output/output/RUN_ID/result.json, HTML은 반환된 reports/hello-output.html입니다. **파일이 실제 존재하고 JSON의 complete=true, records의 id가 alpha/beta 두 개인지도 확인**합니다. PowerShell에서는 실제 RUN_ID를 넣은 뒤 아래처럼 읽습니다.

```powershell
Get-Content -LiteralPath '.\runtime\job-data\hello-output\output\RUN_ID\result.json' -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
```

HTML은 파일로 열 수 있고 서버가 필요 없습니다. 로그가 한 페이지를 넘으면 반환된 offset으로 계속 조회합니다. 실패/대기/관찰 오류는 성공이 아니며 같은 Run ID를 조회합니다. run을 다시 제출하지 마세요. [예제 계약](examples/hello-output/README.md)과 [결과 조회](docs/result-queries.md)를 확인하세요.

완료 보고에는 사용자 OS/셸/Python 버전, 실제 코드·데이터·venv 경로, 기존/신규/부분 설치 판별, Run ID와 state/exit_code, 두 로그, 결과 파일 경로와 2행/Alpha 1행 확인을 포함합니다. 의존성 설치만 성공했거나 예제를 확인하지 못했으면 “환경 준비 완료, 설치 검증 미완료”로 구분합니다. 실제 OS 검증·모의 테스트·외부 사용자 보고·미검증 항목을 각각 표시하며 예약 실행 성공을 추정하지 않습니다.

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
| 확정된 프로젝트 내부의 Dashboard Skill 등록·확인(기존 파일 보존) | 프로젝트 루트 불명확 시 확인, 쓰기 허용 범위 밖 경로의 권한 확보 |
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
| PowerShell 5.1: 인덱스가 배열 범위를 벗어남 | 아래 진단 절차로 PowerShell/PSReadLine 예외인지 pip Python traceback인지 구분. 같은 checkout/venv 유지; 전체 설치·Run 재실행 금지 |
| clib wheel 없음 / 컴파일 오류 | Python·CPU·pip 지원 확인. 새 venv에서 pip 업데이트 후 의존성 설치 재시도. 빌드 도구/OS 변경은 승인 필요 |
| No module named runner / ruamel | 코드 루트와 방금 만든 .venv Python인지 확인. --root는 import 경로 설정이 아님 |
| PermissionError / symlink 거부 | 사용자 소유의 일반 디렉터리 사용. 심볼릭 링크·공유 권한을 우회하지 않음. Windows runtime 접근 거부는 [ACL 복구 절차](#windows-런타임-acl-복구) 확인 |
| Job ID 충돌 | 기존 Job 보존. 새 설치 경로에서 진행하거나 사용자에게 충돌 보고 |
| 예제가 기본 문구만 출력 / 결과 없음 | create 다음의 예제 파일 복사 누락 확인. 이미 제출한 Run을 먼저 관찰하고 추가 실행은 별도 요청 |
| Job 실행 파일/라이브러리 없음 | manager venv와 Job 의존성은 별도. POSIX python3는 PATH 해석이며 argv는 shell 아님. 필요 시 지원 etag update로 명시적 인터프리터 설정 |
| Dashboard address already in use | 기존 프로세스·session root 확인. 기존 서비스 종료 금지. 승인된 다른 포트 사용 |
| Dashboard Host/Origin/CSRF 거부 | 출력된 loopback URL 및 기존 보안 절차 사용. 검사를 완화하지 않음 |
| run 실패/관찰 중단 | runs/logs/results에서 같은 ID 재조회. 실패 원인을 확인하고 자동 재제출하지 않음 |
| 결과 없음/오래됨 | 수집 시각·Run·경로·경고 보고. 조회 요청만으로 재실행하지 않음 |

### Windows 런타임 ACL 복구

Python 3.13부터 Windows의 `mkdir(mode=0o700)`은 부모 권한을 상속하지 않는 보호 DACL을 생성합니다. [CPython 3.13.9 구현](https://github.com/python/cpython/blob/v3.13.9/Modules/posixmodule.c#L5284-L5292)은 SYSTEM·Administrators·owner에 접근을 허용하며, [공식 mkdir 설명](https://docs.python.org/3.13/library/os.html#os.mkdir)도 Windows의 특별 처리를 설명합니다. Codex sandbox와 일반 사용자 프로세스가 서로 다른 보안 토큰/소유자 문맥을 사용하면 접근에 차이가 생길 수 있습니다. 이 저장소에서 해당 두 문맥의 실제 재현은 아직 하지 않았습니다.

로컬 runtime과 하위 데이터·Job 생성 임시 폴더·스냅샷·Output/State/Workspace·Package 저장/임시 폴더는 이제 Windows에서 부모 ACL을 정상 상속해 생성합니다. Windows에 전달하는 `0777`은 ACL 부여 값이 아니며 Python이 해당 숫자 모드를 무시합니다. Everyone 권한을 추가하지 않습니다. POSIX의 `0700`, 파일 원자 저장 권한과 `.env` 검사, Linux 전용 원격 helper의 권한은 그대로입니다. `--root`로 별도 데이터를 쓰는 설치에도 같은 정책이 적용됩니다.

1. **신규 설치:** 사용자 소유의 비공유 일반 폴더를 사용합니다. 부모 ACL이 일반 사용자 계정과 필요한 sandbox 계정, 시스템/관리 주체에 한정되어 있고 자식 폴더·파일로 상속되는지 확인합니다. 사용자 프로필 아래라는 경로명만으로 안전하다고 가정하지 않습니다. 넓게 공유된 ACL을 상속하면 이 코드가 비공개 권한으로 좁혀 주지 않습니다. 필요한 작업에만 접근을 허용하고 Everyone/Users 전체에 새 권한을 주지 않습니다.
2. **기존 설치:** 코드 업데이트는 기존 ACL을 변경하거나 이미 막힌 디렉터리를 복구하지 않습니다. 접근 가능한 설치는 그대로 재사용합니다. 접근 거부가 발생하면 실행 계정·Python 버전·절대 코드/데이터 루트와 거부 경로를 기록하고 중단합니다. 같은 Run을 재제출하거나 runtime·venv·Job을 지우고 재설치하지 않습니다.
3. **읽기 전용 진단:** 일반 사용자 터미널과 sandbox에서 각각 `whoami /user`와 거부 경로 및 부모에 대한 `Get-Acl -LiteralPath 'C:\actual data root\runtime' | Format-List Owner,AreAccessRulesProtected,AccessToString`을 비교합니다. 경로는 실제 값으로 바꾸고 비밀 파일은 열지 않습니다. ACL 자체도 읽을 수 없다면 그 제한을 보고하며 우회·관리자 실행으로 재시도하지 않습니다. ACL 출력의 계정 식별자는 공개 보고에 그대로 게시하지 않습니다.
4. **데이터 보존과 복구:** 읽을 수 있는 원래 계정으로 Jobs·Schedules·Output·State·Workspace·Package와 배포 이력의 보존/백업을 먼저 검토합니다. 실행 중인 Job/서비스와 OS 예약은 건드리지 않습니다. 기존 ACL의 강제 변경, `icacls /reset`·재귀 권한 부여·소유권 탈취·Everyone 추가는 이 수정의 복구 방법이 아닙니다. 접근이 막힌 데이터의 복구는 소유자/관리 담당자가 필요한 계정과 최소 접근 범위를 검토해 별도로 승인한 절차로만 진행합니다. 자동 이전이나 새 루트로의 묵시적 전환도 하지 않습니다.
5. **접근 복구 후:** 같은 데이터 루트에서 `list`, 필요한 `get/runs/results`로 원래 기록을 확인합니다. 부분 초기화라면 다음 CLI 호출이 이미 생성된 디렉터리를 재사용합니다. 생성 실패 시에는 이번 작업이 소유한 새 임시 경로만 정리하고 기존 데이터는 보존합니다. 실제 Windows에서의 상속/계정 간 접근·거부·복구 검증 항목은 [검증 기록](docs/validation.md#windows-runtime-acl-compatibility--2026-11-15)을 따릅니다. 기존 Run 확인이나 ACL 점검은 새로운 Job 실행을 승인하지 않습니다.

### PowerShell 5.1 배열 인덱스 오류 진단

외부 Windows PC의 Python 3.14.3 설치에서는 venv python.exe로 pip를 호출하던 중 이 오류가 발생했고 CMD에서 이어서 성공했습니다. 원본 traceback·호스트·PSReadLine 버전이 없어 **원인은 미확정**입니다. [PSReadLine upstream #4102](https://github.com/PowerShell/PSReadLine/issues/4102)에는 PowerShell 5.1에서 동일한 `IndexOutOfRangeException`이 있지만, 이 보고만으로 같은 결함이라고 결론 내리지 않습니다. 이번 변경은 진행 표시와 셸 재해석을 줄이고 실패 후 계속 진행하는 문제를 막는 예방·복구 조치이며 해당 예외의 재현 수정으로 표시하지 않습니다.

1. 실패 단계·종료 코드와 비밀을 지운 예외 stack을 기록합니다. `$PSVersionTable.PSVersion`, `$Host.Name`, `Get-Module PSReadLine | Select-Object Name,Version`, `py -3 --version` 및 해당 venv의 `-m pip --version`을 확인합니다. `.env`, 전체 환경변수, 인증 포함 pip config는 출력하지 않습니다.
2. `Microsoft.PowerShell.PSConsoleReadLine`/`System.IndexOutOfRangeException`이면 셸 입력/렌더링 경로를 의심합니다. Python `Traceback`의 pip 내부 프레임이면 pip/의존성 경로를 조사합니다. 문구만으로 구분하지 않습니다. 기존 Run이 있으면 먼저 관찰하고 새로 제출하지 않습니다.
3. 동일 checkout에서 `powershell.exe -NoProfile -NonInteractive -Command "py -3 scripts/bootstrap.py"`로 읽기 전용 조회를 비교합니다. 필요 시 승인된 신규/부분 환경 준비에만 같은 명령의 마지막을 `scripts/bootstrap.py --prepare`로 바꿉니다. PSReadLine 설정·모듈 업데이트·전역 실행 정책 변경은 하지 않습니다.
4. CMD 우회가 필요하면 CMD를 직접 열어 `cd /d "C:\actual path\script-manager-oss"` 후 `py -3 scripts\bootstrap.py`부터 확인합니다. 데이터 없는 부분 환경에서만 `py -3 scripts\bootstrap.py --prepare`를 실행합니다. 실패하면 그 자리에서 멈추고 상태를 다시 확인합니다. POSIX의 `source`/`cp`, PowerShell의 `&`/`Copy-Item`을 CMD에 섞지 않습니다. 이후 CLI는 `".venv\Scripts\python.exe" -m runner ...`이며 예제 제출 여부를 먼저 확인합니다.

[pip 공식 옵션](https://pip.pypa.io/en/stable/cli/pip_install/#cmdoption-progress-bar)의 진행 표시 끄기와 [PowerShell native 종료 코드 처리](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_automatic_variables?view=powershell-5.1#lastexitcode)를 따릅니다. PowerShell 5.1/7, 프로필/비대화형, CMD에서 같은 환경을 비교하는 실제 Windows 후속 검증은 [검증 기록](docs/validation.md)에 남깁니다.

기존 설치의 버전 확인·업데이트는 [UPDATE](UPDATE.md)를 따릅니다. “업데이트 확인해 줘”는 확인·안내만 수행하고, 명시적인 “업데이트해 줘” 요청일 때만 안전 점검 후 승인 범위에서 적용합니다. 현재 VERSION의 `0.1.0`은 예정된 첫 배포 버전이며 아직 Release를 발행하지 않았습니다. 위 기본 clone은 `main` 개발 소스 설치로, Release 부재 시 최신 `main`을 안정 버전으로 간주하지 않습니다. 저장소 관리자 간 수동 소스 반영은 별도 [기여 절차](CONTRIBUTING.md)를 따릅니다. 설치 제거를 이유로 예약·Job·runtime을 자동 삭제하지 않습니다.
