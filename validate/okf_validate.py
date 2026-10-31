#!/usr/bin/env python3
"""Validate OKF documents against the spec and version each rule names.

For each markdown file in the working tree, the first rule whose paths match it
decides what it is validated against. An `okf` rule checks each file on its own;
an `ai-xf` rule runs the AI-XF reference validator on the bundle the file is in,
the nearest folder above it with a `manifest.ai-xf.yaml`, leaving out the
bundle's markdown files the rule doesn't select. Errors fail the run; warnings
are only reported.

Given files, as the pre-commit hook is, it validates those rather than the whole
working tree, and untracked files it wasn't given don't count: `okf` rules check
the given files, and `ai-xf` rules the bundles they are in.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import okf_0_2  # noqa: E402

IN_ACTIONS = os.environ.get("GITHUB_ACTIONS") == "true"
MANIFEST = "manifest.ai-xf.yaml"
VENDOR = HERE / "vendor"
# One entry per supported version: an `okf` checker module, or an `ai-xf`
# reference validator copied into vendor/ai-xf-<version>/.
SPECS = {
    "ai-xf": sorted(p.name[len("ai-xf-"):] for p in VENDOR.glob("ai-xf-*")),
    "okf": {"0.2": okf_0_2},
}

findings = []


def report(severity, file, message):
    findings.append((severity, file, message))


def fail(message):
    sys.exit(f"::error::{message}" if IN_ACTIONS else f"error: {message}")


def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def load_rules(path):
    file = Path(path)
    if not file.exists():
        fail(f"{path} not found: add it to say what to validate against, "
             "see https://github.com/dzangolab/okf-actions/tree/main/validate#rules")
    try:
        config = yaml.safe_load(file.read_text())
    except yaml.YAMLError as error:
        fail(f"{path} isn't valid YAML: {error}".replace("\n", " "))
    rules = (config or {}).get("rules")
    if not isinstance(rules, list) or not rules:
        fail(f"{path}: `rules` must be a non-empty list")
    for i, rule in enumerate(rules):
        where = f"{path}: rules[{i}]"
        if not isinstance(rule, dict) or not rule.get("paths"):
            fail(f"{where}: `paths` is required")
        spec = rule.get("spec")
        if spec not in SPECS:
            fail(f"{where}: `spec` must be one of {sorted(SPECS)}")
        if "version" not in rule:
            fail(f"{where}: `version` is required, e.g. \"{list(SPECS[spec])[-1]}\"")
        rule["version"] = str(rule["version"])
        if rule["version"] not in SPECS[spec]:
            fail(f"{where}: {spec} {rule['version']} isn't supported; supported versions: {', '.join(SPECS[spec])}. "
                 "Quote the version in YAML, e.g. \"0.10\", or it is read as a number.")
        if "level" in rule:
            if spec != "ai-xf":
                fail(f"{where}: `level` only applies to `spec: ai-xf`")
            if rule["level"] not in (0, 1, 2, 3):
                fail(f"{where}: `level` must be 0, 1, 2 or 3")
    return rules


def repository_files():
    return [f for f in git("ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0")
            if f and Path(f).exists()]


def commit_files(targets):
    """The given files and the tracked ones: an untracked file nobody asked about isn't part of the commit."""
    tracked = [f for f in git("ls-files", "-z", "--cached").split("\0") if f and Path(f).exists()]
    return sorted({*tracked, *targets})


def given_files(paths):
    targets = {os.path.relpath(path) for path in paths}
    for target in sorted(targets):
        if not Path(target).is_file():
            fail(f"{target} isn't a file")
    return targets


def matching(globs, files):
    """The files, among `files`, that git's glob pathspecs select; `!` excludes."""
    specs = [f":(glob,exclude){g[1:]}" if g.startswith("!") else f":(glob){g}" for g in globs]
    if not any(not g.startswith("!") for g in globs):
        specs.insert(0, ":(glob)**")
    selected = git("ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", *specs).split("\0")
    return set(selected) & set(files)


def bundle_of(file):
    for folder in Path(file).parents:
        if (folder / MANIFEST).exists():
            return folder
    return None


def in_scope(rule, selected, targets):
    """The selected documents to validate for the given files: those, and for `ai-xf` the rest of their bundles."""
    given = set(selected) & targets
    if rule["spec"] == "okf":
        return sorted(given)
    bundles = {bundle_of(document) for document in given} - {None}
    return sorted(d for d in selected if d in given or bundle_of(d) in bundles)


def validate_okf(rule, documents):
    checker = SPECS["okf"][rule["version"]]
    for document in documents:
        for severity, message in checker.check(document):
            report(severity, document, message)


