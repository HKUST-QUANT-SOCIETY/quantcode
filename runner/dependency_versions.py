"""Read dependency declarations and resolved versions without executing manifests."""
from __future__ import annotations

import json
import tomllib
import posixpath
import re
import json5
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


PARSER_REVISION = 4


def is_dependency_file(name: str) -> bool:
    return name in {"pyproject.toml", "package.json", "package-lock.json", "bun.lock", "uv.lock", "poetry.lock", "requirements"} or (
        name.startswith("requirements") and name.endswith((".txt", ".in"))
    )


def _requirements(values: list, section: str) -> dict[str, str]:
    result: dict[str, set[str]] = {}
    for value in values:
        if not isinstance(value, str):
            raise ValueError("dependency declaration must be a string")
        requirement = Requirement(value)
        key = f"declared:{section}:{canonicalize_name(requirement.name)}"
        result.setdefault(key, set()).add(str(requirement))
    return {key: " | ".join(sorted(items)) for key, items in result.items()}


def _dependency_groups(groups: dict) -> dict[str, list[str]]:
    if not isinstance(groups, dict):
        raise ValueError("dependency groups must be a table")
    normalized = {}
    for name, values in groups.items():
        key = canonicalize_name(name, validate=True)
        if key in normalized:
            raise ValueError("duplicate normalized dependency group name")
        normalized[key] = values
    resolved = {}

    def expand(name, ancestors):
        if name in ancestors:
            raise ValueError("cyclic dependency group include")
        if name in resolved:
            return resolved[name]
        if name not in normalized:
            raise ValueError("included dependency group does not exist")
        if not isinstance(normalized[name], list):
            raise ValueError("dependency group must be an array")
        values = []
        for item in normalized[name]:
            if isinstance(item, str):
                Requirement(item)
                values.append(item)
            elif isinstance(item, dict) and set(item) == {"include-group"} and isinstance(item["include-group"], str):
                values.extend(expand(canonicalize_name(item["include-group"], validate=True), ancestors | {name}))
            else:
                raise ValueError("invalid dependency group entry")
            if len(values) > 100_000:
                raise ValueError("expanded dependency group exceeds 100000 declarations")
        resolved[name] = values
        return values

    # Expansion retains declaration order and duplicates. The caller produces
    # a package-change summary; this is not an installer or dependency solver.
    return {name: expand(canonicalize_name(name), set()) for name in groups}


def _requirements_file(path, content, read_file, ancestors=(), constraint=False):
    if path in ancestors:
        raise ValueError("cyclic requirements include")
    result = {}
    declarations = []
    for raw in content.replace("\\\r\n", "").replace("\\\n", "").splitlines():
        line = raw.split(" #", 1)[0].strip()
        if not line or line.startswith("#"):
            continue
        include = re.fullmatch(r"(?:-r\s*|--requirement(?:=|\s+))(.+)", line)
        constrain = re.fullmatch(r"(?:-c\s*|--constraint(?:=|\s+))(.+)", line)
        if include or constrain:
            if read_file is None:
                return None
            relative = (include or constrain).group(1).strip().strip("\"'")
            if ":" in relative or relative.startswith("/") or "${" in relative:
                return None
            target = posixpath.normpath(posixpath.join(posixpath.dirname(path), relative))
            if target == ".." or target.startswith("../"):
                raise ValueError("requirements include escapes repository")
            included = _requirements_file(target, read_file(target), read_file, (*ancestors, path), constraint or bool(constrain))
            if included is None:
                return None
            result.update(included)
            continue
        if line.startswith("-") or "${" in line:
            return None  # environment and installer options are not resolved.
        declaration = re.sub(r"\s+--hash(?:=|\s+)\S+", "", line)
        if " --" in declaration:
            return None
        declarations.append(declaration)
    result.update(_requirements(declarations, f"{'constraints' if constraint else 'requirements'}:{path}"))
    return result


