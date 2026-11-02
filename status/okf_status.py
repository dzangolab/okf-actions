#!/usr/bin/env python3
"""Change the status of OKF documents, or record a verification, on request.

Run by hand through workflow_dispatch: the person who runs it is the one recorded,
so `verified` can't name somebody else. The approve rules don't apply here.
"""

import datetime
import os
import re
import subprocess
import sys
from pathlib import Path

# The action's folder sits in a full copy of this repository, approve/ included.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "approve"))
from okf_approve import add_log_entries, add_verified, field, frontmatter, is_bot, matching, nearest_log  # noqa: E402

STATUSES = ("deprecated", "draft", "stable", "unchanged")


def documents(globs):
    tracked = subprocess.run(["git", "ls-files", "-z"], check=True, capture_output=True, text=True).stdout.split("\0")
    pages = [f for f in tracked if f.endswith(".md") and Path(f).name not in ("index.md", "log.md")]
    return sorted(matching(globs, pages))


def main():
    globs = re.split(r"[\s,]+", os.environ.get("PATHS", "").strip())
    status = os.environ.get("STATUS") or "unchanged"
    verify = os.environ.get("VERIFY", "false").lower() == "true"
    actor = os.environ["GITHUB_ACTOR"]
    if globs == [""]:
        sys.exit("::error::`paths` is required.")
    if status not in STATUSES:
        sys.exit(f"::error::`status` must be one of {list(STATUSES)}, not {status}.")
    if status == "unchanged" and not verify:
        sys.exit("::error::Nothing to do: set `status`, `verify`, or both.")
    if is_bot(actor) and (verify or status == "stable"):
        sys.exit(f"::error::{actor} is a bot: only a person can be recorded in `verified`.")

    files = documents(globs)
    if not files:
        sys.exit(f"::error::No document matches {' '.join(globs)}.")

    at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    report, logs = [], {}
    for file in files:
        lines = Path(file).read_text().split("\n")
        end = frontmatter(lines)
        if end is None:
            continue
        head = lines[1:end]
        current = field(head, "status") or "stable"
        new = current if status == "unchanged" else status
        # A page never becomes stable without a name against it.
        record = verify or (new == "stable" and current != "stable")
        if new == current and not record:
            continue

        if new != current:
            if field(head, "status"):
                head = [f"status: {new}" if re.match(r"status:", line) else line for line in head]
            else:
                head.append(f"status: {new}")
        if record:
            head = add_verified(head, [(actor, at)])
        Path(file).write_text("\n".join(["---"] + head + lines[end:]))
        report.append((file, current, new, record))

        if folder := nearest_log(file):
            title = field(head, "title") or Path(file).stem
            link = "/" + str(Path(file).relative_to(folder))
            if new == current:
                how = f"verified by @{actor}."
            elif record:
                how = f"marked {new}; verified by @{actor}."
            else:
                how = f"marked {new} by @{actor}."
            logs.setdefault(folder, []).append(f"**Update**: [{title}]({link}) {how}")

    for folder, entries in logs.items():
        add_log_entries(folder, entries)

    lines = ["### okf-status", ""]
    if report:
        lines += ["| Document | Status | Verified by |", "| --- | --- | --- |"]
        lines += [f"| `{f}` | {c}{' → ' + n if n != c else ''} | {'@' + actor if r else 'nobody'} |"
                  for f, c, n, r in report]
    else:
        lines.append("No document needed changing.")
    summary = "\n".join(lines) + "\n"
    print(summary)
    if path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(path, "a") as out:
            out.write(summary)


if __name__ == "__main__":
    main()