def bundle_view(bundle, documents, files, into):
    """Link into `into` the bundle's files, leaving out the markdown files the rule doesn't select."""
    for file in files:
        if Path(file).is_relative_to(bundle) and (not file.endswith(".md") or file in documents):
            link = Path(into) / Path(file).relative_to(bundle)
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(Path(file).resolve())


def validate_ai_xf(rule, documents, files):
    version = rule["version"]
    bundles = {}
    for document in documents:
        if (bundle := bundle_of(document)) is None:
            report("error", document, f"not in an AI-XF bundle: no {MANIFEST} in its folder or above (AI-XF {version} §10.3)")
        else:
            bundles.setdefault(bundle, set()).add(document)

    script = VENDOR / f"ai-xf-{version}" / "ai-xf-validate.py"
    for bundle in sorted(bundles):
        manifest_path = bundle / MANIFEST
        try:
            manifest = yaml.safe_load(manifest_path.read_text()) or {}
        except yaml.YAMLError:
            manifest = {}  # the validator reports it
        declared = manifest.get("ai-xf")
        if declared is not None and str(declared) != version:
            report("warning", str(manifest_path), f"declares AI-XF {declared}, but the rule validates against {version}")
        level = rule.get("level", manifest.get("conformance", 1))
        if level not in (0, 1, 2, 3):
            report("error", str(manifest_path), f"`conformance: {level}` must be 0, 1, 2 or 3 (AI-XF {version} §11)")
            continue

        # The validator checks every markdown file in a folder: give it the bundle as the rule selects it.
        with tempfile.TemporaryDirectory() as view:
            bundle_view(bundle, bundles[bundle], files, view)
            result = subprocess.run([sys.executable, "-I", str(script), view, "--level", str(level), "--json"],
                                    capture_output=True, text=True)
        try:
            output = json.loads(result.stdout)
        except json.JSONDecodeError:
            report("error", str(bundle), f"the AI-XF validator failed: {result.stderr.strip() or result.stdout.strip()}")
            continue
        for finding in output["findings"]:
            path = bundle / finding["file"]
            report(finding["severity"], str(path) if path.exists() else str(bundle), finding["message"])
        print(f"{bundle}: AI-XF {version} level {output['achieved_level']} achieved, level {level} checked.")


def escape(value, property=False):
    value = str(value).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return value.replace(":", "%3A").replace(",", "%2C") if property else value


def parse_arguments():
    parser = argparse.ArgumentParser(prog="okf-validate", allow_abbrev=False,
                                     description="Validate OKF documents against the spec and version each rule names.")
    parser.add_argument("--config", default=os.environ.get("CONFIG", ".github/okf-validate.yml"),
                        help="the rules file (default: $CONFIG, else %(default)s)")
    parser.add_argument("files", nargs="*",
                        help="validate these rather than the whole working tree; `ai-xf` rules validate their bundles")
    return parser.parse_args()


def main():
    arguments = parse_arguments()
    rules = load_rules(arguments.config)
    targets = given_files(arguments.files) if arguments.files else None
    files = repository_files() if targets is None else commit_files(targets)
    markdown, claimed, checked = [f for f in files if f.endswith(".md")], set(), set()
    for rule in rules:
        selected = sorted(matching(rule["paths"], markdown) - claimed)
        claimed |= set(selected)
        if targets is not None:
            selected = in_scope(rule, selected, targets)
        checked |= set(selected)
        if rule["spec"] == "okf":
            validate_okf(rule, selected)
        else:
            validate_ai_xf(rule, selected, files)

    if targets is not None:
        for file in sorted(targets - claimed):
            print(f"{file}: skipped, no rule matches it.")
        if others := checked - targets:
            print(f"{len(others)} other document(s) checked, because AI-XF validates whole bundles: "
                  "findings can be about them too.")

    for severity, file, message in findings:
        print(f"::{severity} file={escape(file, property=True)}::{escape(message)}" if IN_ACTIONS
              else f"{file}: {severity}: {message}")

    errors = sum(1 for severity, _, _ in findings if severity == "error")
    count = f"{len(checked)} document(s) checked: {errors} error(s), {len(findings) - errors} warning(s)."
    lines = ["### okf-validate", "", count, ""]
    if findings:
        lines += ["| | Document | Finding |", "| --- | --- | --- |"]
        for severity, file, message in findings:
            message = message.replace("|", r"\|")
            lines.append(f"| {'❌' if severity == 'error' else '⚠️'} | `{file}` | {message} |")
    summary = "\n".join(lines) + "\n"
    print(summary if IN_ACTIONS else count)
    if path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(path, "a") as out:
            out.write(summary)
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
