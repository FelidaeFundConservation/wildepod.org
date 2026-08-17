import json
import os
import re
from collections import defaultdict

try:
    from packaging.version import Version, InvalidVersion
except ImportError:
    raise SystemExit("Install packaging: python -m pip install packaging")

INPUT_PATH = os.environ.get("INPUT_PATH", "open_prs.json")
RETAIN_PATH = os.environ.get("RETAIN_PATH", "retained_prs.json")
CLOSE_PATH = os.environ.get("CLOSE_PATH", "close_prs.json")


def normalize_version(v: str):
    try:
        return Version(str(v))
    except InvalidVersion:
        # fallback for weird Snyk versions like post-release or local labels
        cleaned = re.sub(r"[^0-9A-Za-z.+-]", "", str(v))
        try:
            return Version(cleaned)
        except InvalidVersion:
            return Version("0")


def parse_mentions(body: str):
    records = []

    for line in (body or "").splitlines():
        s = line.strip()

        # Pattern: "Security upgrade foo from 1.2.3 to 2.0.0"
        m = re.match(
            r"^\s*Security upgrade\s+([A-Za-z0-9_.-]+)\s+from\s+([^\s]+)\s+to\s+([^\s]+)",
            s,
            re.I,
        )
        if m:
            pkg, old_v, new_v = m.groups()
            records.append({"package": pkg, "version": old_v, "kind": "old"})
            records.append({"package": pkg, "version": new_v, "kind": "new"})
            continue

        # Pattern: "foo 1.2.3 requires bar, which is not installed."
        m = re.match(
            r"^\s*([A-Za-z0-9_.-]+)\s+([A-Za-z0-9_.-]+)\s+requires\s+([A-Za-z0-9_.-]+)",
            s,
            re.I,
        )
        if m:
            pkg, version, _dep = m.groups()
            records.append({"package": pkg, "version": version, "kind": "requires"})
            continue

        # Generic fallback: "package from old to new"
        m = re.match(
            r"^\s*([A-Za-z0-9_.-]+)\s+from\s+([^\s]+)\s+to\s+([^\s]+)",
            s,
            re.I,
        )
        if m:
            pkg, old_v, new_v = m.groups()
            records.append({"package": pkg, "version": old_v, "kind": "old"})
            records.append({"package": pkg, "version": new_v, "kind": "new"})
            continue

    return records


def main():
    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        prs = json.load(f)

    by_package = defaultdict(list)

    for pr in prs:
        pr_number = pr.get("number")
        body = pr.get("body") or ""
        for rec in parse_mentions(body):
            by_package[rec["package"].lower()].append({
                "pr_number": pr_number,
                "version": rec["version"],
                "title": pr.get("title", ""),
                "kind": rec["kind"],
            })

    latest_by_package = {}
    for pkg, rows in by_package.items():
        versions = [r["version"] for r in rows]
        latest = max(versions, key=normalize_version)
        latest_by_package[pkg] = latest

    retained = []
    closed = []

    for pr in prs:
        pr_number = pr.get("number")
        title = pr.get("title", "")
        body = pr.get("body") or ""
        mentions_latest = []

        for pkg, latest_version in latest_by_package.items():
            pattern_pkg = re.escape(pkg)
            pattern_ver = re.escape(latest_version)

            # exact mention: "package 2.3.4"
            if re.search(rf"{pattern_pkg}\s+{pattern_ver}", body, re.I):
                mentions_latest.append(pkg)
                continue

            # upgrade mention: "package from 1.2.3 to 2.3.4"
            if re.search(
                rf"{pattern_pkg}\s+from\s+[^\s]+\s+to\s+{pattern_ver}",
                body,
                re.I,
            ):
                mentions_latest.append(pkg)

        if mentions_latest:
            retained.append({
                "number": pr_number,
                "title": title,
                "mentions_latest_version_for": sorted(set(mentions_latest)),
            })
        else:
            closed.append({
                "number": pr_number,
                "title": title,
            })

    with open(RETAIN_PATH, "w", encoding="utf-8") as f:
        json.dump(retained, f, indent=2)

    with open(CLOSE_PATH, "w", encoding="utf-8") as f:
        json.dump(closed, f, indent=2)

    print(f"retained={len(retained)}")
    print(f"closed={len(closed)}")
    print(f"files written: {RETAIN_PATH}, {CLOSE_PATH}")


if __name__ == "__main__":
    main()