def parse_versions(path: str, content: str, *, read_file=None) -> dict[str, str] | None:
    """Keys retain dependency section/location so parallel versions never overwrite.

    None means unsupported syntax. Version declarations are preserved literally;
    a changed range is not presented as an installed package upgrade.
    """
    source_path = path
    path = posixpath.basename(path)
    if path == "pyproject.toml":
        document = tomllib.loads(content)
        project = document.get("project", {})
        if {"dependencies", "optional-dependencies"}.intersection(project.get("dynamic", [])):
            return None
        dependencies = project.get("dependencies", [])
        if not isinstance(dependencies, list):
            raise ValueError("project dependencies must be an array")
        result = _requirements(dependencies, "project")
        for group, values in project.get("optional-dependencies", {}).items():
            if not isinstance(values, list):
                raise ValueError("optional dependencies must be an array")
            result.update(_requirements(values, f"optional:{group}"))
        poetry = document.get("tool", {}).get("poetry", {})
        sections = {"poetry": poetry.get("dependencies", {}), "poetry-dev": poetry.get("dev-dependencies", {})}
        sections.update({f"poetry-group:{group}": data.get("dependencies", {}) for group, data in poetry.get("group", {}).items()})
        for section, values in sections.items():
            if not isinstance(values, dict):
                raise ValueError("Poetry dependencies must be a table")
            for name, value in values.items():
                result[f"declared:{section}:{canonicalize_name(name)}"] = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
        for group, values in _dependency_groups(document.get("dependency-groups", {})).items():
            result.update(_requirements(values, f"group:{group}"))
        return result
    if path.startswith("requirements"):
        return _requirements_file(source_path, content, read_file)
    if path == "package.json":
        document = json.loads(content)
        result = {}
        for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
            values = document.get(section, {})
            if not isinstance(values, dict) or not all(isinstance(value, str) for value in values.values()):
                raise ValueError(f"invalid {section}")
            result.update({f"declared:{section}:{name}": value for name, value in values.items()})
        return result
    if path == "bun.lock":
        document = json5.loads(content, allow_duplicate_keys=False)
        if not isinstance(document, dict) or document.get("lockfileVersion") != 1:
            return None
        packages = document.get("packages")
        if not isinstance(packages, dict):
            raise ValueError("Bun lockfile has no package map")
        result = {}
        for location, package in packages.items():
            if not isinstance(package, list) or not package or not isinstance(package[0], str):
                raise ValueError("invalid Bun package record")
            # Retain Bun's full resolution descriptor, including workspace/git
            # resolutions; do not mislabel every source as a semver package.
            result[f"resolved:{location}"] = package[0]
        for workspace, manifest in document.get("workspaces", {}).items():
            for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
                values = manifest.get(section, {})
                if not isinstance(values, dict) or not all(isinstance(value, str) for value in values.values()):
                    raise ValueError("invalid Bun workspace declarations")
                result.update({f"declared:{workspace}:{section}:{name}": value for name, value in values.items()})
        return result
    if path == "package-lock.json":
        document = json.loads(content)
        if document.get("lockfileVersion") == 1:
            result = {}
            pending = [("", document.get("dependencies", {}))]
            while pending:
                prefix, dependencies = pending.pop()
                if not isinstance(dependencies, dict):
                    raise ValueError("invalid npm v1 dependencies")
                for name, dependency in dependencies.items():
                    if not isinstance(dependency, dict) or not isinstance(dependency.get("version"), str):
                        raise ValueError("invalid npm v1 package version")
                    location = f"{prefix}node_modules/{name}"
                    result[f"resolved:{location}"] = dependency["version"]
                    pending.append((location + "/", dependency.get("dependencies", {})))
            return result
        packages = document.get("packages")
        if not isinstance(packages, dict):
            return None
        result = {}
        for location, package in packages.items():
            if not location:
                continue
            if not isinstance(package, dict):
                raise ValueError("invalid locked package")
            if package.get("link"):
                result[f"resolved:{location}"] = f"link:{package.get('resolved', '')}"
            elif isinstance(package.get("version"), str):
                result[f"resolved:{location}"] = package["version"]
            else:
                raise ValueError("locked package has no version")
        return result
    if path in {"uv.lock", "poetry.lock"}:
        document = tomllib.loads(content)
        packages = document.get("package")
        if not isinstance(packages, list):
            raise ValueError("lockfile has no package list")
        result: dict[str, set[str]] = {}
        for package in packages:
            if not isinstance(package.get("name"), str) or not isinstance(package.get("version"), str):
                raise ValueError("locked package has no name/version")
            # Preserve all versions for marker-specific or source-specific locks.
            key = f"resolved:{package['name']}"
            source = package.get("source")
            value = package["version"]
            if source:
                value += " " + json.dumps(source, sort_keys=True, ensure_ascii=False)
            result.setdefault(key, set()).add(value)
        return {key: " | ".join(sorted(values)) for key, values in result.items()}
    return None
