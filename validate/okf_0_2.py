"""OKF 0.2 checks for one file.

Errors are what §11 makes conformance: parseable frontmatter with a non-empty
`type` in every concept, and reserved files that follow §8 and §9. Warnings are
the SHOULDs of §5 to §7, which a conformant consumer may not reject a document
for.
"""

import datetime
import re
from pathlib import Path

import yaml

ACTOR = re.compile(r"^(human:|process:)\S+$|^[^\s/:]+/\S+$")
DATE_HEADING = re.compile(r"^## \d{4}-\d{2}-\d{2}$")
STATUS = ("deprecated", "draft", "stable")


def split(text):
    """The frontmatter's text and the line after its closing `---`, or None."""
    lines = text.split("\n")
    if not lines or lines[0].rstrip() != "---":
        return None
    for i, line in enumerate(lines[1:], 1):
        if line.rstrip() == "---":
            return "\n".join(lines[1:i]), i + 1
    return None


def is_instant(value):
    if isinstance(value, (datetime.datetime, datetime.date)):
        return True
    try:
        datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def parse(text):
    """(frontmatter, error): the frontmatter mapping, or why there isn't one."""
    found = split(text)
    if found is None:
        return None, "no YAML frontmatter: start the file with `---`, then close it with `---` (OKF 0.2 §4)"
    try:
        data = yaml.safe_load(found[0])
    except yaml.YAMLError as error:
        return None, f"the frontmatter isn't valid YAML: {error}".replace("\n", " ")
    if data is None:
        return {}, None
    if not isinstance(data, dict):
        return None, "the frontmatter must be a YAML mapping (OKF 0.2 §4.1)"
    return data, None


def check_actor(where, value):
    if not isinstance(value, str) or not ACTOR.match(value):
        return [("warning", f"{where} `{value}` isn't an actor: use `human:<id>`, `process:<id>` or "
                            "`<producer>/<version>` (OKF 0.2 §7)")]
    return []


def check_concept(text):
    data, error = parse(text)
    if error:
        return [("error", error)]
    findings = []
    kind = data.get("type")
    if not isinstance(kind, str) or not kind.strip():
        findings.append(("error", "`type` is required and must be a non-empty string (OKF 0.2 §4.1)"))

    status = data.get("status")
    if status is not None and status not in STATUS:
        findings.append(("warning", f"`status: {status}` isn't one of {', '.join(STATUS)} (OKF 0.2 §5.4)"))

    generated = data.get("generated")
    if generated is not None:
        if not isinstance(generated, dict) or "by" not in generated:
            findings.append(("warning", "`generated` must be a mapping with `by` (OKF 0.2 §5.2)"))
        else:
            findings += check_actor("`generated.by`", generated["by"])
            if "at" in generated and not is_instant(generated["at"]):
                findings.append(("warning", f"`generated.at` `{generated['at']}` isn't an ISO 8601 datetime (OKF 0.2 §5.2)"))

    verified = data.get("verified")
    if verified is not None:
        entries = [verified] if isinstance(verified, dict) else verified
        if not isinstance(entries, list):
            findings.append(("warning", "`verified` must be a list of `{ by, at }` (OKF 0.2 §5.2)"))
            entries = []
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict) or "by" not in entry or "at" not in entry:
                findings.append(("warning", f"`verified[{i}]` must have `by` and `at` (OKF 0.2 §5.2)"))
                continue
            findings += check_actor(f"`verified[{i}].by`", entry["by"])
            if not is_instant(entry["at"]):
                findings.append(("warning", f"`verified[{i}].at` `{entry['at']}` isn't an ISO 8601 datetime (OKF 0.2 §5.2)"))

    stale_after = data.get("stale_after")
    if stale_after is not None and not is_instant(stale_after):
        findings.append(("warning", f"`stale_after` `{stale_after}` isn't an ISO 8601 datetime (OKF 0.2 §5.5)"))

    tags = data.get("tags")
    if tags is not None and not isinstance(tags, list):
        findings.append(("warning", "`tags` must be a YAML list (OKF 0.2 §4.1)"))
    return findings


def check_index(text):
    if split(text) is None:
        return []
    data, error = parse(text)
    if error:
        return [("error", error)]
    if set(data) - {"okf_version"}:
        return [("error", "`index.md` has no frontmatter, except `okf_version` in a bundle's root index (OKF 0.2 §8)")]
    return []


def check_log(text):
    findings, dates = [], []
    for line in text.split("\n"):
        if line.startswith("## "):
            if DATE_HEADING.match(line.rstrip()):
                dates.append(line.strip()[3:])
            else:
                findings.append(("error", f"`{line.strip()}`: date headings use `## YYYY-MM-DD` (OKF 0.2 §9)"))
    if dates != sorted(dates, reverse=True):
        findings.append(("warning", "date headings should be newest first (OKF 0.2 §9)"))
    return findings


def check(path):
    """[(severity, message)] for the file at `path`."""
    text = Path(path).read_text(encoding="utf-8")
    name = Path(path).name
    if name == "index.md":
        return check_index(text)
    if name == "log.md":
        return check_log(text)
    return check_concept(text)
