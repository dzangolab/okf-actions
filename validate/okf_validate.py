#!/usr/bin/env python3
"""Validate OKF documents against the spec and version each rule names.

For each markdown file in the working tree, the first rule whose paths match it
decides what it is validated against. An `okf` rule checks each file on its own;
an `ai-xf` rule runs the AI-XF reference validator on the bundle the file is in,
the nearest folder above it with a `manifest.ai-xf.yaml`. Errors fail the run;
warnings are only reported.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import okf_0_2  # noqa: E402

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
    sys.exit(f"::error::{message}")


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


def markdown_files():
    return [f for f in git("ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0")
            if f.endswith(".md") and Path(f).exists()]


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


def validate_okf(rule, files):
    checker = SPECS["okf"][rule["version"]]
    for file in files:
        for severity, message in checker.check(file):
            report(severity, file, message)


def validate_ai_xf(rule, files):
    version = rule["version"]
    bundles = set()
    for file in files:
        if (bundle := bundle_of(file)) is None:
            report("error", file, f"not in an AI-XF bundle: no {MANIFEST} in its folder or above (AI-XF {version} §10.3)")
        else:
            bundles.add(bundle)

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

        result = subprocess.run([sys.executable, "-I", str(script), str(bundle), "--level", str(level), "--json"],
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


def main():
    rules = load_rules(os.environ.get("CONFIG", ".github/okf-validate.yml"))
    files, claimed = markdown_files(), set()
    for rule in rules:
        selected = sorted(matching(rule["paths"], files) - claimed)
        claimed |= set(selected)
        if rule["spec"] == "okf":
            validate_okf(rule, selected)
        else:
            validate_ai_xf(rule, selected)

    for severity, file, message in findings:
        print(f"::{severity} file={escape(file, property=True)}::{escape(message)}")

    errors = sum(1 for severity, _, _ in findings if severity == "error")
    lines = ["### okf-validate", "", f"{len(claimed)} document(s) checked: {errors} error(s), "
             f"{len(findings) - errors} warning(s).", ""]
    if findings:
        lines += ["| | Document | Finding |", "| --- | --- | --- |"]
        for severity, file, message in findings:
            message = message.replace("|", r"\|")
            lines.append(f"| {'❌' if severity == 'error' else '⚠️'} | `{file}` | {message} |")
    summary = "\n".join(lines) + "\n"
    print(summary)
    if path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(path, "a") as out:
            out.write(summary)
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
