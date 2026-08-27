import json
import os
import re
from collections import defaultdict

try:
    from packaging.version import Version, InvalidVersion
except ImportError:
    raise SystemExit("Install packaging: python -m pip install packaging")

INPUT_PATH = os.environ.get("INPUT_PATH", "open_prs.json")
FILES_PATH = os.environ.get("FILES_PATH", "pr_files.json")
RETAIN_PATH = os.environ.get("RETAIN_PATH", "retained_prs.json")
CLOSE_PATH = os.environ.get("CLOSE_PATH", "close_prs.json")


def parse_version(value: str):
    try:
        return Version(str(value))
    except InvalidVersion:
        cleaned = re.sub(r"[^0-9A-Za-z.+-]", "", str(value))
        try:
            return Version(cleaned)
        except InvalidVersion:
            return Version("0")


def parse_body_mentions(body: str):
    records = []

    for line in (body or "").splitlines():
        s = line.strip()

        m = re.match(
            r"^\s*Security upgrade\s+([A-Za-z0-9_.-]+)\s+from\s+([^\s]+)\s+to\s+([^\s]+)",
            s,
            re.I,
        )
        if m:
            pkg, old_v, new_v = m.groups()
            records.append({"package": pkg, "version": old_v})
            records.append({"package": pkg, "version": new_v})
            continue

        m = re.match(
            r"^\s*([A-Za-z0-9_.-]+)\s+([A-Za-z0-9_.-]+)\s+requires\s+([A-Za-z0-9_.-]+)",
            s,
            re.I,
        )
        if m:
            pkg, version, _dep = m.groups()
            records.append({"package": pkg, "version": version})
            continue

        m = re.match(
            r"^\s*([A-Za-z0-9_.-]+)\s+from\s+([^\s]+)\s+to\s+([^\s]+)",
            s,
            re.I,
        )
        if m:
            pkg, old_v, new_v = m.groups()
            records.append({"package": pkg, "version": old_v})
            records.append({"package": pkg, "version": new_v})
            continue

    return records


def parse_patch_mentions(patch_text: str):
    records = []
    if not patch_text:
        return records

    for line in patch_text.splitlines():
        s = line.strip()
        if not s or s.startswith("+++ ") or s.startswith("--- "):
            continue

        m = re.match(r"^[-+]\s*([A-Za-z0-9_.-]+)\s*==\s*([A-Za-z0-9_.-]+)", s)
        if m:
            pkg, version = m.groups()
            records.append({"package": pkg, "version": version})
            continue

        m = re.match(r"^[-+]\s*([A-Za-z0-9_.-]+)\s*[<>=~!]+\s*([A-Za-z0-9_.-]+)", s)
        if m:
            pkg, version = m.groups()
            records.append({"package": pkg, "version": version})
            continue

    return records


def main():
    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        prs = json.load(f)

    by_package = defaultdict(list)

    for pr in prs:
        pr_number = pr.get("number")
        body = pr.get("body") or ""

        for rec in parse_body_mentions(body):
            by_package[rec["package"].lower()].append({
                "pr_number": pr_number,
                "version": rec["version"],
                "title": pr.get("title", ""),
            })

        if os.path.exists(FILES_PATH):
            with open(FILES_PATH, "r", encoding="utf-8") as f:
                pr_files = json.load(f)
            file_entry = next((x for x in pr_files if x.get("number") == pr_number), None)
            if file_entry:
                for file_info in file_entry.get("files", []):
                    for rec in parse_patch_mentions(file_info.get("patch") or ""):
                        by_package[rec["package"].lower()].append({
                            "pr_number": pr_number,
                            "version": rec["version"],
                            "title": pr.get("title", ""),
                        })

    latest_by_package = {}
    for pkg, rows in by_package.items():
        versions = [r["version"] for r in rows]
        latest_by_package[pkg] = max(versions, key=parse_version)

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

            if re.search(rf"{pattern_pkg}\s+{pattern_ver}", body, re.I):
                mentions_latest.append(pkg)
                continue

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
