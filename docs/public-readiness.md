# 공개 상태와 검증 기록

상태 확인일: 2026-11-13 (Asia/Seoul). 저장소 `nstgmg/script-manager-oss`는 **Public**이며 GitHub Security Overview에서 **Private Vulnerability Reporting Enabled**를 확인했습니다. Security policy, Security advisories, Dependabot alerts, Code scanning alerts, Secret scanning alerts도 Enabled로 관찰했습니다. 이 확인은 설정 변경, 알림 전달·비관리자 제보 폼·메일 송수신의 새 검증을 뜻하지 않습니다.

보안 제보는 [security@def-v.com](mailto:security@def-v.com) 또는 GitHub의 비공개 제보 절차, 일반 문의는 [oss@def-v.com](mailto:oss@def-v.com)을 사용하세요. 자세한 절차는 [SECURITY](../SECURITY.md#reporting), 설치는 [INSTALL](../INSTALL.md), CodeQL 기준 커밋 `9040b78`의 분류·최소 수정·경고 관리 기준은 [CodeQL 후속 조치](codeql-triage.md)를 따릅니다.

공개 소스는 신뢰하는 로컬 단일 사용자가 검토한 Job을 실행하는 도구입니다. Dashboard의 공개 bind·프록시·포트 포워딩, 다중 사용자 제공, 비신뢰 Job 실행을 안전하다고 주장하지 않습니다. Windows·Linux 실제 설치, native 예약, 실제 SSH/systemd 미검증과 Linux 로컬 예약 미지원, 원격 required_env·표준 데이터 경로 등의 제한은 유지합니다. 아래의 과거 성공 기록을 새로운 플랫폼 검증으로 해석하지 마세요.

## 현재 운영 확인

- [x] 저장소 Public 및 Private Vulnerability Reporting Enabled를 GitHub UI에서 확인.
- [x] 공식 보안/일반 연락처를 유지하고 현재 공개 상태와 문서 안내를 일치시킴. 이메일 송수신은 이번에 반복하지 않음.
- [ ] 비관리자 관점의 Report a vulnerability 폼, 유지보수자 알림 전달·private report 접근·메일 모니터링을 별도로 확인. 허위 제보는 제출하지 않음.
- [ ] Dependency graph, Dependabot security updates/grouping, repository push protection의 세부 상태는 개별 확인. 관련 alerts Enabled만으로 이 설정까지 켜졌다고 추정하지 않음.
- [ ] CodeQL은 정확한 푸시 SHA의 분석 완료 후 실제 경고 변화를 확인. 분류 기록을 경고 일괄 해제로 사용하지 않음.

이 후속 작업은 실제 Job·OS 예약·원격 배포·기존 서비스·GitHub 보안 설정을 변경하지 않습니다. Release/Tag 생성이나 보안 무결점·전체 원격 기능 지원을 선언하는 작업도 아닙니다.

<details>
<summary>Public 전환 전 Phase 3·4 및 연락처 정비 원기록 — 당시 상태로 보존</summary>

아래의 Private, 기능 Off/Disabled, Public 전 승인·활성화 대기, 과거 후보 판정·커밋은 해당 검증 당시의 기록입니다. 현재 공개 상태와 보안 기능 활성 여부는 위 현황을 따릅니다. 설치·의존성 감사·기능 테스트를 이번에 재실행했다는 뜻이 아닙니다.

# 공개 준비 현황 — 공식 연락처 최종 정비

최종 정비일: 2026-11-13 (Asia/Seoul). 대상: `nstgmg/script-manager-oss` **Private**, 이번 문서 변경의 기준 커밋 `7f94eb14d861df18f2f3f98875f7a68423c3414c`. 아래 Python 3.13·의존성 감사는 기존 Phase 4 검증(기준 `f8d229134a88a68ed0759eab00f1e6185b16608d`) 결과를 보존한 것이며 이번에 재실행하지 않았습니다.

**판정: Public 전환 승인 요청이 가능한 후보입니다. 공개 전 미해결 기술 차단 P0/P1은 0건입니다.** Phase 3의 Python/설치 도구 P1은 새 Python 3.13 환경에서 해결했고, 제보 채널 P1도 외부 송수신이 확인된 공식 비공개 이메일을 확보해 해결했습니다. GitHub Private Vulnerability Reporting은 Public 직후 활성화·확인할 추가 채널이며 현재 제보 폼은 비활성입니다. 별도 명시적 Public 승인과 아래 전환 절차를 수행하기 전에는 공개 운영 준비 완료로 간주하지 않습니다. 기능 확장·최소 Python 변경·Public 전환·Release·Tag 생성은 하지 않았습니다.

## 공식 연락처와 이번 변경 범위

- 일반 문의·기여·협업·라이선스 문의: [oss@def-v.com](mailto:oss@def-v.com).
- 보안 취약점 비공개 제보: [security@def-v.com](mailto:security@def-v.com), [SECURITY.md](../SECURITY.md#reporting)의 절차를 따릅니다. 공개 GitHub Issue에 취약점 세부 정보를 게시하지 않습니다.
- 두 주소의 외부 송신·수신은 사용자가 확인 완료했습니다. 이번 작업에서는 메일을 재발송하지 않았습니다.
- README·CONTRIBUTING·SECURITY·이 문서만 수정합니다. 개인 이메일·메일 운영 설정·자격증명은 공개 문서에 추가하지 않습니다. 응답·수정 기한은 약속하지 않습니다.
- 공개 후보는 이번 문서 커밋의 정확한 SHA입니다. SHA를 문서 자체에 넣는 순환을 피하기 위해 커밋 후 로컬 HEAD와 origin/main의 일치를 최종 보고에서 확인합니다.

## Python 3.13 독립 설치와 실행

호스트에 3.13이 없어 공식 Astral uv 0.13.8 ARM64 자산을 임시 경로에 받고 GitHub 배포 SHA-256과 대조했습니다. uv의 [관리형 CPython 배포](https://docs.astral.sh/uv/concepts/python-versions/#managed-python-distributions)로 CPython **3.13.18**을 설치했습니다. OS Python·shell profile·기존 venv는 바꾸지 않았습니다. Python 3.13은 [유지보수 중인 계열](https://devguide.python.org/versions/)입니다.

`/private/tmp/sm-oss-phase4/install`에 OSS Git clone을 만들고 3.13으로 새 `.venv`를 생성했습니다. 기존 site-packages·PYTHONPATH·실제 Job·.env·운영 데이터는 복사하지 않았습니다. 새 venv에서 문서 순서대로 pip/setuptools 업데이트 후 `requirements.txt`를 PyPI에서 신규 설치했습니다. 설치 도구와 런타임 모두 wheel을 사용했고 sdist 빌드는 없었습니다. 테스트 프로세스의 PATH 앞에 임시 관리형 Python bin을 지정해 예제의 `python3 main.py`도 **3.13.18**로 해석되는 것을 확인했습니다. 일반 설치에서도 POSIX Job의 python3는 PATH를 따릅니다. manager venv를 지정하는 것만으로 임의 Job의 Python 버전이 고정되지는 않습니다.

| 검사 | 결과 |
| --- | --- |
| 플랫폼 / 인터프리터 | macOS ARM64 / CPython 3.13.18; manager와 합성 Job 모두 동일 계열 |
| 실제 설치 | pip 26.3, setuptools 84.2.1, ruamel.yaml 0.18.17, ruamel.yaml.clib 0.2.15 (cp313 ARM64 wheel) |
| 무결성 / CLI | pip check 통과; root 및 사용한 하위 명령·Dashboard help 파싱 성공; 초기 list=[] |
| 합성 등록 / 계약 | 새 hello-output ID, schedules=[], required_env/parameters 미선언; 기존 Job 덮어쓰기 없음 |
| 합성 Run / 제출 횟수 | `b6b5741695ff4da9a4d537a8e6a2801b` / 정확히 1회 / succeeded / exit_code=0 |
| stdout / stderr | 합성 레코드 2개 저장 메시지 / 빈 stderr |
| Output | complete=true, alpha/beta 2개; `runtime/job-data/hello-output/output/위_Run_ID/result.json` |
| 조회 | 전체 total=2; Alpha + synthetic + ready total=1; 중복/제외 없음 |
| Run inputs | parameters / parameter_contract_version 필드 없음 (미선언 계약), 추정값 없음 |
| HTML | 저장 Output에서 `reports/hello-output.html` 생성, Dashboard HTML route 읽기 성공 |
| 임시 Dashboard | 프로세스 사전 조회 후 같은 테스트 root·port=0에서만 시작; session root, 저장 Run/결과, HTML·정적 자산 200; 잘못된 Host·CSRF 없는 POST 403 |
| Dashboard 종료 | 직접 시작한 테스트 foreground만 SIGINT로 정상 종료(exit 0); 추가 Run 없음 |
| 선택 검사 | 새 3.13에서 Store 9개 + Dashboard 정적/보안·동일 Run 관찰 2개 = 11개 통과 |

기존 전체 회귀는 반복하지 않았습니다. Phase 2A의 기존 결과는 [validation](validation.md)에, Phase 3의 3.9.6 결과는 아래 원기록에 보존합니다. Phase 3 임시 증거 파일의 SHA-256도 전후 대조했습니다. 코드 최소 버전 **3.9는 그대로**이며 새 설치 권장은 3.13입니다. 3.9의 역사적 호환성 검증은 EOL Python의 보안 지원 약속이 아닙니다. 3.13의 전체 회귀·다른 OS 성공으로 확대 해석하지 않습니다.

로컬 검토 증거는 `/private/tmp/sm-oss-phase4/`의 설치 report, accepted-run, stdout/stderr, results, smoke-summary, 감사 JSON과 Git 검사 요약에 보존합니다. 임시 경로는 영구 보관소가 아니며 Git에 포함하지 않습니다. 원본 프로젝트와 기존 Job·Schedule·운영 데이터는 수정하지 않았습니다. 실제 SSH/OS 예약 적용은 하지 않았습니다.

## 기존 Advisory 6건별 판정

대상은 Phase 3 Python 3.9.6 venv의 pip 26.0.1 / setuptools 82.0.1에서 남았던 **6개의 고유 advisory**입니다. PYSEC/GHSA/CVE는 같은 취약점의 별칭으로 중복 합산하지 않습니다. 영향 범위·수정 버전은 2026-11-13 GitHub Advisory Database와 upstream 수정 자료를 대조했습니다. GitHub 분류는 앞 5건 Moderate, 마지막 1건 Low입니다. 설치 도구는 런타임 `requirements.txt`에 넣지 않았습니다.

| 패키지 / ID | 영향 버전 → 수정 버전 | 사용 조건과 실제 설치 경로 | 처리·잔여 위험 판정 |
| --- | --- | --- | --- |
| pip — PYSEC-2026-196 / [GHSA-wf93-45jw-7689](https://github.com/advisories/GHSA-wf93-45jw-7689) / CVE-2026-8643 | <26.1.2 → 26.1.2 | 악성 wheel의 console/gui entry point 이름이 scripts 경로를 벗어남. wheel 설치 시 관련되는 경로이며 런타임 미사용만으로 제외할 수 없음 | pip 26.3으로 해결. 설치된 `operations/install/wheel.py`의 entry point 경계 검사도 확인. 신뢰할 수 없는 패키지의 코드 실행 위험 자체는 별개 |
| pip — PYSEC-2026-2875 / [GHSA-58qw-9mgm-455v](https://github.com/advisories/GHSA-58qw-9mgm-455v) / CVE-2026-3219 | <=26.0.1 → 26.1 | tar+ZIP 복합 archive 판별 충돌. 이번에는 PyPI의 정상 wheel만 사용하고 sdist 추출 없음; 기존 pip로 악성 archive를 설치할 때 위험 | pip 26.3으로 해결. archive가 안전하다는 일반 보장은 하지 않음 |
| pip — PYSEC-2026-2876 / [GHSA-jp4c-xjxw-mgf9](https://github.com/advisories/GHSA-jp4c-xjxw-mgf9) / CVE-2026-6357 | <26.1 → 26.1 | wheel 설치 뒤 버전 점검의 지연 import가 새 악성 모듈을 불러올 수 있음. 설치 단계의 위험이며 사용자 승인 없는 Job 의존성 자동 설치는 없음 | pip 26.3으로 해결. 이번 정상 wheel 구성에서 공격 모듈을 발견하지 않았으나 임의 wheel의 신뢰를 대신 검증하지는 않음 |
| pip — PYSEC-2026-3721 / [GHSA-qwm4-qh6w-59xr](https://github.com/advisories/GHSA-qwm4-qh6w-59xr) / CVE-2026-13346 | <26.2.0 → 26.2.0 | 악성 index의 이중 인코딩 URL로 경로 혼동. upstream은 악성 package 단독으로는 불충분하고 `pip download --only-binary`에 실질적 영향이 있다고 설명. 이번에는 공식 PyPI install이며 해당 download 명령 없음 | pip 26.3으로 해결. 다른 index·임의 다운로드 작업까지 검증한 것은 아님 |
| setuptools — PYSEC-2026-3447 / [GHSA-h35f-9h28-mq5c](https://github.com/advisories/GHSA-h35f-9h28-mq5c) / CVE-2026-59890 | DB: <83.0.0 → 83.0.0; upstream 페이지: <=82.0.1 / patched None | macOS sdist의 MANIFEST.in NFC/NFD 제외 우회로 비밀 파일 포함 가능. 본 저장소는 pip install . / sdist 배포를 하지 않으며 별도 ZIP Package는 setuptools를 사용하지 않음. 이번 설치도 wheel만 사용 | setuptools 84.2.1로 교체. DB/원문 차이를 숨기지 않음. [공식 수정 dd9f436](https://github.com/pypa/setuptools/commit/dd9f436a36486b4cb8a4c70a2321548b0be09b8f)과 설치된 `egg_info.translate_pattern` 정규화 구현을 대조하고 NFC↔NFD 메모리 매칭 확인 통과. 실제 sdist는 생성하지 않음 |
| setuptools — [GHSA-xmj3-9gf7-h52w](https://github.com/pypa/setuptools/security/advisories/GHSA-xmj3-9gf7-h52w) (CVE/PYSEC 별칭 미제공) | >=38.2.2,<84.1.0 → 84.1.0 | Windows의 legacy `Wheel.install_as_egg()`가 namespace_packages.txt로 고정 내용의 __init__.py를 대상 밖에 만들 수 있음. 이번 macOS/pip wheel 설치·제품 런타임은 해당 경로를 사용하지 않음 | setuptools 84.2.1로 해결. Windows 실제 검증은 수행하지 않았고 지원 완료로 표시하지 않음 |

pip/setuptools는 설치·빌드 도구입니다. `runner/`, `dashboard/`, `deployments/`에서 이들 도구를 import하거나 패키지를 자동 설치하는 경로가 없음을 확인했습니다. 실제 직접/전이 런타임은 ruamel.yaml과 clib입니다. 임의 사용자 Job이 별도로 pip를 호출할 수 있다는 점은 이 감사 범위 밖입니다.

별도 **Python 3.13 감사 venv / pip-audit 2.10.1**에서 실제 제품 venv의 site-packages를 `--path --strict`로 감사했습니다. 결과는 pip 26.3, setuptools 84.2.1, ruamel.yaml 0.18.17, clib 0.2.15 **모두 vulns=[]**, 감사 exit 0입니다. 감사 도구의 자체 의존성을 제품 의존성으로 섞지 않았습니다. 조회에는 공개 패키지 이름·버전만 보내고 비밀·소스는 보내지 않았습니다.

따라서 **새 3.13 환경에서 기존 6건은 모두 처리됐고 실제 사용 경로에 영향을 주는 미해결 고위험 항목은 발견되지 않았습니다.** 기존 3.9 venv는 증거 보존을 위해 그대로이며 취약점이 소급 해결된 것은 아닙니다. 설치·실행 도구의 최신판/DB는 변하므로 다른 설치는 실제 버전·감사를 다시 확인해야 합니다. 알려지지 않은 취약점, Python/OS 전체, 임의 Job, 바이너리 재배포를 인증하는 결론은 아닙니다.

## 보안 제보와 GitHub 현재 상태

로그인한 저장소의 Settings와 Advanced Security를 읽기 전용으로 확인했습니다. 현재 **Private**이며 Dependency graph·Dependabot alerts·security updates·grouped updates는 **Off**, version updates는 dependabot.yml 구성이 필요합니다. 현재 설정에는 Private vulnerability reporting 활성화 항목이 노출되지 않습니다. Security overview는 Security policy Enabled, Code scanning Disabled 및 개인 Private 저장소에 대한 조직용 Advanced Security 제한을 표시했습니다. Private secret scanning/push protection 설정은 노출되지 않았습니다. 정책 파일의 표시는 제보 폼 활성화를 뜻하지 않으며, 코드/비밀 scanning 보호를 제공받고 있다고 주장하지 않습니다. 이번 단계에서 GitHub 설정을 변경하지 않았습니다.

[GitHub 공식 안내](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/configure-for-a-repository)에 따라 **Public 저장소 소유자/admin이 활성화하는 Private vulnerability reporting**을 추가 제보 경로로 준비했습니다. SECURITY.md 추가만으로 활성화되지 않습니다. 최종 정비에서 외부 송수신이 확인된 `security@def-v.com`을 공식 비공개 제보 채널로 등록했습니다. 일반 문의는 `oss@def-v.com`으로 구분합니다. Public 이후에는 Security and quality → Advisories → Report a vulnerability 버튼의 실제 노출을 확인한 뒤 사용합니다.

[SECURITY.md](../SECURITY.md)에 보고 항목, 민감정보 금지, 폼 부재 시 공식 보안 이메일 사용, 소유자의 모니터링·비공개 triage·수정·공동 공개 절차를 기록했습니다. 최신 main을 triage 대상으로 하고 과거 커밋 backport/응답 SLA·고정 응답·수정 기한은 약속하지 않습니다. 담당자는 저장소 소유자이며 이메일 송수신 확인은 완료했습니다. GitHub의 실제 알림 수신·접근 확인은 전환 체크리스트의 필수 항목입니다. Public 직후 활성화 실패 시 안내/홍보·Release를 보류하고 채널 문제를 해결해야 합니다.

## 비밀정보와 Git 이력 최종 점검

### Phase 4 검사 원기록

다음 표와 두 커밋 기준 설명은 이전 Phase 4 검사 당시의 결과입니다. 이번 연락처 정비의 최종 검사는 아래에 구분합니다.

Gitleaks 8.30.1(Phase 3에서 공식 자산 checksum 검증 완료)을 재사용해 전체 redaction, decode 5단계, archive 3단계, allow 주석 무시로 검사했습니다. 추적 파일 트리와 staged diff, 모든 refs의 Git diff 이력, reachable blob/commit 원문을 별도로 검사했습니다. 이는 보안 최종 재검사이며 전체 기능 테스트 재실행이 아닙니다.

| 대상 | 결과 |
| --- | --- |
| 기준 이력 | 2 commits / 84 distinct blobs / 82 unique historical paths; scanner 탐지 0 |
| 최종 후보 트리 / staged diff | 82 tracked files / 탐지 0; 가상환경·감사 JSON·실제 운영 데이터 미포함 |
| 개인 경로 / 인증정보 / 운영 파일 | 실제 사용자 경로·private key·실제 .env/Job/targets/runtime/State/Output 없음. `deployments/targets.example.yaml`의 Linux 계정 경로는 가상 예제 1개로 명시 제외 |
| LICENSE / 제3자 고지 | MIT/genew 보존; 실제 설치된 ruamel.yaml 0.18.17·clib 0.2.15 LICENSE의 MIT·기존 저작권과 THIRD_PARTY_NOTICES 일치. 바이너리/vendor 배포 없음 |
| 문서 | Markdown 상대 링크/anchor 97개·POSIX shell 구문 검사 통과; fenced Runner 명령 40줄·공개 subcommand help 24개 argparse 대조; README·INSTALL·AGENTS 설치 순서/구현 일치 |
| 지원 범위 | macOS ARM64 3.13의 위 범위만 새로 실검증. Windows/Linux 실제 설치·native 예약·실제 SSH/systemd 미검증, Linux 로컬 예약 미지원, 원격 required_env/표준 데이터 경로 제한 유지 |

기준 Git 이력은 OSS 초기화와 Phase 3의 두 커밋이며, 이번 문서 커밋이 그 위에 추가됩니다. 원본 프로젝트 이력을 가져오지 않았습니다. 별도 branch/tag·submodule·LFS 참조는 없습니다. 커밋 메시지·파일명·변경 내용을 검토했고 운영 데이터는 없었습니다. 기존 두 커밋의 author/committer는 동일한 `Jin`과 로컬 Git에 설정된 업무 이메일입니다. 이번 커밋도 기존 identity를 유지합니다. **Public 전환 시 과거 파일/삭제 내용뿐 아니라 author/committer 이메일과 시각도 공개됩니다.** 이것은 제보 이메일의 검증이나 사용 승인이 아닙니다. 이력을 재작성하지 않았고 별도 최종 공개 승인이 이 신원 메타데이터 공개 검토도 포함해야 합니다.

### 이번 연락처 정비의 최종 검사

Gitleaks **8.30.1**을 동일 설정(전체 redaction, decode 5단계, archive 3단계, allow 주석 무시)으로 재사용했습니다. 문서 변경 후 **82개 추적 파일**, 기준 커밋까지 **3 commits / 89 distinct blobs / 82 historical paths**의 전체 refs 이력과 reachable blob/commit 원문에서 탐지 **0건**입니다. 최종 staged diff와 커밋 후 정확한 HEAD의 이력도 푸시 전에 확인하며, 결과와 공개 후보 SHA는 최종 보고에 남깁니다. 보안 검사는 비밀의 완전한 부재를 보증하지 않습니다.

Markdown 상대 링크·anchor **101개**에 깨진 참조가 없고, GitHub 보안 기능 공식 안내 링크 3개도 열리는 것을 확인했습니다. 문서 속 POSIX shell 블록은 구문만 확인했습니다. 이번 diff의 이메일은 공식 두 주소만 허용하며 mailto 대상·표시 주소 일치를 확인합니다. 추적 파일·이력의 개인 경로·private key·금지된 운영 파일 후보는 없고 가상 배포 경로 1개는 기존 합성 예제로 유지합니다. Python 3.13 설치·의존성 감사·전체 기능 테스트·Job 실행·서비스 조작은 반복하지 않았습니다.

기존 3개 커밋의 author/committer는 모두 기존 `Jin` 업무 이메일 identity이며, 이번 커밋도 이를 유지합니다. 공식 연락처 두 주소의 승인·송수신 확인은 Git 신원 이메일의 외부 공개 승인과 별개입니다. 신원 변경이나 이력 재작성 없이 Private에 반영하며, **Public 전 정확한 후보 SHA와 모든 author/committer 이메일의 공개 적합성을 소유자가 최종 확인**해야 합니다. 개인 이메일 주소나 메일 운영 정보는 문서에 추가하지 않습니다.

패턴 검사로 모든 비밀의 부재를 증명할 수는 없습니다. Public 승인 이후 새 커밋이 생기면 해당 정확한 SHA를 다시 감사해야 합니다.

## 차단 항목과 잔여 위험

P0: 즉시 노출/실행 위험, P1: 공개 전 해결 또는 명시적 위험 판단 필요, P2: 제한을 공개하고 후속 관리 가능.

| 등급 | 항목 | 최종 처리 / 공개 판단 |
| --- | --- | --- |
| P1 → 해결 | EOL Python만 검증 / 설치 도구 advisory 6건 | 유지보수 중인 3.13.18 독립 설치·실행, 도구 수정·실제 환경 감사 0건. 최소 Python 변경 없음 |
| P1 → 해결 | 비공개 제보 채널 미확정 | 사용자가 외부 송수신을 확인한 security@def-v.com 등록 완료. PVR은 현재 비활성이며 Public 직후 추가 채널로 활성화·폼·알림 접근 검증 필요 |
| P2 | Python 3.9 과거 환경 | 보존만 하며 새 실사용에는 비권장. 지원 최소 변경은 별도 결정 |
| P2 | Dependabot/scanning 상시 보호 미설정 | 아래 공개 직후 설정·가용성 확인 필요. 로컬 일회 감사를 상시 보호로 오인하지 않기 |
| P2 | Windows/Linux/native/SSH 및 원격 계약 | 미검증·미지원·제한 문구 유지. 후속 기능 작업과 실환경 검증은 별도 승인 |
| P2 | 전이 clib 버전 / 미래 도구 해석 | 실제 설치·라이선스·감사 확인 필요. lock/광범위 CI 정책은 별도 개선 |
| P2 | Git 신원 노출 / single-user trust model | 기존 커밋 메타데이터 노출 고지. Job은 sandbox가 아니며 Dashboard 공개 노출 금지 |

미해결 기술 P0/P1 **0건**, Public 전환 후 즉시 수행할 운영 게이트가 남습니다. 이것은 무조건적인 “이미 공개 운영 가능” 판정이 아닙니다. 채널 활성화를 완료할 담당자/권한/시간이 확보되지 않거나 아래 필수 확인이 실패하면 **공개를 보류**합니다.

## Public 전환 체크리스트

이번 작업은 연락처 문서 정비·최종 보안 검사·Private 저장소 커밋/푸시 범위입니다. Public 전환·Release·Tag 생성은 하지 않습니다. 아래 완료 항목 외에는 별도 승인된 전환 작업에서 실행/확인합니다.

- [x] 공식 일반 문의·보안 제보 이메일 확보, 두 주소의 외부 송수신 확인(사용자 확인), README·CONTRIBUTING·SECURITY 안내 일치.
- [x] 기존 Python 3.13 독립 설치·의존성 감사 결과와 미검증 플랫폼/원격 제한 보존. 전체 기능 테스트·이메일 발송 반복 없음.
- [x] 추적 파일·기준 Git 이력 Gitleaks 탐지 0건, 상대 문서 링크/anchor 101개 오류 0건.
- [ ] 소유자가 정확한 공개 후보 SHA와 전체 Git author/committer 메타데이터 공개를 검토하고 **별도로 Public 전환을 명시 승인**한다. 변경이 추가됐으면 그 SHA를 다시 검사한다.
- [ ] 소유자가 보안 메일함의 지속 모니터링·접근을 확인하고, 소유자/admin의 즉시 작업·triage 가능 시간을 확보한다. Public로 변경한 직후 **Settings → Advanced Security → Private vulnerability reporting → Enable**을 수행하고 Enabled를 확인한다.
- [ ] 비관리자 GitHub 사용자 관점에서 **Security and quality → Advisories → Report a vulnerability** 및 제보 폼이 열리는지 확인한다. 허위 보안 제보는 제출하지 않는다. 소유자의 Watch → Custom → Security alerts(또는 All Activity)와 알림 전달·private report 접근을 확인한다. 실패 시 홍보/Release를 보류한다.
- [ ] SECURITY 정책이 노출되고 Public 활성 상태에 맞는 안내인지 확인한다. 이 전환 절차와 실제 상태가 다른 문구는 갱신한다.
- [ ] Dependency graph와 Dependabot alerts를 활성화/확인하고 requirements.txt의 직접·전이 의존성 탐지를 검토한다. security updates는 활성화하고 PR을 검토한다. pip/setuptools bootstrap은 requirements 밖이므로 별도 환경 감사도 계속 필요하다.
- [ ] [GitHub 기능별 제공 조건](https://docs.github.com/en/code-security/getting-started/github-security-features)에 맞춰 Public secret scanning·repository push protection 상태를 확인하고 가능한 보호를 활성화한다. 자동 활성화를 가정하지 않는다. 소유자 개인 push protection과 repository 보호를 구분한다.
- [ ] Python CodeQL/code scanning 설정 가용성과 분석 범위를 확인하고 활성화를 검토한다. 이번의 수동 검사와 같은 것으로 표시하지 않는다. Dependabot version updates/grouping·CI 범위 확대는 후속 개선으로 결정한다.
- [ ] 모든 필수 게이트가 통과한 뒤 공개 운영 가능 상태를 기록한다. Release/Tag는 이번에 만들지 않으며 별도 요청으로만 진행한다.

---

<details>
<summary>Phase 3 원기록 — 당시 결과 보존 (아래 연락처·차단 판정은 위 최종 정비 현황으로 대체)</summary>

# Phase 3 — 공개 준비 검증

검증일: 2026-11-13 (Asia/Seoul). 대상은 nstgmg/script-manager-oss Private 저장소이며, 시작 커밋은 fc66206f03b80bd2d9f2106c0e1d53afe0664281입니다. 이번 변경은 설치·온보딩·보안·검증 문서에 한정합니다. Runner/배포 엔진은 변경하지 않았습니다. Public 전환·Release·Tag 생성은 별도 승인 사항입니다.

## 독립 설치와 에이전트 워크플로우

macOS ARM64 / Python 3.9.6에서 별도 임시 디렉터리에 Git checkout을 복제하고 새 venv를 만들었습니다. 원본 개발 환경·venv/site-packages/PYTHONPATH·개인 Job·.env·운영 데이터는 복사하지 않았습니다. 소스는 로컬 OSS Git clone이며, 원격 SSH 읽기 인증/동일 main SHA는 별도 git ls-remote로 확인했습니다. HTTPS 대화형 인증이나 다른 에이전트 제품의 실제 세션을 재현한 것은 아닙니다.

선언된 런타임 의존성을 PyPI에서 새로 설치했습니다. Git/Python이 준비되고 저장소 접근 권한이 있다는 전제에서, [INSTALL](../INSTALL.md)의 공통 절차만으로 초기화 → 예제 등록 → 실행 → 결과 확인이 가능했습니다. 특정 에이전트 플러그인·사용자 shell profile·API 키는 필요하지 않았습니다. AGENTS 자동 탐색을 제공하지 않는 도구는 문서를 직접 읽어야 합니다.

| 검사 | 실제 결과 |
| --- | --- |
| 초기 list 및 lazy 초기화 | [] / 새 jobs·runtime 생성 |
| CLI·Dashboard 및 관련 하위 명령 help | 구현과 대조, 파싱 성공 |
| hello-output create 후 소스/README 배치 | 새 ID, schedules=[], required_env/parameters 미선언 |
| 온보딩 합성 Job 제출 횟수 | 정확히 1회 |
| Run | ac5b01101389402387a36449347b2b90 / succeeded / exit_code=0 |
| stdout / stderr | 기대한 2개 합성 레코드 메시지 / 빈 stderr |
| 저장 Output | complete=true, alpha/beta 2개; runtime/job-data/hello-output/output/위_Run_ID/result.json |
| 지원 필터 조회 | Alpha + synthetic + ready: total=1; 전체 total=2 |
| Run parameters / parameter_contract_version | 둘 다 필드 없음 (미선언 Job); 기본값을 추정해 보고하지 않음 |
| HTML | 저장 JSON에서 reports/hello-output.html 생성 |
| 의존성 무결성 | pip check 통과 |
| 임시 Dashboard | --port 0, 동일 임시 root; session root·기존 Run·저장 결과·HTML·정적 파일 조회 통과 |
| Dashboard 경계/종료 | 잘못된 Host 및 CSRF 없는 POST 거부; foreground SIGINT(Ctrl+C) 종료 코드 0 |
| 영향 범위 기존 테스트 | Store 9개 + Dashboard 정적/보안·동일 Run 관찰 2개 = 11개 통과 |
| 전체 회귀 | 이번에는 반복하지 않음; 기존 Phase 2A 기록은 [validation](validation.md) 참조 |

임시 Dashboard는 이번에 명시적으로 요청한 기본 검증의 범위에서만 시작·종료했습니다. Dashboard를 통해 추가 Job을 제출하지 않았습니다. 실제 Job·예약 등록·외부 업무 API·SSH 배포·기존 서비스 제어는 수행하지 않았습니다. 합성 검증 디렉터리는 검토를 위해 남겼고 운영 데이터로 가져오지 않습니다.

온보딩 Job 실행 뒤 설치 도구 취약점이 발견되어 같은 venv의 pip/setuptools를 업데이트하고 감사/pip check만 다시 수행했습니다. 독립 설치나 합성 Job을 두 번째로 실행하지 않았습니다. 최종 INSTALL은 업데이트를 의존성 설치 앞에 배치합니다. 문서의 최종 순서 전체를 두 번째로 재실행했다는 뜻은 아닙니다.

## 의존성·Python 보안 검사

pip-audit 2.9.0을 별도 감사 venv에 설치하고, 실제 런타임 freeze 두 개를 --no-deps --disable-pip로 감사했습니다. 전체 설치 환경은 --path로 별도 감사해 설치 도구도 포함했습니다. 프로젝트 소스/자격증명을 서비스에 보내지 않았으며 공개 패키지 이름/버전만 조회했습니다.

| 범위 | 버전 | 알려진 advisory |
| --- | --- | --- |
| 런타임 ruamel.yaml | 0.18.17 | 0 |
| 런타임 ruamel.yaml.clib | 0.2.15 | 0 |
| 초기 venv 도구 | pip 21.2.4 / setuptools 58.0.4 | 총 12 |
| 같은 venv 업데이트 후 도구 | pip 26.0.1 / setuptools 82.0.1 | 총 6 (미해결) |

업데이트 후 남은 감사 결과는 아래와 같습니다. 수정 버전은 감사 DB가 반환한 정보이며 이 환경에서 설치/검증한 버전이 아닙니다.

| 패키지 | Advisory | 감사 DB 수정 버전 |
| --- | --- | --- |
| pip | PYSEC-2026-196 / GHSA-wf93-45jw-7689 | 26.1.2 |
| pip | PYSEC-2026-2875 / GHSA-58qw-9mgm-455v | 26.1 |
| pip | PYSEC-2026-2876 / GHSA-jp4c-xjxw-mgf9 | 26.1 |
| pip | PYSEC-2026-3721 / GHSA-qwm4-qh6w-59xr | 26.2 |
| setuptools | PYSEC-2026-3447 / GHSA-h35f-9h28-mq5c | 83.0.0 |
| setuptools | GHSA-xmj3-9gf7-h52w | 84.1.0 |

이는 manager의 두 런타임 라이브러리에서 검출된 취약점은 아닙니다. 주로 패키지 설치/경로 처리 및 sdist 작성 조건의 위험이며, pip-audit의 검출을 임의로 무시하거나 해당 경로가 안전하다고 결론내리지 않았습니다. 일부 upstream advisory 페이지와 감사 DB의 수정 정보가 다를 수 있으므로 유지보수자가 개별 검토해야 합니다. 확인한 [setuptools 원문](https://github.com/pypa/setuptools/security/advisories/GHSA-h35f-9h28-mq5c)은 macOS sdist 제외 우회와 영향을 설명합니다. 로컬에서 sdist를 만들거나 악성 패키지를 실행하는 재현은 하지 않았습니다.

Python 3.9는 [공식 유지보수 종료 버전](https://devguide.python.org/versions/)입니다. 설치 도구 업데이트도 이 Python의 호환 범위에 제한됩니다. 유지보수 중인 Python으로 동일 설치/감사를 확인하고 남은 advisory를 해결하거나 범위·근거·책임자를 포함한 명시적 위험 결정을 해야 합니다. 기존 호스트 Python을 바꾸거나 두 번째 설치를 시작하지 않았습니다.

감사 도구는 호스트 LibreSSL 2.8.3에 대한 urllib3 경고를 냈지만 조회와 JSON 결과 반환은 완료했습니다. 이 경고를 제품 런타임 경고로 혼동하지 않습니다. Advisory 감사는 탐지 시점에 알려진 항목만 검사하며 Python/OS 전체 보안 인증이 아닙니다. ruamel.yaml.clib는 하한만 지정되어 있어 다른 설치의 전이 버전/라이선스/감사 결과가 달라질 수 있습니다.

## GitHub Private 보안 기능 확인

GitHub 로그인 UI의 Security overview와 Settings → Advanced Security를 읽기 전용으로 확인했습니다. 보안 기능을 켜거나 과금/권한/공개 범위를 바꾸지 않았습니다.

| 기능 | 이 저장소에서 관찰한 상태 / 의미 |
| --- | --- |
| 저장소 visibility | Private |
| Security policy | Enabled (SECURITY.md 표시); 제보 수신 경로 확정을 뜻하지 않음 |
| Dependency graph | 사용 가능한 checkbox, 꺼짐 |
| Dependabot alerts | 사용 가능, Disabled |
| Dependabot security updates / grouped updates | 꺼짐 |
| Dependabot version updates | dependabot.yml 구성 필요, 이번에 생성하지 않음 |
| Code scanning | Disabled; “Advanced Security is only available for Organizations” 표시 |
| Private secret scanning / repository push protection | 설정에 노출되지 않음; 이 개인 소유 Private 저장소에서 보호된다고 주장하지 않음 |
| Private vulnerability reporting | 현재 Private에서 사용할 제보 폼으로 간주하지 않음; Public 저장소에서 별도 활성화하는 기능 |

[GitHub 기능 안내](https://docs.github.com/en/code-security/getting-started/github-security-features)는 Dependency graph/Dependabot와 계정·제품 조건이 있는 추가 보호를 구분합니다. [비공개 제보 안내](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/report-privately)는 Public 저장소 소유자/관리자가 private vulnerability reporting을 활성화할 수 있다고 설명합니다. SECURITY.md 파일을 추가해도 제보 폼은 자동 활성화되지 않습니다.

Public 전 확인할 선택은 검증된 비공개 연락처를 먼저 마련하는 방법, 별도 Public 전환 승인 후 GitHub 제보를 즉시 활성화하는 절차를 준비하는 방법 등입니다. 어느 방법도 이번 작업에서 결정·실행하지 않았습니다. 메일 주소·SLA·활성 제보 링크를 임의로 만들지 않았습니다. 공개 시점에 실제로 도달 가능한 비공개 채널과 명확한 문서가 있어야 합니다.

## 비밀·개인 경로·라이선스·문서

Gitleaks 8.30.1 공식 macOS ARM64 아카이브의 SHA-256을 [공식 자산 목록](https://github.com/gitleaks/gitleaks/releases/expanded_assets/v8.30.1)과 대조했습니다. 전체 redaction, decoding 5단계, archive 3단계로 배포 파일 트리 82개 및 기존 Git 이력을 검사해 탐지 0개를 확인했습니다. 별도 ZIP 안에 생성한 합성 canary는 탐지되어 scanner/archive 경로의 동작도 확인했습니다. 커밋 직전 최종 트리와 staged diff도 같은 설정으로 검사합니다. 상세 탐지 값/토큰은 보고서나 공개 문서에 넣지 않습니다.

Markdown 상대 링크/anchor 93개 검사에서 기존 Dashboard Skill → CLI의 깨진 anchor 1개를 발견해 해당 CLI 제목을 복원했으며, 최종 깨진 링크는 0개입니다. README/INSTALL/AGENTS 상호 참조, 문서 fenced Runner 명령 40줄과 공개 하위 명령 help 24개를 argparse에 대조하고 POSIX shell 구문을 검사했습니다. Dashboard 인자는 실제 구현/help와 시작/종료 검사로 대조했습니다. POSIX 명령은 실제 macOS에서 확인하며 Windows 명령은 구현·정적 경로 대조만 수행합니다. 이것을 실제 Windows 성공으로 보고하지 않습니다.

LICENSE의 MIT/genew 고지를 보존했습니다. 설치한 ruamel.yaml 0.18.17 / clib 0.2.15의 실제 LICENSE는 THIRD_PARTY_NOTICES.md의 MIT·저작권 기재와 일치합니다. hello-output은 원본 합성 예제이며 비밀/파라미터/예약/네트워크 호출이 없습니다. 파일 목록·개인 경로·private-key 표식 검사에서 실제 개인 경로나 인증정보는 발견하지 않았습니다. 경로 후보 1개(deployments/targets.example.yaml의 가상 Linux 계정 경로)는 합성 배포 예제로 확인해 제외했습니다. 실제 .env·Job·targets·runtime·실행 기록·산출물은 배포 파일에서 제외합니다. 검사 도구/venv/감사 JSON은 저장소에 추가하지 않습니다. 패턴 검사만으로 모든 비밀·취약점의 부재를 보증하지 않습니다.

## 발견 사항과 Public 전 필수 조치

P0는 즉시 데이터 노출/실행 위험, P1은 공개 전 해결 또는 명시적 판단이 필요한 문제, P2는 공개 주장을 제한하면 관리할 수 있는 항목으로 사용합니다.

| 우선순위 | 문제 | Public 차단 | 필요한 조치 |
| --- | --- | --- | --- |
| P1 | 검증된 비공개 보안 제보 수신 채널 미확정 | 예 | 유지보수자가 채널·접근·안내와 응답 방침을 확정하고 SECURITY.md 갱신 |
| P1 | 검증 Python 3.9 EOL / 업데이트 후 설치 도구 advisory 6개 | 예, 해결 또는 명시적 위험 판단 전 | 유지보수 중인 Python에서 설치/감사 확인, 개별 취약점 처리·지원 기준 결정 |
| P2 | Dependency graph/Dependabot 꺼짐 | 단독 필수 차단 아님 | 사용자가 활성화 여부 결정; 로컬 감사를 GitHub 상시 탐지로 오인하지 않기 |
| P2 | Windows/Linux 실제 설치·native 예약·실제 SSH 미검증 | 검증 완료라고 홍보하면 차단 | 현재 미검증/미지원 표기 유지, 필요시 별도 승인된 환경 검증 |
| P2 | 원격 required_env 실패·로컬 데이터 계약과 차이 | 원격 동등 지원을 주장하면 차단 | 제한 유지; 엔진 확장은 별도 작업 |
| P2 | 전이 의존성 clib 하한만 지정 | 단독 필수 차단 아님 | 다른 배포 환경에서 실제 버전/라이선스/감사 확인; lock 정책은 별도 결정 |

설치·합성 실행·기본 조회는 재현됐습니다. 공개 준비 완료를 Public 전환 승인으로 해석하지 않습니다. 제보 채널과 보안 기준을 결정하고 당시 최종 커밋 재검사 후 별도 Public 승인을 받아야 합니다.

</details>

</details>
