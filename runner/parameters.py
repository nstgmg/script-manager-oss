"""Version 1 public, non-secret run inputs. No shell interpolation or business logic."""
from collections.abc import Mapping
from datetime import date
import json
import math
import re

from runner.common import ManagerError

CONTRACT_VERSION = 1
TYPES = {"string", "integer", "number", "boolean", "date"}
FIELDS = {"type", "description", "required", "default", "choices", "min", "max", "cli"}
SECRET_NAME = re.compile(r"(?:^|[_-])(?:password|passwd|secret|token|credential|credentials|api[_-]?key|private[_-]?key)(?:$|[_-])", re.I)


def fail(name, reason):
    # Deliberately never echo supplied values (including malformed credentials).
    raise ManagerError("파라미터 " + name + ": " + reason)


def scalar(name, spec, value):
    kind = spec["type"]
    valid = (isinstance(value, str) if kind in ("string", "date") else
             type(value) is bool if kind == "boolean" else
             type(value) is int if kind == "integer" else
             type(value) in (int, float))
    if not valid:
        fail(name, kind + " 타입이 필요합니다.")
    if isinstance(value, str):
        if len(value) > 4096 or "\x00" in value:
            fail(name, "문자열은 NUL 없이 4096자 이하여야 합니다.")
        if kind == "date":
            try:
                if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
                    raise ValueError()
                date.fromisoformat(value)
            except ValueError:
                fail(name, "유효한 YYYY-MM-DD 날짜가 필요합니다.")
    elif kind in ("integer", "number") and (abs(value) > 9007199254740991 or
                                               not math.isfinite(value)):
        fail(name, "유한한 숫자이며 절댓값은 9007199254740991 이하여야 합니다.")
    return value


def checked(name, spec, value):
    scalar(name, spec, value)
    if "choices" in spec and value not in spec["choices"]:
        fail(name, "허용값에 포함되지 않습니다.")
    if ("min" in spec and value < spec["min"]) or ("max" in spec and value > spec["max"]):
        fail(name, "허용 범위를 벗어났습니다.")
    if spec.get("required") and value == "":
        fail(name, "필수 문자열은 비어 있을 수 없습니다.")
    return value


def validate_contract(config):
    definitions = config.get("parameters", {})
    if not isinstance(definitions, Mapping) or len(definitions) > 64:
        raise ManagerError("parameters는 최대 64개의 이름별 정의 객체여야 합니다.")
    reserved = {s.lower().replace("-", "_") for s in config.get("required_env", [])}
    options = set()
    for name, spec in definitions.items():
        if (not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]{0,62}", name)
                or SECRET_NAME.search(name) or name.lower().replace("-", "_") in reserved
                or name.upper().startswith("SCRIPT_MANAGER_")):
            raise ManagerError("파라미터 이름이 잘못되었거나 자격증명용 이름입니다. 비밀정보는 required_env를 사용하세요.")
        if not isinstance(spec, Mapping) or set(spec) - FIELDS:
            fail(name, "지원하지 않는 정의 필드입니다. 비밀정보는 required_env를 사용하세요.")
        if not isinstance(spec.get("type"), str) or spec["type"] not in TYPES:
            fail(name, "지원하지 않는 타입입니다.")
        if not isinstance(spec.get("description", ""), str) or len(spec.get("description", "")) > 2000:
            fail(name, "설명은 2000자 이하 문자열이어야 합니다.")
        if type(spec.get("required", False)) is not bool:
            fail(name, "required는 boolean이어야 합니다.")
        if any(key in spec for key in ("min", "max")):
            if spec["type"] not in ("integer", "number", "date"):
                fail(name, "범위는 숫자 또는 날짜에만 지정할 수 있습니다.")
            for key in ("min", "max"):
                if key in spec:
                    scalar(name, spec, spec[key])
            if "min" in spec and "max" in spec and spec["min"] > spec["max"]:
                fail(name, "min은 max 이하여야 합니다.")
        if "choices" in spec:
            choices = spec["choices"]
            if not isinstance(choices, list) or not 1 <= len(choices) <= 100:
                fail(name, "choices는 1~100개 배열이어야 합니다.")
            for i, value in enumerate(choices):
                scalar(name, spec, value)
                if value in choices[:i]:
                    fail(name, "choices에 중복이 있습니다.")
                checked(name, spec, value)
        if "default" in spec:
            checked(name, spec, spec["default"])
        if "cli" in spec:
            cli = spec["cli"]
            if (not isinstance(cli, Mapping) or set(cli) - {"option", "mode"}
                    or not isinstance(cli.get("option"), str)
                    or not re.fullmatch(r"--[a-zA-Z][a-zA-Z0-9-]*", cli["option"])
                    or cli.get("mode", "value") not in ("value", "flag")
                    or cli.get("mode") == "flag" and spec["type"] != "boolean"):
                fail(name, "cli에는 --long-option과 value 또는 boolean flag 모드가 필요합니다.")
            if cli["option"] in options:
                fail(name, "CLI 옵션은 중복될 수 없습니다.")
            options.add(cli["option"])
    return definitions


def resolve_parameters(config, supplied=None):
    definitions = validate_contract(config)
    supplied = {} if supplied is None else supplied
    if not isinstance(supplied, Mapping):
        raise ManagerError("parameters는 JSON 객체여야 합니다.")
    if any(name not in definitions for name in supplied):
        raise ManagerError("선언되지 않은 실행 파라미터입니다.")
    applied = {}
    for name, spec in definitions.items():
        if name in supplied:
            applied[name] = checked(name, spec, supplied[name])
        elif "default" in spec:
            applied[name] = spec["default"]
        elif spec.get("required"):
            fail(name, "필수 입력이 누락되었습니다.")
    if len(encode_parameters(applied).encode("utf-8")) > 32768:
        raise ManagerError("실행 파라미터는 JSON 32 KiB 이하여야 합니다.")
    return applied


def encode_parameters(applied):
    return json.dumps(applied, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def parameter_command(config, applied):
    command = list(config["command"])
    for name, spec in config.get("parameters", {}).items():
        if name not in applied or "cli" not in spec:
            continue
        value, cli = applied[name], spec["cli"]
        if cli.get("mode") == "flag":
            if value:
                command.append(cli["option"])
        else:
            text = value if isinstance(value, str) else json.dumps(value, allow_nan=False)
            # Equals keeps leading '-' values from becoming another option.
            command.append(cli["option"] + "=" + text)
    return command


def parse_cli_parameters(text, label="--parameters"):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError()
            value[key] = item
        return value
    try:
        value = json.loads(text, object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, TypeError, RecursionError):
        raise ManagerError(label + "에는 중복 키 없는 유효한 JSON 객체가 필요합니다.") from None
    if not isinstance(value, dict):
        raise ManagerError(label + "에는 JSON 객체가 필요합니다.")
    return value
