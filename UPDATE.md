# 버전 확인과 업데이트

Script Manager의 제품 버전은 루트 [VERSION](VERSION)에 `MAJOR.MINOR.PATCH`로 기록하며, 공식 GitHub Release의 Tag `vMAJOR.MINOR.PATCH`와 대응합니다. Job YAML의 `version`, 실행 파라미터 계약 버전, Package ID는 제품 버전과 별개입니다. 현재 `0.1.0`은 **예정된 첫 배포 버전**입니다. 아직 `v0.1.0` Release를 발행하지 않았으며, VERSION 파일이나 Tag만 있다고 공식 배포가 완료된 것은 아닙니다.

공식 배포 여부와 변경 내용은 [nstgmg/script-manager-oss Releases](https://github.com/nstgmg/script-manager-oss/releases)에서 확인합니다. 이 문서는 에이전트가 수행하는 수동 절차이며 자동 업데이트·자동 재시작 기능은 없습니다. Tag와 Release 발행은 저장소 관리자의 별도 작업입니다.

[v0.1.0 Release Notes](docs/releases/v0.1.0.md)는 첫 공식 릴리스의 발행 준비용 본문입니다. [검토 기록](docs/validation.md#v010-release-notes-review--2026-11-14)과 함께 확인하되, 저장소에 본문이 있다는 사실만으로 안정 Release가 존재한다고 판단하지 않습니다.

## 설치와 업데이트 요청 구분

처음 설치는 [INSTALL](INSTALL.md)을 따릅니다. 현재 README/INSTALL의 기본 clone은 `main` 소스를 받는 개발 소스 설치이며, Release 발행 전에는 안정 버전 설치라고 안내하지 않습니다. 공식 Release가 생기면 새 설치도 선택한 안정 Release의 Tag·커밋과 VERSION을 확인한 뒤 해당 소스로 INSTALL 절차를 수행합니다. 기존 설치에는 새 설치용 초기화·합성 Job 등록을 반복하지 않습니다.

| 사용자 요청 | 에이전트가 수행할 범위 |
| --- | --- |
| “Script Manager 업데이트 확인해 줘.” | 로컬 상태와 공식 Release·Release Notes를 읽고 버전·변경·충돌·계획만 안내. 코드 전환·의존성 설치·마이그레이션·서비스 조작은 하지 않음 |
| “Script Manager 업데이트해 줘.” | 아래 안전 점검과 계획 안내 후, 이미 승인된 범위에서만 적용·최소 검증. 추가 충돌이나 비호환 변경은 먼저 해결 방안을 확인 |

명시적 업데이트 요청은 안전한 제품 소스·선언 의존성 업데이트 범위의 승인입니다. 같은 내용을 반복 승인받을 필요는 없지만, Job·활성 Schedule 변경, 운영 데이터 마이그레이션, 충돌하는 사용자 파일 교체, 서비스 중단·재시작은 자동으로 승인되지 않습니다. 로컬 수정·비호환 변경·실행 중 작업 등 충돌이 있으면 덮어쓰지 말고 적용을 보류해 필요한 선택을 안내합니다.

## 1. 로컬 버전·HEAD·작업 트리 확인

실제 설치 코드 루트와 데이터 루트를 먼저 구분합니다. CLI의 전역 `--root DATA_ROOT`는 데이터 경로만 선택합니다. 별도 데이터 루트를 사용하는 설치라면 아래의 모든 운영 조회에서 동일한 루트를 사용합니다.

Git 설치에서는 다음 읽기 전용 명령으로 시작합니다.

```sh
git rev-parse --show-toplevel
git remote -v
git rev-parse HEAD
git status --short --branch
git status --porcelain=v1 --untracked-files=all
git show HEAD:VERSION
```

루트 VERSION 파일도 직접 읽어 HEAD에 기록된 값과 비교합니다. POSIX는 `cat VERSION`, PowerShell은 `Get-Content VERSION`을 사용합니다. 원격 URL에 자격증명이 포함되어 있다면 보고서나 채팅에 출력하지 않습니다. 실제 `.env`는 읽지 않습니다.

- 신규 설치: VERSION, 선택한 Release Tag, 실제 HEAD를 함께 기록합니다. `main` 소스의 VERSION만으로 안정 Release 설치라고 단정하지 않습니다.
- 기존 설치: VERSION이 없거나 HEAD에 기록되지 않았다면 “제품 버전 미기록”으로 보고하고 HEAD·원격·작업 트리로 출처와 변경 범위를 식별합니다. 임의로 `0.0.0`이나 `0.1.0`을 대입하지 않습니다. 기준을 식별할 수 없으면 적용을 보류합니다.
- VERSION과 HEAD의 값이 다르거나 로컬 변경·미추적 파일이 있으면 내용을 보존하고 충돌 해결 방안을 안내합니다. 자동 stash·reset·clean·강제 checkout을 하지 않습니다. Git에서 무시하는 파일도 전환 대상 경로와 충돌하는지 확인하되 비밀 파일 내용을 열지 않습니다.
- ZIP 설치: VERSION은 읽을 수 있지만 `.git`이 없으면 HEAD·로컬 수정 여부를 Git으로 검증할 수 없습니다. 기존 폴더에 덮어 풀거나 Git 이력을 억지로 만들지 않습니다. 원본 배포물과 사용자 변경을 식별하고, 새 폴더에서 코드·의존성을 준비하는 별도 계획을 안내합니다. 데이터 경로·예약·Skill 참조 전환은 사용자 승인 범위에서만 진행합니다.

## 2. 최신 안정 Release 비교

공식 저장소의 GitHub Releases 또는 GitHub API를 읽습니다. API를 사용하는 경우 `GET https://api.github.com/repos/nstgmg/script-manager-oss/releases/latest`로 최신 안정 Release를 확인하고, `GET https://api.github.com/repos/nstgmg/script-manager-oss/releases`의 페이지를 계속 읽어 현재 버전 이후의 관련 Release를 검토합니다. Draft·Prerelease는 안정 업데이트 대상에서 제외합니다. Tag 목록·`main` HEAD·커밋 날짜를 안정 Release의 대용으로 사용하지 않습니다.

Tag `vX.Y.Z`를 숫자 버전으로 비교하고, 해당 Tag 커밋의 VERSION이 `X.Y.Z`인지 확인합니다. 불일치나 알 수 없는 버전 형식은 적용을 보류합니다. 로컬 HEAD가 같은 VERSION의 공식 Tag와 다르면 변경된/개발 소스 상태임을 별도로 알립니다. 로컬이 최신 안정판보다 높아도 자동 다운그레이드하지 않습니다.

**안정 Release가 없으면 “공식 안정 Release가 없어 적용할 안정 업데이트가 없습니다. 로컬 0.1.0은 예정 버전입니다”라고 안내하고 적용을 멈춥니다**(로컬 버전이 없으면 그 사실을 대신 보고). 최신 `main`을 안정 버전으로 간주하거나 `git pull`하지 않습니다. 개발 소스 반영은 별도 명시적 요청과 검토가 필요한 작업입니다.

API의 404만으로 Release 부재를 단정하지 말고 저장소 접근과 Releases 목록도 확인합니다. DNS·권한·인증·API 제한·통신 실패는 “확인 불가”로 구별합니다. 승인된 네트워크 접근만 사용하고 인증정보를 읽거나 제한을 우회하지 않습니다.

## 3. Release Notes와 마이그레이션 검토

현재 버전 이후부터 목표 안정 버전까지의 Release Notes와 연결된 마이그레이션 문서를 순서대로 읽습니다. 버전 미기록 설치는 식별한 HEAD 이후 변경을 함께 검토합니다. 중간 버전 적용 필요 여부, 지원 Python/OS, 제품·Job 의존성, CLI·Job YAML·파라미터·결과 형식, 데이터·예약·설정 호환성과 알려진 제한을 확인합니다. 필요한 설명이 없거나 비호환 변경의 영향이 불명확하면 추측으로 적용하지 않습니다.

제품 업데이트를 이유로 기존 Job의 코드·계약·의존성이나 Schedule 정의를 바꾸지 않습니다. 필요한 마이그레이션이 있으면 대상·영향·백업·검증·복구 가능성을 구체적으로 안내하고 별도 승인된 범위에서만 수행합니다.

## 4. 사용자 데이터와 설정 보호

적용 전 기존 코드 HEAD·버전·작업 트리, 실제 데이터 루트, Python/venv·설치 의존성 버전과 사용자 설정 위치를 기록합니다. 비밀 값은 기록하지 않습니다. 다음은 제품 소스 교체 대상이 아닙니다.

- `jobs/`의 사용자 코드·README·`job.yaml`, Schedule 정의와 OS 등록
- `runtime/`의 Run 기록·로그·Output·State·휴지통·보존 정책, 공유 `workspace/`, `reports/`와 사용자 지정 경로
- `.env`, 기존 호환 `env_file`, 사용자 설정, Job별 가상환경
- 배포 대상 설정, Package ZIP·메타데이터·배포 이력

기존 [.gitignore](.gitignore)를 유지합니다. 무시된 파일이 안전한 백업이라는 뜻은 아닙니다. 마이그레이션 등 위험이 있는 경우 사용자가 관리하는 비공개 백업 위치·범위·일관성 확보 방법을 계획에 포함하되, 에이전트는 실제 비밀 값을 읽거나 복사하지 않습니다. 운영 폴더 전체 복사·동기화나 `git clean -fdx`, `git reset --hard`, 강제 checkout·push를 업데이트 방법으로 쓰지 않습니다.

## 5. 실행 중 Job·Dashboard·예약 확인

[CLI](docs/cli.md)와 해당 명령 help를 확인한 뒤 기존 venv로 `list`/`get JOB_ID`, `runs JOB_ID`, `schedule-status JOB_ID`를 사용해 업데이트 전 기준을 확보합니다. `runs`는 고아 실행을 interrupted로 정리할 수 있는 기존 관리 조회입니다. 반환된 queued/running Run ID를 보존하며 새 실행을 제출하지 않습니다. 별도 데이터 루트는 `python -m runner --root DATA_ROOT ...`를 사용합니다. `.venv/bin/python`은 POSIX 예시이며 Windows는 `.venv\Scripts\python.exe`입니다.

프로세스·포트를 조회해 기존 Dashboard를 확인하고, 접근 가능한 서비스는 `GET /api/session`의 root를 메모리에서 비교합니다. CSRF를 포함하는 세션 응답을 출력·저장하지 않습니다. HTTP를 사용하기 전 [서버 구현](dashboard/server.py)과 기존 인터페이스를 확인합니다. 서비스/프로세스 발견·승인된 loopback 접근이 불가능하면 “미실행”이라고 가정하지 말고 점검 제한을 보고해 적용을 보류합니다.

실행 중 Job·Dashboard 또는 업데이트 중 실행될 수 있는 활성 예약과 충돌하면 안전한 작업 시점과 필요한 조치를 안내하고 보류합니다. 자동 취소·종료·재시작·예약 해제는 하지 않습니다. 사용자에게 승인받은 유지보수 범위가 있으면 그 범위에서만 기존 지원 절차를 사용합니다. 코드 전환 전에 상태를 다시 확인합니다. 실행 소스 스냅샷이 있다는 이유로 venv·설정 변경이 실행 중 Job에 안전하다고 가정하지 않습니다.

## 6. 변경 내용과 적용 계획 안내

사용자에게 현재 VERSION/HEAD와 안정 Release·목표 Tag/커밋, 주요 변경·마이그레이션, 보존 경로, 충돌과 실행 상태, 코드·의존성 적용 방법, 최소 검증과 코드 복구 지점을 알려 줍니다. “확인해 줘” 요청은 여기서 결과 안내로 끝냅니다. “업데이트해 줘” 요청은 충돌이 없고 승인 범위가 충분할 때 진행합니다. 추가 승인이 필요한 조치는 구체적인 계획을 먼저 제시합니다.

## 7. 승인 범위에서 제품 소스·의존성 반영

clean Git 설치의 기본 방식은 확인한 공식 Release Tag로 코드를 전환하는 것입니다. `git pull`로 최신 `main`을 합치지 않습니다. 정확한 원격·Tag를 지정해 fetch하고, 실제 Tag 커밋이 검토한 커밋과 같은지 재확인합니다. 예를 들어 목표가 공식 `vX.Y.Z`라면 `git fetch origin refs/tags/vX.Y.Z:refs/tags/vX.Y.Z` 후 `git rev-parse 'refs/tags/vX.Y.Z^{commit}'`로 확인하고, 충돌 점검을 통과한 경우에만 `git switch --detach refs/tags/vX.Y.Z`를 사용합니다. `vX.Y.Z`는 실제 검토한 Tag로 바꾸며 강제 옵션을 쓰지 않습니다. 로컬 동일 이름 Tag가 충돌하면 덮어쓰지 않습니다. detached HEAD가 된 사실과 원래 브랜치·HEAD를 보고에 남깁니다.

목표 Release의 INSTALL·의존성 선언에 따라 필요한 제품 의존성만 반영합니다. 기존 venv를 무작정 교체하거나 Job별 환경·전역 Python을 업그레이드하지 않습니다. 변경이 필요하면 이전 환경을 보존하고 별도 venv에서 준비·검증한 뒤, 기존 CLI·예약의 인터프리터 경로와 호환되는 전환 방법을 계획에 포함합니다. 새 venv로 바뀌었다고 OS 예약 경로를 임의로 재등록하지 않습니다. 자동 업데이트 엔진이나 시작/재시작 서비스를 추가하지 않습니다.

## 8. 최소 검증과 Dashboard Skill 유지

제품 코드 루트에서 실제 사용할 venv로 다음을 확인합니다. 검증 때문에 Dashboard를 시작하거나 실제 Job을 실행·생성하지 않습니다.

- VERSION·HEAD가 목표 Release와 일치하고 예상 밖 작업 트리 변경이 없는지 확인
- `python -m pip check`, `python -m runner --help`, 관련 하위 명령 help
- 동일 데이터 루트의 `list`와 필요한 `get JOB_ID`로 기존 Job ID·설정·예약이 유지되는지 비교
- 대표 저장 결과 조회(`result-jobs` → `results`) 등 Release가 영향을 주는 필수 기능을 기존 계약에 맞게 확인. 데이터가 없으면 없음을 보고하고 재수집하지 않음
- 필요한 실행 검증은 별도 임시 데이터 루트의 네트워크 없는 합성 예제로 한정하고 계획에 포함. 사용자 Job·데이터를 복사하지 않음. 실제 Job 실행·외부 통신·OS 예약 검증은 별도 승인 범위에서만 수행

전체 회귀 테스트·보안 감사를 매번 반복하지 않습니다. 변경 영향과 실패에 필요한 최소 검증만 수행하고 실제 성공/실패·미검증을 구분합니다.

Codex에서는 [기존 등록 절차](INSTALL.md#codex-프로젝트의-dashboard-skill-등록)에 따라 **기존에 확정한 실제 프로젝트 루트**를 사용해 `.agents/skills/sm-dashboard` 등록을 확인합니다. 저장소 루트나 임의 상위 폴더를 프로젝트 루트로 추정하지 않습니다. 아래는 저장소 코드 루트에서 수행하며 실행 파일은 기존 venv에 맞춥니다.

```sh
.venv/bin/python scripts/register_dashboard_skill.py --project-root "/absolute/project" --check
```

등록이 없고 쓰기가 승인된 프로젝트 경로라면 같은 기존 스크립트에서 `--check`를 빼고 등록한 뒤 다시 확인합니다. 저장소 내부 원본·정상 symlink는 그대로 유지합니다. Windows의 기존 복사본이 오래되었거나 수정되었으면 스크립트가 교체하지 않고 오류를 보고하므로 충돌을 안내합니다. 기존 외부 파일·복사본·링크를 무단 삭제·교체하거나 전역 설치하지 않습니다. `allow_implicit_invocation: false`를 유지합니다.

호스트의 Skill 목록/새로고침 기능이 있으면 검색도 확인합니다. 파일 등록 성공과 현재 세션 자동 검색은 별개입니다. 목록이나 새 세션 확인이 불가능하면 등록 결과와 자동 검색 미검증을 구분해 보고합니다. 검증을 위해 호스트나 Dashboard를 재시작하지 않습니다.

## 9. 결과 보고와 실패 시 코드 복구

최종 보고에는 이전→현재 버전·HEAD, 공식 Release URL/Tag, 코드·의존성 적용 결과, 최소 검증 결과와 미검증, 데이터·예약·서비스 보존 상태, Skill 등록/검색 결과, 남은 수동 작업을 포함합니다. 검증 실패나 적용 보류를 업데이트 완료로 보고하지 않습니다.

실패하면 추가 변경을 멈추고 실패 단계와 실제 코드·환경 상태를 기록합니다. 진행 중 Run 관찰은 같은 ID로 계속하며 재제출하지 않습니다. 적용 전 기록한 HEAD가 있고 작업 트리가 여전히 clean이며 실행 상태·경로 충돌을 재점검한 경우에만, 승인된 코드 복구 계획에 따라 `git switch --detach OLD_HEAD`로 이전 제품 코드로 돌아갑니다. `OLD_HEAD`는 기록한 실제 커밋입니다. 원래 브랜치 복귀도 브랜치가 이동하지 않았고 안전함을 확인한 뒤 수행하며 이력을 재작성하지 않습니다. 새 사용자 변경이 생겼다면 강제로 되돌리지 않고 보류합니다.

의존성은 보존한 이전 venv 또는 기록된 이전 선언으로 검토한 환경을 사용하고 최소 검증을 반복합니다. 환경 복원이 확인되지 않으면 코드만 복구되었다고 보고합니다. ZIP 설치는 보존한 이전 코드·환경 경로로 돌아가는 승인된 전환 계획을 따릅니다. 경로 전환 때문에 서비스 재시작·예약 수정이 필요하면 별도 승인 없이 수행하지 않습니다.

**코드 복구는 운영 데이터 복원이 아닙니다.** Job·Schedule·Output·State·Workspace·설정·비밀정보·실행/배포 이력을 임의로 삭제하거나 과거 백업으로 되돌리지 않습니다. 마이그레이션이 이미 데이터를 변경했다면 구버전 코드와의 호환성을 먼저 확인하고, 불명확하면 구버전을 실행하지 않습니다. 데이터 복구는 영향·백업 시점·유실 가능성·복구 절차를 별도로 검토해 승인받아야 합니다.
