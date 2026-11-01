#!/usr/bin/env python3
"""Validate a personal-style Skill's format and implicit-invocation settings."""

import argparse
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

try:
    import yaml
except ImportError:
    sys.exit("PyYAML is required. Install this Skill's requirements.txt with your Python interpreter.")


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if not isinstance(key, str) or key in result:
            raise ValueError("YAML mapping keys must be unique strings.")
        result[key] = loader.construct_object(value_node)
    return result


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)

COMMON_FIELDS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
INVOCATION_FIELDS = {"disable-model-invocation", "user-invocable"}


def validate_style(source):
    source = Path(source).expanduser().resolve()
    path = source / "SKILL.md" if source.is_dir() else source
    errors = []
    if path.name != "SKILL.md":
        errors.append("The entrypoint filename must be SKILL.md.")
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        return [str(error)]
    match = re.match(r"\A---\n(.*?)\n---(?:\n|$)", content, re.S)
    if not match:
        return errors + ["SKILL.md must start with YAML frontmatter delimited by ---."]
    try:
        metadata = yaml.load(match[1], Loader=UniqueKeyLoader)
    except (yaml.YAMLError, ValueError) as error:
        return errors + ["Invalid frontmatter: " + str(error)]
    if not isinstance(metadata, dict):
        return errors + ["Frontmatter must be a mapping."]
    unknown = metadata.keys() - COMMON_FIELDS - INVOCATION_FIELDS
    if unknown:
        errors.append("Unsupported frontmatter fields: " + ", ".join(sorted(unknown)))
    name = metadata.get("name")
    if not isinstance(name, str) or not 1 <= len(name) <= 64 or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        errors.append("name must be 1-64 lowercase letters, digits or single hyphens.")
    elif name != path.parent.name:
        errors.append("name must match the Skill directory name.")
    description = metadata.get("description")
    if not isinstance(description, str) or not description.strip() or len(description) > 1024:
        errors.append("description must be a non-empty string of at most 1024 characters.")
    for field in ("license", "compatibility", "allowed-tools"):
        if field in metadata and (not isinstance(metadata[field], str) or not metadata[field].strip()):
            errors.append(field + " must be a non-empty string.")
    if isinstance(metadata.get("compatibility"), str) and len(metadata["compatibility"]) > 500:
        errors.append("compatibility must be at most 500 characters.")
    if "metadata" in metadata:
        extra = metadata["metadata"]
        if not isinstance(extra, dict) or any(not isinstance(value, str) for value in extra.values()):
            errors.append("metadata must be a mapping of strings to strings.")
    for field in INVOCATION_FIELDS:
        if field in metadata and type(metadata[field]) is not bool:
            errors.append(field + " must be a boolean.")
    if metadata.get("disable-model-invocation") is True:
        errors.append("Personal-style Skills must allow implicit invocation.")
    body = content[match.end():]
    if not body.strip():
        errors.append("The Skill body must contain confirmed preferences.")

    prose = []
    fence = None
    for line in body.splitlines():
        marker = re.match(r"^[ ]{0,3}(`{3,}|~{3,})(.*)$", line)
        if marker:
            if fence is None:
                fence = marker[1]
            elif marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = None
            continue
        if fence is None:
            prose.append(re.sub(r"(`+).*?\1", "", line))
    prose = "\n".join(prose)
    # shortcut: common inline and reference links only; use a Markdown parser if richer syntax is needed.
    links = re.findall(r"!?\[[^\]\n]*\]\(\s*(<[^>\n]+>|[^\s)]+)", prose)
    links += re.findall(r"^[ \t]{0,3}\[[^\]\n]+\]:[ \t]*(<[^>\n]+>|\S+)", prose, re.M)
    for link in links:
        destination = link[1:-1] if link.startswith("<") else link
        if re.match(r"^[A-Za-z]:[\\/]", destination):
            errors.append("Local references must be relative to the Skill: " + destination)
            continue
        parsed = urlsplit(destination)
        if parsed.scheme and parsed.scheme != "file":
            continue
        if parsed.netloc:
            continue
        if not parsed.path:
            continue
        relative = Path(unquote(parsed.path))
        if parsed.scheme == "file" or relative.is_absolute() or re.match(r"^[A-Za-z]:", str(relative)):
            errors.append("Local references must be relative to the Skill: " + destination)
            continue
        referenced = (path.parent / relative).resolve()
        if path.parent not in referenced.parents or not referenced.exists():
            errors.append("Local reference is missing or outside the Skill: " + destination)

    config = path.parent / "agents/openai.yaml"
    if config.exists():
        try:
            settings = yaml.load(config.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
            if not isinstance(settings, dict):
                raise ValueError("agents/openai.yaml must be a mapping.")
            policy = settings.get("policy", {})
            if not isinstance(policy, dict):
                raise ValueError("Codex policy must be a mapping.")
            if "allow_implicit_invocation" in policy:
                if type(policy["allow_implicit_invocation"]) is not bool:
                    raise ValueError("allow_implicit_invocation must be a boolean.")
                if policy["allow_implicit_invocation"] is False:
                    errors.append("Codex policy must allow implicit invocation for personal-style Skills.")
        except (OSError, ValueError, yaml.YAMLError) as error:
            errors.append("Invalid agents/openai.yaml: " + str(error))
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", help="Personal-style Skill directory or SKILL.md path")
    args = parser.parse_args(argv)
    try:
        errors = validate_style(args.target)
    except (OSError, ValueError) as error:
        errors = [str(error)]
    print(json.dumps({"status": "invalid" if errors else "valid", "errors": errors}, ensure_ascii=False))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
