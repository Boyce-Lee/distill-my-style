#!/usr/bin/env python3
"""Read and atomically maintain the user's personal-style binding."""

import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile


RECORD = Path.home() / ".distill-my-style" / "target.json"


def validate_record(target):
    if not isinstance(target, dict) or set(target) != {"name", "path"}:
        raise ValueError("Binding must contain exactly name and path.")
    name, path = target["name"], target["path"]
    if (not isinstance(name, str) or not 1 <= len(name) <= 64
            or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name)):
        raise ValueError("Invalid Skill name.")
    if (not isinstance(path, str) or not Path(path).is_absolute()
            or Path(path).name != "SKILL.md"):
        raise ValueError("Binding path must be an absolute path to SKILL.md.")
    return target


def validate_target(target):
    path = Path(target["path"])
    if not path.is_file():
        raise ValueError("Bound SKILL.md is missing or is not a file.")
    content = path.read_text(encoding="utf-8")
    frontmatter = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", content, re.S)
    if not frontmatter:
        raise ValueError("Target has no YAML frontmatter.")
    names = re.findall(r"^name:[ \t]*(.*)$", frontmatter[1], re.M)
    if len(names) != 1:
        raise ValueError("Target must declare one name in frontmatter.")
    # shortcut: single-line plain or quoted YAML names only; use a YAML parser if broader syntax is needed.
    name = re.fullmatch(r'''(?:([a-z0-9-]+)|"([a-z0-9-]+)"|'([a-z0-9-]+)')(?:[ \t]+\#.*)?''', names[0].strip())
    if not name or next(value for value in name.groups() if value is not None) != target["name"]:
        raise ValueError("Target frontmatter name does not match the binding.")


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Binding contains duplicate JSON keys.")
        result[key] = value
    return result


def read_record():
    try:
        content = RECORD.read_text(encoding="utf-8")
    except FileNotFoundError:
        if RECORD.is_symlink():
            raise ValueError("Binding record is a broken symlink.")
        return None
    return validate_record(json.loads(content, object_pairs_hook=unique_keys))


def write_record(target, expected, create):
    validate_target(target)
    RECORD.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = RECORD.with_name("target.lock")
    try:
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise ValueError("Another binding write holds target.lock; do not remove it automatically.")
    os.close(descriptor)
    temporary = None
    try:
        current = read_record()
        if create and current is not None:
            raise ValueError("Binding already exists; read it before proposing an update.")
        if not create and (current is None or current != expected):
            raise ValueError("Binding changed or is missing; read it again before updating.")
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=RECORD.parent, delete=False) as file:
            temporary = Path(file.name)
            json.dump(target, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, RECORD)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        lock.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("read")
    for command in ("create", "update"):
        operation = commands.add_parser(command)
        operation.add_argument("--name", required=True)
        operation.add_argument("--path", required=True)
        if command == "update":
            operation.add_argument("--expected-name", required=True)
            operation.add_argument("--expected-path", required=True)
    args = parser.parse_args(argv)
    result = {"record": str(RECORD)}
    try:
        if args.command == "read":
            target = read_record()
            result["target"] = target
            if target is not None:
                validate_target(target)
            result["status"] = "bound" if target is not None else "unbound"
        else:
            path = Path(args.path).expanduser()
            if not path.is_absolute():
                raise ValueError("Use an absolute target path, not a working-directory-relative path.")
            target = validate_record({"name": args.name, "path": str(path.resolve())})
            expected = None
            if args.command == "update":
                expected = validate_record({"name": args.expected_name, "path": args.expected_path})
            write_record(target, expected, args.command == "create")
            result.update(status="bound", target=target)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError) as error:
        result.update(status="error", error=str(error))
        print(json.dumps(result, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
