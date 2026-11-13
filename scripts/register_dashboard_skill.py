"""Register only the project-local Dashboard Skill. Never replace a destination."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys


SKILL = Path(".agents/skills/sm-dashboard")
SOURCE_FILE = "script-manager-source.json"


def tree_contents(folder):
    contents = {}
    for item in folder.rglob("*"):
        relative = item.relative_to(folder).as_posix()
        if relative == SOURCE_FILE:
            continue
        if item.is_symlink():
            raise ValueError("Copied Skill contains a symlink; preserve it for manual review.")
        contents[relative] = None if item.is_dir() else item.read_bytes()
    return contents


def register(repository, project, check=False):
    if not Path(project).is_absolute():
        raise ValueError("Provide the confirmed absolute project root.")
    repository = Path(repository).resolve(strict=True)
    project = Path(project).resolve(strict=True)
    if not project.is_dir() or project == Path.home().resolve() or project == Path(project.anchor):
        raise ValueError("Use an explicit project directory, never a home or filesystem root.")
    if project != repository and project not in repository.parents:
        raise ValueError("The repository must be inside the confirmed project root.")
    # Do not let a symlinked .agents/skills redirect writes outside this project.
    for parent in (project / ".agents", project / ".agents/skills"):
        resolved = parent.resolve()
        if resolved != project and project not in resolved.parents:
            raise ValueError("Skill parent resolves outside the project; no registration performed.")
    source = repository / SKILL
    if not (source / "SKILL.md").is_file() or not (source / "agents/openai.yaml").is_file():
        raise ValueError("The repository Dashboard Skill or invocation policy is missing.")
    target = project / SKILL
    metadata = {"repository_root": str(repository)}
    mode = "copy" if sys.platform == "win32" else "symlink"
    if target == source:
        mode = "repository"
    elif target.is_symlink():
        if target.resolve() != source.resolve() or not target.is_dir():
            raise ValueError("Existing Skill link conflicts or is broken; left unchanged.")
        mode = "symlink"
    elif target.exists():
        marker = target / SOURCE_FILE
        if (not marker.is_file() or json.loads(marker.read_text(encoding="utf-8")) != metadata
                or tree_contents(target) != tree_contents(source)):
            raise ValueError("Existing Skill differs or is unmanaged; left unchanged. Review manually.")
        mode = "copy"
    elif check:
        raise ValueError("Project Skill is not registered.")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        if mode == "symlink":
            target.symlink_to(os.path.relpath(source, target.parent), target_is_directory=True)
        else:
            # copytree rejects an existing destination, including concurrent installs.
            shutil.copytree(source, target)
            with (target / SOURCE_FILE).open("x", encoding="utf-8") as handle:
                json.dump(metadata, handle, ensure_ascii=False, indent=2)
    return {"mode": mode, "repository_root": str(repository), "project_root": str(project),
            "skill_path": str(target), "source_path": str(source), "verified": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True,
                        help="Confirmed agent project root; never inferred from cwd or git")
    parser.add_argument("--check", action="store_true", help="Verify only; do not write")
    args = parser.parse_args()
    try:
        result = register(Path(__file__).resolve().parents[1], args.project_root, args.check)
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
