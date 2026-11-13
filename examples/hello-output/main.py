# SPDX-License-Identifier: MIT
# Copyright (c) 2026 genew
"""Original offline example: two synthetic records, one atomic Output JSON."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile


def main():
    output_value = os.environ.get("SCRIPT_MANAGER_OUTPUT_DIR")
    if not output_value:
        raise SystemExit("SCRIPT_MANAGER_OUTPUT_DIR is required; execute through Script Manager")
    output = Path(output_value)
    if not output.is_absolute() or not output.is_dir():
        raise SystemExit("Managed Output must be an existing absolute directory")
    collected = datetime.now(timezone.utc).isoformat()
    records = [
        {"id": "alpha", "title": "Alpha example", "source": "synthetic", "status": "ready", "value": 1},
        {"id": "beta", "title": "Beta example", "source": "synthetic", "status": "ready", "value": 2},
    ]
    document = {"generated_at": collected, "collected_at": collected,
                "complete": True, "records": records}
    assert len(records) == 2 and len({row["id"] for row in records}) == 2
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output,
                                         prefix=".result-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(document, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        parsed = json.loads(temporary.read_text(encoding="utf-8"))
        if not parsed["complete"] or len(parsed["records"]) != 2:
            raise ValueError("Unexpected synthetic result")
        os.replace(temporary, output / "result.json")
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print("Hello Output: wrote 2 synthetic records to result.json")


if __name__ == "__main__":
    main()
