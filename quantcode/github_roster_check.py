"""Read-only GitHub team/SSH-key crosscheck. Output is local review data, not grants."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess

from quantcode.github_visibility import GH_ORG, paginated
from quantcode.roster import read_workbook, normalize_public_key


def gh_get(path):
    result = subprocess.run(["gh", "api", path], check=True, capture_output=True, text=True, timeout=30)
    return json.loads(result.stdout)


def collect_snapshot(get=gh_get):
    teams = paginated(get, f"/orgs/{GH_ORG}/teams")
    def team_snapshot(team):
        slug = team["slug"]
        return {"slug": slug, "parent": (team.get("parent") or {}).get("slug"),
                "members": [row["login"] for row in paginated(get, f"/orgs/{GH_ORG}/teams/{slug}/members")],
                "repositories": [row["full_name"] for row in paginated(get, f"/orgs/{GH_ORG}/teams/{slug}/repos")]}
    with ThreadPoolExecutor(max_workers=4) as pool:
        snapshots = list(pool.map(team_snapshot, teams))
    logins = sorted({login for team in snapshots for login in team["members"]})
    def user_keys(login):
        fingerprints = []
        for row in paginated(get, f"/users/{login}/keys"):
            _, fingerprint = normalize_public_key(row["key"])
            fingerprints.append(fingerprint)
        return login, fingerprints
    with ThreadPoolExecutor(max_workers=4) as pool:
        keys = dict(pool.map(user_keys, logins))
    return {"organization": GH_ORG, "observed_at": datetime.now(timezone.utc).isoformat(),
            "teams": snapshots, "fingerprints": keys}


def match_records(records, snapshot):
    matches = []
    for row in records:
        try:
            _, fingerprint = normalize_public_key(str(row.get("public_key") or ""))
        except ValueError:
            matches.append({"row": row["row"], "status": "PUBLIC_KEY_REQUIRED_OR_INVALID"})
            continue
        logins = [login for login, keys in snapshot["fingerprints"].items() if fingerprint in keys]
        match = {"row": row["row"], "status": "MATCHED" if len(logins) == 1 else "UNMATCHED" if not logins else "CONFLICT",
                 "github_subjects": logins}
        if len(logins) == 1:
            match["teams"] = [team["slug"] for team in snapshot["teams"] if logins[0] in team["members"]]
        matches.append(match)
    return matches


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    snapshot = collect_snapshot()
    matches = match_records(read_workbook(args.workbook), snapshot)
    args.output.mkdir(parents=True, exist_ok=False, mode=0o700)
    for name, value in [("snapshot.json", snapshot), ("matches.json", matches)]:
        descriptor = os.open(args.output / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
    print(json.dumps({"teams": len(snapshot["teams"]), "members": len(snapshot["fingerprints"]),
                      "matched_rows": sum(item["status"] == "MATCHED" for item in matches),
                      "rows": len(matches)}))


if __name__ == "__main__":
    main()
