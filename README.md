# Script Manager

에이전트가 반복 작업을 재사용 가능한 스크립트로 만들고, Script Manager가 Job·실행 기록·저장 결과·OS 예약을 관리합니다. **에이전트는 자동화를 만들고, Script Manager는 실행합니다.** 개인 Job과 운영 데이터는 포함하지 않습니다.

## 주요 기능

- 파일 기반 Job 정의와 검증, 한 Job의 여러 Schedule 관리
- 수동 CLI 실행, 상태·stdout/stderr·Output 확인, 저장 결과 필터 조회
- JSON을 서버 없이 여는 독립 HTML 보고서로 변환
- 선택적 loopback Dashboard, immutable Package와 보존 정책
- 명시적으로 승인한 Linux systemd user SSH 배포 워크플로우 (제한·미검증 범위 있음)

DB, LLM API, Node, 프런트엔드 빌드는 기본 실행에 필요 없습니다. Job은 사용자 권한의 임의 프로그램이며 sandbox가 아닙니다. 신뢰하는 코드만 실행하세요.

## 빠른 시작

Git과 venv/pip 포함 유지보수 중인 Python(3.13 권장; 코드 최소 3.9, 3.9 자체는 EOL)을 준비하고 새 사용자 소유 폴더에서 시작합니다. 저장소는 Public이며 HTTPS 소스 다운로드에는 GitHub 로그인이 필요하지 않습니다. 아래는 macOS/POSIX 셸 절차입니다. Windows PowerShell과 Linux의 상세 절차·지원 범위·오류 해결은 [INSTALL.md](INSTALL.md)를 따르세요.

```sh
git clone https://github.com/nstgmg/script-manager-oss.git script-manager-oss
cd script-manager-oss
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m runner --help
.venv/bin/python -m runner list
```

초기 목록이 비어 있고 hello-output이 없을 때만 합성 예제를 등록하고 한 번 실행합니다. create --file은 기본 소스도 생성하므로 예제 복사가 필요합니다.

```sh
.venv/bin/python -m runner create hello-output --file examples/hello-output/job.yaml
cp examples/hello-output/main.py examples/hello-output/README.md jobs/hello-output/
.venv/bin/python -m runner get hello-output
.venv/bin/python -m runner run hello-output --wait
.venv/bin/python -m runner results hello-output --keyword Alpha --source synthetic --status ready
```

반환된 Run ID를 보존하고 succeeded, exit_code=0, stdout/stderr와 Output 두 레코드를 확인합니다. Alpha 필터는 total=1이어야 합니다. [설치의 결과 확인 절차](INSTALL.md#3-네트워크-없는-합성-job-한-번-실행)와 [예제 계약](examples/hello-output/README.md)을 참조하세요. API 키·외부 수집·예약·Dashboard가 필요 없습니다. 기존 Job을 덮어쓰지 않습니다.

## 플랫폼과 안전 경계

macOS ARM64 / Python 3.13.18에서 독립 설치와 CLI·수동 실행·저장 결과·HTML·Dashboard를 검증했습니다. 기존 Python 3.9.6 기록도 보존합니다. Windows는 구현·모의 테스트, Linux 로컬 수동 기능은 구현 상태이며 실제 설치는 미검증입니다. Linux 로컬 예약은 미지원입니다. macOS launchd/Windows Task Scheduler의 native 적용은 이번 검증에서 수행하지 않았습니다. 자세한 [지원 표](INSTALL.md#지원-범위와-사전-준비)와 [검증 기록](docs/validation.md)을 확인하세요.

실제 SSH/systemd 서버는 미검증입니다. 원격 required_env는 project root 전달 누락으로 실행에 실패하고, 로컬 표준 데이터 경로·보고서·로그/결과 동기화도 동일하게 제공되지 않습니다. verified는 업무 실행 성공이 아닙니다. [Package·SSH 제한](docs/packages.md)을 먼저 읽으세요.

Dashboard는 사용자의 명시적 서비스 요청 후에만 시작하며 loopback 단일 사용자용입니다. 신뢰하는 로컬 사용자가 검토한 Job만 실행하세요. 공개 저장소라는 사실은 Dashboard의 인터넷 공개나 비신뢰 Job의 안전한 실행을 뜻하지 않습니다. 시작·기존 서비스 확인·Ctrl+C 종료는 [INSTALL](INSTALL.md#4-선택적-dashboard-시작과-종료)에 있습니다. Package·Lifecycle·복구용 전용 Runner CLI는 없습니다.

jobs/, runtime/, workspace/, reports/는 운영 데이터이며 Git에서 제외합니다. --root는 데이터 경로를 선택하는 전역 옵션입니다. 비밀은 사용자가 루트 .env에 직접 등록하고 Job의 required_env에 이름만 선언합니다. 에이전트는 실제 값을 읽지 않습니다. [SECURITY](SECURITY.md)를 확인하세요. 보안 취약점은 [SECURITY.md의 비공개 제보 절차](SECURITY.md#reporting)를 따르세요.

## 문의·협업

일반 문의·기여·협업·라이선스 문의는 [oss@def-v.com](mailto:oss@def-v.com)으로 보내세요. 보안 취약점은 [security@def-v.com](mailto:security@def-v.com) 또는 활성화된 GitHub Private Vulnerability Reporting으로 비공개 제보하세요. 공개 GitHub Issue에 취약점 세부 정보를 게시하지 말고 [SECURITY.md](SECURITY.md#reporting)를 따르세요.

## 문서

- [설치·에이전트 온보딩·문제 해결](INSTALL.md), [에이전트 지침](AGENTS.md), [스크립트 작성](docs/script-authoring.md)
- [CLI](docs/cli.md), [운영](docs/operations.md), [파라미터](docs/run-parameters.md), [결과 조회](docs/result-queries.md), [HTML](docs/html-reports.md)
- [Package·배포](docs/packages.md), [보존 정책](docs/phase3-lifecycle.md), [기여·테스트](CONTRIBUTING.md), [공개 준비 검증](docs/public-readiness.md)

자체 코드·문서는 MIT입니다. [LICENSE](LICENSE)와 [제3자 고지](THIRD_PARTY_NOTICES.md)를 보존하세요. 런타임 바이너리·개인 데이터·외부 수집물은 배포하지 않습니다.
