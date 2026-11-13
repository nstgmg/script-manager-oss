# Script Manager

반복해서 하는 일을 에이전트에게 말로 설명하세요. 에이전트가 재사용 가능한 스크립트를 만들고, Script Manager가 작업(Job)·실행 기록·저장 결과·OS 예약을 관리합니다. **에이전트는 자동화를 만들고, Script Manager는 실행합니다.**

예를 들어 다음과 같은 일을 맡길 수 있습니다.

- 정한 사이트나 API에서 지원사업 공고를 모아 정기적으로 저장하기
- 반복해서 받는 CSV·JSON 파일을 정리하고 여러 작업의 결과를 비교하기
- 만들어 둔 작업을 실행하고 실패 원인을 로그로 확인하기
- 저장된 결과를 자연어로 찾아보고, 서버 없이 열리는 HTML 보고서로 만들기

수집·정리·비교 같은 업무 로직은 목적에 맞게 에이전트가 작성합니다. 특정 사이트 수집기, 지원사업 데이터, 알림 연동이 기본 탑재된 것은 아닙니다. 배포 소스에는 개인 Job·운영 데이터가 없고, 네트워크 없는 합성 예제만 포함합니다. [할 수 있는 일과 한계](docs/capabilities.md)에서 구분을 확인할 수 있습니다.

## 에이전트에게 설치 맡기기

사용자 소유 프로젝트 폴더를 만들고, 그 폴더에서 파일·터미널을 다룰 수 있는 코딩 에이전트에 다음을 전달하세요.

> https://github.com/nstgmg/script-manager-oss 를 이 프로젝트 폴더에 설치해 줘.

에이전트는 [INSTALL](INSTALL.md)과 [AGENTS](AGENTS.md)에 따라 새 가상환경과 의존성을 준비하고, 합성 예제를 한 번 실행해 결과와 HTML을 확인합니다. 에이전트가 저장소 지침을 자동으로 읽지 못하면 두 문서를 읽도록 요청하세요. Git·지원 Python·다운로드 권한 등이 없으면 필요한 준비를 안내합니다. 기존 파일은 보존하며, 설치 요청으로 실제 데이터 수집·예약 활성화·Dashboard 시작·SSH 배포를 수행하지 않습니다.

설치 후에도 같은 프로젝트에서 자연어로 요청하면 됩니다. 별도 채팅 서버나 LLM API는 필요하지 않으며, 자연어 해석과 스크립트 작성은 사용 중인 에이전트가 담당합니다.

| 이렇게 요청하세요 | 다음에 진행할 일 |
| --- | --- |
| “이걸로 뭘 할 수 있어?” | 목적별 활용 사례와 지원 범위 안내 |
| “매일 지원사업 공고를 모으고 싶어.” | 수집 대상·결과·시각을 정하고 Job과 예약 준비 |
| “만든 작업들과 실행 결과를 보여줘.” | 실제 Job·실행 기록·저장 결과 조회 |
| “저장된 결과를 HTML 보고서로 만들어 줘.” | 재수집 없이 기존 JSON을 HTML로 변환 |
| “Dashboard를 시작해서 관리 화면을 열어 줘.” | 기존 서비스 확인 후 재사용 또는 승인된 시작 |

사용자는 명령을 외울 필요가 없습니다. [사용자 가이드](USER_GUIDE.md)는 요청 예시와 필요한 입력·승인, [기능 안내](docs/capabilities.md)는 제품 기능과 새 스크립트가 필요한 일을 설명합니다.

## 버전과 업데이트

루트 [VERSION](VERSION)의 `0.1.0`은 **예정된 첫 배포 버전**이며, 아직 공식 `v0.1.0` Release를 발행하지 않았습니다. 제품 버전 `X.Y.Z`는 공식 GitHub Release Tag `vX.Y.Z`와 대응합니다. VERSION만으로 공식 배포 여부를 판단하지 않습니다. 현재 기본 clone은 `main` 개발 소스 설치이며, Release가 없을 때 최신 `main`을 안정 버전으로 간주하지 않습니다.

처음 설치는 [INSTALL](INSTALL.md), 기존 설치의 버전 확인·업데이트·실패 시 코드 복구는 [UPDATE](UPDATE.md)를 따릅니다. 같은 프로젝트에서 에이전트에게 요청하세요.

> Script Manager 업데이트 확인해 줘.

이 요청은 버전·Release Notes·업데이트 계획 확인과 안내만 수행합니다. 적용하려면 “Script Manager 업데이트해 줘”라고 명시하세요. 에이전트는 안전 점검 후 승인 범위에서만 적용하며, 로컬 수정·비호환 변경·실행 중 작업과 충돌하면 덮어쓰지 않고 안내합니다. Job·예약·운영 데이터·설정·비밀정보를 보존하고 기존 Dashboard Skill 등록도 확인합니다. 자동 업데이트·자동 재시작은 하지 않습니다. 안정 Release가 없으면 적용할 안정 업데이트가 없다고 안내합니다.

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

- [무엇을 할 수 있나](docs/capabilities.md), [자연어로 사용하는 가이드](USER_GUIDE.md)
- [설치·에이전트 온보딩·문제 해결](INSTALL.md), [버전·업데이트](UPDATE.md), [에이전트 지침](AGENTS.md), [스크립트 작성](docs/script-authoring.md)
- [CLI](docs/cli.md), [운영](docs/operations.md), [파라미터](docs/run-parameters.md), [결과 조회](docs/result-queries.md), [HTML](docs/html-reports.md)
- [Package·배포](docs/packages.md), [보존 정책](docs/phase3-lifecycle.md), [기여·테스트](CONTRIBUTING.md), [공개 준비 검증](docs/public-readiness.md)

자체 코드·문서는 MIT입니다. [LICENSE](LICENSE)와 [제3자 고지](THIRD_PARTY_NOTICES.md)를 보존하세요. 런타임 바이너리·개인 데이터·외부 수집물은 배포하지 않습니다.
