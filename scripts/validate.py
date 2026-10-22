#!/usr/bin/env python3
"""Validate every registry/*.yml: schema, name rules, unique hosts, reachable origins.

Usage: python3 scripts/validate.py [--online] [FILE ...]
Exit status 1 when any error is found. Needs PyYAML.
"""
import pathlib
import re
import subprocess
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,38}[a-z0-9]$")
LAB_RE = NAME_RE
GIT_URL_RE = re.compile(r"^(https://github\.com/[\w.-]+/[\w.-]+|git@github\.com:[\w.-]+/[\w.-]+\.git)$")
# Names central keeps for itself (src/edit/createVault.js RESERVED_HOSTS plus SYNC_EXCLUDE).
RESERVED = {
    "www", "api", "doi", "root", "localhost", "local", "mail", "ftp", "static", "cdn", "admin",
    "chat", "mcp", "agents", "recent", "id", "search", "wanted", "new-vault", "register", "3d",
    "ads", "ai", "ai0", "analytics", "blog", "c", "ci", "comms", "contact", "docs", "earn",
    "email", "es", "graph", "leads", "login", "news", "obsidian", "party", "pocketz", "tables",
    "vid", "src", "tools", "test",
}
LOCATION_TYPES = {"disk", "s3", "node", "git"}


def check_origin(origin, where, errors):
    if origin is None:
        return
    if not isinstance(origin, dict):
        errors.append(f"{where}: origin must be a mapping or null")
        return
    if origin.get("type") != "git":
        errors.append(f"{where}: origin.type must be 'git'")
    url = origin.get("url", "")
    if not isinstance(url, str) or not GIT_URL_RE.match(url):
        errors.append(f"{where}: origin.url must be a GitHub https or ssh URL (got {url!r})")
    if not isinstance(origin.get("branch", "main"), str):
        errors.append(f"{where}: origin.branch must be a string")
    if origin.get("visibility", "public") not in ("public", "private"):
        errors.append(f"{where}: origin.visibility must be public or private")


def check_vault(v, lab, where, hosts, errors, base_lab):
    if not isinstance(v, dict):
        errors.append(f"{where}: entry must be a mapping")
        return
    name = v.get("name")
    # The base lab keeps a few one-letter hosts from before the rule (c.doi.bio); nobody else may.
    legacy = lab == base_lab and isinstance(name, str) and re.match(r"^[a-z0-9]$", name)
    if not isinstance(name, str) or not (NAME_RE.match(name) or legacy):
        errors.append(f"{where}: invalid name {name!r}")
        return
    where = f"{where} ({name})"
    kind = v.get("kind", "vault")
    if kind not in ("vault", "support"):
        errors.append(f"{where}: kind must be vault or support")
    host = v.get("host")
    if kind == "support":
        if host not in (None, "null"):
            errors.append(f"{where}: a support entry has no host")
    else:
        expected = "doi.bio" if (name == "doi" and lab == base_lab) else f"{name}.doi.bio"
        if host != expected:
            errors.append(f"{where}: host must be {expected} (got {host!r})")
        if name in RESERVED and lab != base_lab:
            errors.append(f"{where}: {name} is a reserved name")
        if host in hosts:
            errors.append(f"{where}: host {host} is already registered in {hosts[host]}")
        hosts[host] = where
    if "origin" not in v:
        errors.append(f"{where}: origin is required (use null when there is no repository)")
    check_origin(v.get("origin"), where, errors)
    locs = v.get("locations", [])
    if not isinstance(locs, list):
        errors.append(f"{where}: locations must be a list")
        locs = []
    for i, loc in enumerate(locs):
        if not isinstance(loc, dict) or loc.get("type") not in LOCATION_TYPES:
            errors.append(f"{where}: locations[{i}] needs a type in {sorted(LOCATION_TYPES)}")
    if v.get("origin") is None and not locs:
        errors.append(f"{where}: a vault without an origin must list at least one location")
    if "served" in v and not isinstance(v["served"], bool):
        errors.append(f"{where}: served must be true or false")
    if "editing" in v and v["editing"] not in ("public", "owners"):
        errors.append(f"{where}: editing must be public or owners")


def check_file(path, hosts, errors, base_lab):
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        errors.append(f"{path}: not valid YAML: {e}")
        return []
    where = str(path.relative_to(ROOT))
    if not isinstance(data, dict):
        errors.append(f"{where}: top level must be a mapping")
        return []
    lab = data.get("lab")
    if not isinstance(lab, str) or not LAB_RE.match(lab):
        errors.append(f"{where}: invalid lab {lab!r}")
    elif lab != path.stem:
        errors.append(f"{where}: lab {lab!r} must equal the file name {path.stem!r}")
    for key in ("name", "maintainers"):
        if key not in data:
            errors.append(f"{where}: missing {key}")
    if not isinstance(data.get("maintainers", []), list) or not data.get("maintainers"):
        errors.append(f"{where}: maintainers must be a non-empty list")
    vaults = data.get("vaults")
    if not isinstance(vaults, list) or not vaults:
        errors.append(f"{where}: vaults must be a non-empty list")
        vaults = []
    origins = []
    for i, v in enumerate(vaults):
        check_vault(v, lab, f"{where} vaults[{i}]", hosts, errors, base_lab)
        if isinstance(v, dict) and isinstance(v.get("origin"), dict):
            origins.append(v["origin"])
    for i, v in enumerate(data.get("retiring", []) or []):
        check_vault(v, lab, f"{where} retiring[{i}]", hosts, errors, base_lab)
    return origins


def ls_remote(origin):
    url = origin["url"]
    try:
        r = subprocess.run(["git", "ls-remote", "--exit-code", "--heads", url, origin.get("branch", "main")],
                           capture_output=True, text=True, timeout=30,
                           env={"GIT_TERMINAL_PROMPT": "0", "PATH": "/usr/bin:/bin:/usr/local/bin"})
        return r.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def main(argv):
    online = "--online" in argv
    files = [pathlib.Path(a) for a in argv if not a.startswith("--")] or sorted((ROOT / "registry").glob("*.yml"))
    errors, hosts, origins = [], {}, []
    for path in files:
        origins += check_file(path, hosts, errors, base_lab="doi-dot-bio")
    if online:
        for origin in origins:
            if origin.get("visibility", "public") == "public" and not ls_remote(origin):
                errors.append(f"origin not reachable: {origin['url']} ({origin.get('branch', 'main')})")
    for e in errors:
        print("ERROR", e)
    print(f"{len(files)} file(s), {len(hosts)} host(s), {len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
