# 공통 실행 파라미터 (계약 v1)

`job.yaml`의 선택적 `parameters`는 스크립트가 실제 지원하는 비밀 아닌 입력만 선언한다. 업무 필터의 의미나 출처·기간 계산은 스크립트 책임이다. 기존 Job은 수정할 필요가 없다. 선언 변경도 기존 YAML/etag 저장 경로를 사용한다.

```yaml
parameters:
  keyword:
    type: string
    description: 검색할 공개 키워드
    required: true
    cli: {option: --keyword}
  count:
    type: integer
    default: 10
    min: 1
    max: 100
    cli: {option: --count}
  day:
    type: date
    description: 처리 기준일
    min: '2026-01-01'
    max: '2026-12-31'
  source:
    type: string
    choices: [one, two]
    default: one
  verbose:
    type: boolean
    default: false
    cli: {option: --verbose, mode: flag}
```

위 예시는 가상의 계약이다. 실제 Job이 지원하는 입력만 선언한다.

## 정의와 검증

- 이름별 객체. 이름은 영문자로 시작하고 영문자·숫자·`_`·`-`를 포함하는 최대 63자, 최대 64개다. `type`은 필수이며 `string`, `integer`, `number`, `boolean`, `date`를 지원한다.
- `description`은 선택적 설명(최대 2000자), `required`는 기본 false다. `default`가 있으면 생략 시 사용하며 필수 조건도 충족한다. 기본값 없는 선택 입력은 적용값 객체에서 생략한다. `null`은 지원하지 않는다. 필수 문자열은 빈 문자열을 거부하며 boolean false와 숫자 0은 유효한 값이다.
- `choices`는 동일 타입의 중복 없는 1~100개 허용값이다. `min`/`max`는 숫자와 날짜의 양끝 포함 범위다. 기본값·허용값·경계 자체도 선언 저장 시 검증한다.
- JSON 타입을 강제한다. `"3"`은 integer가 아니며 true는 1이 아니다. 숫자는 유한하고 절댓값이 9007199254740991 이하여야 한다. 정수는 JSON 정수 표기를 사용한다. 날짜는 따옴표로 감싼 유효한 `YYYY-MM-DD` 문자열이다. 날짜의 상대 표현을 Runner가 계산하지 않는다.
- 문자열은 NUL 없이 4096자 이하, 적용값 JSON은 UTF-8 32 KiB 이하다. 미선언 입력, 잘못된 값, 미지원 정의 필드는 실행 전에 거부한다. 검증 오류에 입력값을 반영하지 않는다.
- `secret` 타입/속성은 없다. password/token/secret/api_key/private_key 등 일반 자격증명 이름, `required_env`와 같은 이름, `SCRIPT_MANAGER_*`는 파라미터로 선언할 수 없다. 이는 보조 방어이며 임의의 문자열이 비밀인지 자동 판별하는 기능은 아니다. 비밀 값은 root `.env`와 `required_env`를 사용한다. 일반 파라미터는 기록·표시되는 공개 입력이다.

## 스크립트 전달

선언된 Job에는 검증된 적용값 전체를 `SCRIPT_MANAGER_PARAMETERS` JSON 환경변수로 전달한다. 스크립트는 예를 들어 `json.loads(os.environ['SCRIPT_MANAGER_PARAMETERS'])`로 읽는다. 이 변수는 Runner가 설정하며 사용자 정의 `env`보다 우선한다. 파라미터 없는 Job에는 새 환경변수를 주입하지 않는다.

기존 CLI 스크립트는 지원하는 입력에만 `cli`를 선언한다.

