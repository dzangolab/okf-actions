#!/usr/bin/env python3
"""Mark OKF documents approved when their pull request is merged.

Only `draft` documents a pull request changed are handled. For each, the first rule
whose paths match it decides who is responsible for it (`verify`). A draft becomes
stable only with somebody to record. On a merged pull request the documents and the
nearest `log.md` are updated in place; on an open one nothing is written and the
outcome is only reported. A merge is never blocked.
"""

import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_VERIFY = ["approvers", "merger"]
DEFAULT_RULES = [
    {"paths": ["**/README.md", "docs/**", "knowledge/**", "specs/**"], "stable": "on-merge", "verify": DEFAULT_VERIFY},
]
STABLE = ("never", "on-merge")
VERIFY = ("approvers", "author", "merger", "reviewers")
CODEOWNERS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")
# The commented-out `verified` placeholder that document templates may leave in.
PLACEHOLDER = re.compile(r"#\s*(Added on merge|Add when the pull request is approved|Add on approval|verified:|-? *at:|by:)")

warnings = []


def warn(message):
    warnings.append(message)
    print(f"::warning::{message}")


def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def api(path):
    """GET a GitHub API path, following pagination; None when the call fails."""
    fixtures = os.environ.get("OKF_APPROVE_FIXTURES")
    if fixtures:
        file = Path(fixtures) / (re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-") + ".json")
        return json.loads(file.read_text()) if file.exists() else None
    result = subprocess.run(["gh", "api", "--paginate", "--slurp", path], capture_output=True, text=True)
    if result.returncode:
        return None
    pages = json.loads(result.stdout)
    return [item for page in pages for item in page] if pages and isinstance(pages[0], list) else pages


def load_rules(path):
    file = Path(path)
    if not file.exists():
        return DEFAULT_RULES
    try:
        config = json.loads(file.read_text())  # JSON is valid YAML too
    except json.JSONDecodeError:
        try:
            import yaml
            config = yaml.safe_load(file.read_text())
        except ImportError:  # GitHub's runners have yq
            config = json.loads(subprocess.run(["yq", "-o=json", ".", str(file)], check=True,
                                               capture_output=True, text=True).stdout)
    rules = (config or {}).get("rules")
    if not isinstance(rules, list) or not rules:
        sys.exit(f"::error::{path}: `rules` must be a non-empty list")
    for i, rule in enumerate(rules):
        where = f"{path}: rules[{i}]"
        if not rule.get("paths"):
            sys.exit(f"::error::{where}: `paths` is required")
        if "owners" in rule or "owners" in rule.get("verify", []):
            sys.exit(f"::error::{where}: `owners` was renamed `reviewers`, as a key and as a `verify` value")
        if rule.get("stable") == "on-verify":
            sys.exit(f"::error::{where}: `stable: on-verify` was removed: a draft only ever becomes stable when "
                     "somebody is recorded, so remove the key")
        if rule.get("verify") == []:
            sys.exit(f"::error::{where}: `verify` can't be empty: somebody must be responsible for a page becoming "
                     "stable. To leave the pages alone, use `stable: never`")
        rule.setdefault("verify", DEFAULT_VERIFY)
        rule.setdefault("stable", "on-merge")
        if unknown := [v for v in rule["verify"] if v not in VERIFY]:
            sys.exit(f"::error::{where}: unknown `verify` value {unknown}; use {list(VERIFY)}")
        if rule["stable"] not in STABLE:
            sys.exit(f"::error::{where}: `stable` must be one of {list(STABLE)}")
    return rules


def matching(globs, files):
    """The files, among `files`, that git's glob pathspecs select; `!` excludes."""
    specs = [f":(glob,exclude){g[1:]}" if g.startswith("!") else f":(glob){g}" for g in globs]
    if not any(not g.startswith("!") for g in globs):
        specs.insert(0, ":(glob)**")
    return set(git("ls-files", "-z", "--", *specs).split("\0")) & set(files)


def gitignore_match(pattern, file):
    return bool(git("ls-files", "-c", "-i", f"--exclude={pattern}", "--", file).strip())


def codeowners():
    for name in CODEOWNERS:
        if Path(name).exists():
            entries = []
            for line in Path(name).read_text().splitlines():
                parts = line.split("#", 1)[0].split()
                if parts:
                    entries.append((parts[0], parts[1:]))
            return name, entries
    return None, []


team_cache = {}


def resolve(owners):
    """Lowercase logins for `@user` and `@org/team` entries; teams need a token that can read them."""
    logins = set()
    for owner in owners:
        if not owner.startswith("@"):
            warn(f"Owner {owner} is ignored: only @user and @org/team are supported.")
        elif "/" in owner:
            if owner not in team_cache:
                org, team = owner[1:].split("/", 1)
                members = api(f"orgs/{org}/teams/{team}/members")
                if members is None:
                    warn(f"Couldn't read the members of {owner}: give the action a token that can read the "
                         "organization's teams. The team is skipped.")
                team_cache[owner] = {m["login"].lower() for m in members or []}
            logins |= team_cache[owner]
        else:
            logins.add(owner[1:].lower())
    return logins


def reviewers_of(rule, file, codeowners_file, codeowners_entries):
    """The logins who may verify the file; None when the rule and the repository define nobody."""
    if rule.get("reviewers"):
        return resolve(rule["reviewers"])
    if codeowners_file:
        for pattern, owners in reversed(codeowners_entries):
            if gitignore_match(pattern, file):
                return resolve(owners)
        return set()
    return None


def is_bot(login):
    return login.endswith("[bot]")


def frontmatter(lines):
    if not lines or lines[0] != "---" or "---" not in lines[1:]:
        return None
    return lines.index("---", 1)


def field(head, key):
    for line in head:
        if m := re.match(rf"{key}:\s*(.*)$", line):
            return m.group(1).strip().strip("'\"")
    return None


def add_verified(head, entries):
    head = [line for line in head if not PLACEHOLDER.match(line)]
    block = [f"  - at: {at}\n    by: human:{login}" for login, at in entries]
    for i, line in enumerate(head):
        if line.startswith("verified:"):
            inline = line[len("verified:"):].strip()
            if inline:
                # A single verification written inline (`verified: { by: …, at: … }`) becomes a list item.
                head[i:i + 1] = ["verified:", f"  - {inline.strip('[] ')}"]
            j = i + 1
            while j < len(head) and (head[j].startswith(" ") or head[j].startswith("-")):
                j += 1
            head[j:j] = block
            return head
    return head + ["verified:"] + block


def nearest_log(file):
    for folder in Path(file).parents:
        if (folder / "log.md").exists():
            return folder
    return None


def add_log_entries(folder, entries):
    log = folder / "log.md"
    text = log.read_text().split("\n")
    today = f"## {os.environ.get('OKF_APPROVE_TODAY') or datetime.date.today().isoformat()}"
    if today in text:
        at = text.index(today) + 1
    else:
        at = next((i for i, line in enumerate(text) if line.startswith("## ")), len(text))
        text[at:at] = [today, ""]
        at += 1
    text[at:at] = [""] + [part for entry in entries for part in (entry, "")][:-1]
    log.write_text("\n".join(text))


def one_entry_per_person(verifiers):
    """Somebody who both approves and merges is recorded once, at the later time."""
    latest = {}
    for login, at in verifiers:
        latest[login] = max(at, latest.get(login, at))
    return list(latest.items())


def changes_to_the_rules(files, config):
    """The files a pull request changes that decide how its own pages are verified."""
    watched = {config, *CODEOWNERS}
    if workflow := os.environ.get("GITHUB_WORKFLOW_REF"):  # owner/repo/.github/workflows/x.yml@ref
        watched.add(workflow.split("@")[0].split("/", 2)[-1])
    names = {name for f in files for name in (f["filename"], f.get("previous_filename"))}
    return sorted(watched & names)


def main():
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    pr = event.get("pull_request")
    if not pr:
        sys.exit("::error::okf-approve runs on pull_request events only.")
    repo, number, author = os.environ["GITHUB_REPOSITORY"], pr["number"], pr["user"]["login"]
    merged = bool(pr.get("merged"))
    merged_at = pr.get("merged_at") or "on merge"
    merger = (pr.get("merged_by") or {}).get("login")
    label = os.environ.get("KEEP_STATUS_LABEL", "okf: keep-status")
    keep_status = label in [lbl["name"] for lbl in pr.get("labels", [])]
    config = os.environ.get("CONFIG", ".github/okf-approve.yml")
    rules = load_rules(config)

    # Each reviewer's latest decisive review counts; keep those that approve.
    latest = {}
    for review in sorted(api(f"repos/{repo}/pulls/{number}/reviews") or [], key=lambda r: r.get("submitted_at") or ""):
        if review["state"] in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            latest[review["user"]["login"]] = review
    approvals = {login: r["submitted_at"] for login, r in latest.items() if r["state"] == "APPROVED" and login != author}

    files_changed = api(f"repos/{repo}/pulls/{number}/files") or []
    changed = [f["filename"] for f in files_changed
               if f["status"] != "removed" and f["filename"].endswith(".md")
               and Path(f["filename"]).name not in ("index.md", "log.md") and Path(f["filename"]).exists()]
    claimed, ruled = set(), []
    for rule in rules:
        files = sorted(matching(rule["paths"], changed) - claimed)
        claimed |= set(files)
        ruled += [(rule, file) for file in files]

    codeowners_file, codeowners_entries = codeowners()
    report, logs, missing_reviewers, nobody = [], {}, {}, []
    for rule, file in ruled:
        lines = Path(file).read_text().split("\n")
        end = frontmatter(lines)
        if end is None:
            continue
        head = lines[1:end]
        if (field(head, "status") or "stable") != "draft":
            continue
        if rule["stable"] == "never" or keep_status:
            report.append((file, "draft", []))
            continue

        verifiers = []
        for kind in rule["verify"]:
            if kind == "approvers":
                verifiers += list(approvals.items())
            elif kind == "author":
                verifiers.append((author, merged_at))
            elif kind == "merger":
                if merger or not merged:
                    verifiers.append((merger or "whoever merges", merged_at))
            elif kind == "reviewers":
                reviewers = reviewers_of(rule, file, codeowners_file, codeowners_entries)
                if reviewers is None:
                    missing_reviewers.setdefault(", ".join(rule["paths"]), []).append(file)
                else:
                    verifiers += [(login, at) for login, at in approvals.items() if login.lower() in reviewers]
        verifiers = one_entry_per_person((login, at) for login, at in verifiers if not is_bot(login))
        if not verifiers:
            nobody.append(file)
            report.append((file, "draft", []))
            continue
        report.append((file, "stable", [login for login, _ in verifiers]))
        if not merged:
            continue

        head = ["status: stable" if re.match(r"status:", line) else line for line in head]
        head = add_verified(head, verifiers)
        Path(file).write_text("\n".join(["---"] + head + lines[end:]))

        if folder := nearest_log(file):
            title = field(head, "title") or Path(file).stem
            link = "/" + str(Path(file).relative_to(folder))
            who = ", ".join(f"@{login}" for login, _ in verifiers)
            logs.setdefault(folder, []).append(
                f"**Update**: [{title}]({link}) merged in #{number} and marked stable; verified by {who}.")

    for paths, files in missing_reviewers.items():
        warn(f"`{paths}` uses `verify: reviewers`, but no reviewers are defined (no `reviewers` in the rule and no "
             f"CODEOWNERS file): {len(files)} document(s) can't be verified by reviewers.")
    if nobody:
        warn(f"{len(nobody)} document(s) stay draft, because nobody qualifies under their rule's `verify`: "
             f"{', '.join(nobody)}.")
    if keep_status:
        warn(f"The pull request has the `{label}` label: its documents are left as they are.")
    if not merged and (changes := changes_to_the_rules(files_changed, config)):
        warn(f"This pull request changes how its own documents are verified, so review these closely: "
             f"{', '.join(changes)}.")
    for folder, entries in logs.items():
        add_log_entries(folder, entries)

    verb = "Changed" if merged else "On merge"
    lines = [f"### okf-approve: {'merged' if merged else 'preview'} #{number}", ""]
    if report:
        lines += ["| Document | Status | Verified by |", "| --- | --- | --- |"]
        lines += [f"| `{f}` | draft{' → stable' if b == 'stable' else ''} | {', '.join('@' + v for v in vs) or 'nobody'} |"
                  for f, b, vs in report]
    else:
        lines.append("No OKF document matched by the rules.")
    lines += [""] + [f"> {w}" for w in warnings]
    summary = "\n".join(lines) + "\n"
    print(summary)
    if path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(path, "a") as out:
            out.write(summary)
    print(f"{verb}: {sum(1 for _, b, _ in report if b == "stable")} document(s).")


if __name__ == "__main__":
    main()