- 기본 `mode: value`는 기존 command argv 뒤에 `--option=value` 한 원소를 추가한다. boolean은 `true`/`false`, 숫자는 JSON 표기다. 값 안의 공백·셸 문자·선행 하이픈을 그대로 전달하며 셸 평가나 템플릿 치환을 하지 않는다.
- `mode: flag`는 boolean 전용으로 true일 때만 `--option`을 추가한다. false 또는 생략이면 추가하지 않는다. 고정 command에 이미 있는 flag를 제거하는 기능은 없으므로 중복·충돌하는 고정 인자를 선언하지 않는다.
- 옵션은 `--long-option` 형식이며 Job 내에서 중복할 수 없다. 위치 인자, 짧은 옵션, 환경변수 이름별 매핑은 v1에서 지원하지 않는다. `--option=value`를 지원하지 않는 기존 스크립트는 JSON 입력을 읽도록 별도 수정해야 한다. 기존 스크립트를 자동으로 추론하거나 변경하지 않는다.

## 실행·발견

```sh
.venv/bin/python -m runner get JOB_ID
.venv/bin/python -m runner run JOB_ID --wait --parameters '{"keyword":"공개 키워드","count":3}'
.venv/bin/python -m runner run-dashboard JOB_ID --parameters '{"keyword":"공개 키워드","count":3}'
```

기본 실행은 `run`입니다. `run-dashboard`는 승인된 접근이 있는 기존 서비스가 필요한 환경에서만 사용하며 서비스를 시작하지 않습니다. 서비스 시작은 사용자의 명시적 요청이 있어야 합니다. [CLI 안내](cli.md) 참조.

`get` 및 `GET /api/jobs/{id}`의 `config.parameters`가 발견 인터페이스다. HTTP는 기존 session/Host/Origin/CSRF 검사 아래 `POST /api/jobs/{id}/runs`에 `{"parameters":{...}}`를 보낸다. 빈 본문/`{}`는 기본값만 적용하며 기존 무파라미터 실행과 호환된다. `parameters: null`은 HTTP에서 거부한다. CLI와 HTTP 실행 JSON은 중복 키와 NaN/Infinity 표기도 거부한다.

`run-dashboard`는 발견한 계약으로 선검증하고 서버도 동일 모듈로 검증한다. 결과에는 실제 적용값을 반환한다. `--keyword`/`--source`/`--status`는 실행 후 저장 결과 조회 조건으로 기존 의미를 유지한다. 대기 제한이나 관찰 실패 후에는 `--run RUN_ID`로 재개하며 `--parameters`를 함께 사용할 수 없다.

Dashboard는 선언된 Job의 실행 버튼에서만 타입별 입력 폼을 연다. 선택 입력의 '입력값 지정'을 해제하면 기본값을 사용하거나 생략한다. 체크박스 false와 미지정은 구분된다. 서버가 모든 값과 범위를 최종 검증하며 입력 오류는 폼 안에 표시한다. 파라미터 없는 Job의 실행 흐름은 유지된다.

## 실행 이력과 호환성

파라미터가 있는 Run은 `parameters`(실제 적용값), `parameter_contract_version: 1`, `resolved_command`를 저장한다. 기존 `config`, `config_etag`, source/job.yaml 및 manifest가 당시 계약을 보존하므로 나중에 Job 정의가 바뀌어도 이력을 해석할 수 있다. worker는 저장된 값과 argv를 사용한다. 최신 Job을 다시 읽어 입력을 재계산하지 않는다. Dashboard의 실행 상세도 Run에 저장된 계약과 적용값을 표시한다.

파라미터 없는 Run은 기존 메타데이터·명령·환경을 유지하며 과거 기록에 새 필드를 요구하지 않는다. Job YAML 기본값, Schedule, Output/State/Workspace는 실행 입력으로 수정하지 않는다. 기존 lock·timeout·취소·로그·자격증명 preflight를 유지한다. 입력 검증 실패 시 worker와 Run/Output을 만들지 않는다.

Schedule의 별도 입력 오버라이드는 v1 범위 밖이다. 기존 Schedule 호출은 기본값만 사용하며 기본값 없는 필수 입력이 있으면 실행 전에 실패한다. 활성 예약을 자동 변경하거나 초기화하지 않는다. 새 Package에는 공통 파라미터 모듈도 포함되며 원격 예약 실행도 같은 기본값/검증/전달 규칙을 따른다. 기존 immutable Package는 그대로 유지된다. 원격 required_env와 표준 데이터 경로 차이는 [Package 제한](packages.md)을 확인한다.
