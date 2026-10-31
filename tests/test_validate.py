"""End-to-end tests: each test builds a git repository with documents and rules,
runs okf_validate.py, and checks its exit code and findings. Needs PyYAML, from
validate/requirements.txt."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "validate" / "okf_validate.py"


def doc(extra="", kind="Concept"):
    return f"---\n{extra}title: Doc\ntype: {kind}\n---\n\n# Doc\n"


def okf(*paths):
    return {"paths": list(paths), "spec": "okf", "version": "0.2"}


def ai_xf(*paths, **options):
    return {"paths": list(paths), "spec": "ai-xf", "version": "0.5", **options}


class OkfValidateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, files):
        for name, content in files.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)

    def track(self):
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True)

    def run_script(self, *args, rules=None, expect=0, env=None):
        if rules is not None:
            self.write({".github/okf-validate.yml": json.dumps({"rules": rules})})
        result = subprocess.run([sys.executable, "-I", str(SCRIPT), *args], cwd=self.repo, env=env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, expect, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def run_action(self, rules=None, expect=0):
        """Runs it as action.yml does: no arguments, inside GitHub Actions."""
        env = {**os.environ, "GITHUB_ACTIONS": "true", "GITHUB_STEP_SUMMARY": ""}
        return self.run_script(rules=rules, expect=expect, env=env)

    def run_cli(self, *args, rules=None, expect=0, **variables):
        """Runs it as the pre-commit hook or a person does: outside GitHub Actions."""
        env = {k: v for k, v in os.environ.items() if k not in ("CONFIG", "GITHUB_ACTIONS", "GITHUB_STEP_SUMMARY")}
        return self.run_script(*args, rules=rules, expect=expect, env={**env, **variables})

    def test_conformant_okf_document_passes(self):
        self.write({"docs/a.md": doc("status: draft\nverified:\n  - { by: human:carol, at: 2026-10-30T09:00:00Z }\n")})
        self.assertIn("1 document(s) checked: 0 error(s), 0 warning(s)", self.run_action([okf("docs/**")]))

    def test_missing_frontmatter_fails(self):
        self.write({"docs/a.md": "# A\n"})
        self.assertIn("::error file=docs/a.md::no YAML frontmatter", self.run_action([okf("docs/**")], expect=1))

    def test_missing_type_fails(self):
        self.write({"docs/a.md": "---\ntitle: A\n---\n"})
        self.assertIn("`type` is required", self.run_action([okf("docs/**")], expect=1))

    def test_invalid_yaml_fails(self):
        self.write({"docs/a.md": "---\ntype: [Concept\n---\n"})
        self.assertIn("isn't valid YAML", self.run_action([okf("docs/**")], expect=1))

    def test_soft_rules_only_warn(self):
        self.write({"docs/a.md": doc("status: final\ngenerated: { by: claude }\n")})
        out = self.run_action([okf("docs/**")])
        self.assertIn("::warning file=docs/a.md::`status: final`", out)
        self.assertIn("`generated.by` `claude` isn't an actor", out)

    def test_bare_verified_mapping_is_accepted(self):
        self.write({"docs/a.md": doc("verified: { by: human:carol, at: 2026-10-30T09:00:00Z }\n")})
        self.assertIn("0 warning(s)", self.run_action([okf("docs/**")]))

    def test_index_frontmatter_only_okf_version(self):
        self.write({"docs/index.md": "---\nokf_version: \"0.2\"\n---\n\n# Docs\n", "docs/a/index.md": "---\ntitle: A\n---\n"})
        out = self.run_action([okf("docs/**")], expect=1)
        self.assertIn("::error file=docs/a/index.md::", out)
        self.assertNotIn("file=docs/index.md", out)

    def test_log_date_headings(self):
        self.write({"docs/log.md": "# Log\n\n## 2026-10-01\n\n## 2026-10-30\n\n## October\n"})
        out = self.run_action([okf("docs/**")], expect=1)
        self.assertIn("`## October`: date headings use `## YYYY-MM-DD`", out)
        self.assertIn("newest first", out)

    def test_first_matching_rule_wins_and_unmatched_files_are_skipped(self):
        self.write({"docs/plain.md": "# Plain\n", "docs/a.md": doc(), "notes/x.md": "# X\n"})
        out = self.run_action([okf("docs/a.md"), okf("docs/**", "!docs/plain.md")])
        self.assertIn("1 document(s) checked: 0 error(s)", out)

    def test_missing_config_fails(self):
        self.assertIn("okf-validate.yml not found", self.run_action(expect=1))

    def test_unsupported_version_fails(self):
        out = self.run_action([{**okf("docs/**"), "version": "0.1"}], expect=1)
        self.assertIn("okf 0.1 isn't supported; supported versions: 0.2", out)

    def test_okf_version_defaults_to_0_2(self):
        self.write({"docs/a.md": doc()})
        rule = {"paths": ["docs/**"], "spec": "okf"}
        self.assertIn("1 document(s) checked: 0 error(s)", self.run_action([rule]))

    def test_ai_xf_version_defaults_to_0_5(self):
        self.write({"specs/manifest.ai-xf.yaml": "ai-xf: \"0.4\"\nname: specs\n", "specs/a.md": doc("id: a\n")})
        rule = {"paths": ["specs/**"], "spec": "ai-xf"}
        out = self.run_action([rule])
        self.assertIn("declares AI-XF 0.4, but the rule validates against 0.5", out)
        self.assertIn("specs: AI-XF 0.5 level 1 achieved", out)

    def test_level_is_for_ai_xf_only(self):
        self.assertIn("`level` only applies", self.run_action([{**okf("docs/**"), "level": 1}], expect=1))

    def test_ai_xf_document_outside_a_bundle_fails(self):
        self.write({"specs/a.md": doc("id: a\n")})
        self.assertIn("not in an AI-XF bundle", self.run_action([ai_xf("specs/**")], expect=1))

    def test_ai_xf_bundle_at_manifest_level(self):
        self.write({"specs/manifest.ai-xf.yaml": "ai-xf: \"0.5\"\nname: specs\nconformance: 1\n",
                    "specs/a.md": doc("id: a\n"), "specs/b/c.md": doc("id: c\n")})
        out = self.run_action([ai_xf("specs/**")])
        self.assertIn("specs: AI-XF 0.5 level 1 achieved, level 1 checked.", out)

    def test_ai_xf_errors_point_at_the_document(self):
        self.write({"specs/manifest.ai-xf.yaml": "ai-xf: \"0.5\"\nname: specs\n",
                    "specs/a.md": doc("id: a\n"), "specs/b.md": doc("id: a\n")})
        self.assertIn("::error file=specs/b.md::duplicate id `a`", self.run_action([ai_xf("specs/**")], expect=1))

    def test_ai_xf_rule_level_overrides_manifest(self):
        self.write({"specs/manifest.ai-xf.yaml": "ai-xf: \"0.5\"\nname: specs\nconformance: 1\n",
                    "specs/a.md": doc("id: a\n")})
        self.run_action([ai_xf("specs/**", level=2)], expect=1)

    def test_ai_xf_bundle_leaves_out_excluded_documents(self):
        self.write({"kb/manifest.ai-xf.yaml": "ai-xf: \"0.5\"\nname: kb\nconformance: 0\n",
                    "kb/wiki/a.md": doc(), "kb/raw/original.md": "# An original\n"})
        self.run_action([ai_xf("kb/**")], expect=1)
        self.assertIn("0 error(s)", self.run_action([ai_xf("kb/**", "!kb/raw/**")]))

    def test_ai_xf_bundle_at_the_repository_root(self):
        self.write({"manifest.ai-xf.yaml": "ai-xf: \"0.5\"\nname: root\n", "a.md": doc("id: a\n"),
                    "notes/b.md": "# B\n"})
        self.assertIn(".: AI-XF 0.5 level 1 achieved", self.run_action([ai_xf("**", "!notes/**")]))

    def test_ai_xf_declared_version_mismatch_warns(self):
        self.write({"specs/manifest.ai-xf.yaml": "ai-xf: \"0.4\"\nname: specs\n", "specs/a.md": doc("id: a\n")})
        self.assertIn("declares AI-XF 0.4, but the rule validates against 0.5", self.run_action([ai_xf("specs/**")]))

    def test_config_option_names_the_rules_file(self):
        self.write({"docs/a.md": doc(), "rules.yml": json.dumps({"rules": [okf("docs/**")]})})
        self.assertIn("1 document(s) checked", self.run_cli("--config", "rules.yml"))

    def test_config_option_wins_over_the_environment(self):
        self.write({"docs/a.md": doc(), "rules.yml": json.dumps({"rules": [okf("docs/**")]})})
        self.assertIn("1 document(s) checked", self.run_cli("--config", "rules.yml", CONFIG="missing.yml"))

    def test_config_environment_variable_names_the_rules_file(self):
        self.write({"docs/a.md": doc(), "rules.yml": json.dumps({"rules": [okf("docs/**")]})})
        self.assertIn("1 document(s) checked", self.run_cli(CONFIG="rules.yml"))
        self.assertIn("missing.yml not found", self.run_cli(CONFIG="missing.yml", expect=1))

    def test_config_option_with_missing_file_fails(self):
        self.assertIn("missing.yml not found", self.run_cli("--config", "missing.yml", expect=1))

    def test_without_files_tracked_and_untracked_files_are_validated(self):
        self.write({"docs/tracked.md": "# Tracked\n"})
        self.track()
        self.write({"docs/untracked.md": "# Untracked\n"})
        out = self.run_cli(rules=[okf("docs/**")], expect=1)
        self.assertIn("docs/tracked.md: error:", out)
        self.assertIn("docs/untracked.md: error:", out)
        self.assertIn("2 document(s) checked: 2 error(s)", out)

    def test_given_file_alone_is_validated(self):
        self.write({"docs/good.md": doc(), "docs/tracked.md": "# Broken\n"})
        self.track()
        self.write({"docs/untracked.md": "# Half-written\n"})
        out = self.run_cli("docs/good.md", rules=[okf("docs/**")])
        self.assertIn("1 document(s) checked: 0 error(s), 0 warning(s).", out)
        self.assertNotIn("docs/tracked.md", out)
        self.assertNotIn("docs/untracked.md", out)

    def test_given_broken_file_fails(self):
        self.write({"docs/bad.md": "# Bad\n", "docs/good.md": doc()})
        out = self.run_cli("docs/bad.md", "docs/good.md", rules=[okf("docs/**")], expect=1)
        self.assertIn("docs/bad.md: error: no YAML frontmatter", out)
        self.assertIn("2 document(s) checked: 1 error(s), 0 warning(s).", out)

    def test_given_untracked_file_is_validated(self):
        self.write({"docs/new.md": "# New\n"})
        self.assertIn("docs/new.md: error:", self.run_cli("docs/new.md", rules=[okf("docs/**")], expect=1))

    def test_given_file_no_rule_matches_is_skipped(self):
        self.write({"docs/excluded.md": "# Excluded\n", "docs/picture.png": "", "notes/x.md": "# X\n"})
        out = self.run_cli("docs/excluded.md", "docs/picture.png", "notes/x.md", rules=[okf("docs/**", "!docs/excluded.md")])
        self.assertIn("docs/excluded.md: skipped, no rule matches it.", out)
        self.assertIn("docs/picture.png: skipped, no rule matches it.", out)
        self.assertIn("notes/x.md: skipped, no rule matches it.", out)
        self.assertIn("0 document(s) checked: 0 error(s), 0 warning(s).", out)

    def test_given_file_keeps_to_the_first_matching_rule(self):
        self.write({"docs/a.md": doc()})
        out = self.run_cli("docs/a.md", rules=[okf("docs/a.md"), ai_xf("docs/**")])
        self.assertIn("1 document(s) checked: 0 error(s)", out)

    def test_given_path_is_normalised(self):
        self.write({"docs/bad.md": "# Bad\n"})
        out = self.run_cli("./docs/bad.md", rules=[okf("docs/**")], expect=1)
        self.assertIn("docs/bad.md: error:", out)
        self.assertNotIn("./docs", out)

    def test_given_path_that_is_not_a_file_fails(self):
        self.write({"docs/a.md": doc()})
        rules = [okf("docs/**")]
        self.assertIn("error: docs/missing.md isn't a file", self.run_cli("docs/missing.md", rules=rules, expect=1))
        self.assertIn("error: docs isn't a file", self.run_cli("docs", rules=rules, expect=1))

    def test_given_file_validates_its_ai_xf_bundle(self):
        self.write({"specs/manifest.ai-xf.yaml": "ai-xf: \"0.5\"\nname: specs\n",
                    "specs/a.md": doc("id: a\n"), "specs/b.md": doc("id: b\n"), "specs/c/d.md": doc("id: d\n")})
        self.track()
        out = self.run_cli("specs/a.md", rules=[ai_xf("specs/**")])
        self.assertIn("specs: AI-XF 0.5 level 1 achieved, level 1 checked.", out)
        self.assertIn("2 other document(s) checked, because AI-XF validates whole bundles", out)
        self.assertIn("3 document(s) checked: 0 error(s)", out)

    def test_ai_xf_finding_about_a_tracked_document_not_given_fails(self):
        self.write({"specs/manifest.ai-xf.yaml": "ai-xf: \"0.5\"\nname: specs\n",
                    "specs/a.md": doc("id: a\n"), "specs/b.md": doc("id: a\n")})
        self.track()
        out = self.run_cli("specs/a.md", rules=[ai_xf("specs/**")], expect=1)
        self.assertIn("specs/b.md: error: duplicate id `a`", out)

    def test_ai_xf_bundles_of_files_not_given_are_left_alone(self):
        self.write({"specs/one/manifest.ai-xf.yaml": "ai-xf: \"0.5\"\nname: one\n", "specs/one/a.md": doc("id: a\n"),
                    "specs/two/manifest.ai-xf.yaml": "ai-xf: \"0.5\"\nname: two\n", "specs/two/b.md": "# Broken\n"})
        self.track()
        out = self.run_cli("specs/one/a.md", rules=[ai_xf("specs/**")])
        self.assertIn("specs/one: AI-XF", out)
        self.assertNotIn("specs/two", out)

    def test_ai_xf_untracked_document_not_given_does_not_block(self):
        self.write({"specs/manifest.ai-xf.yaml": "ai-xf: \"0.5\"\nname: specs\n", "specs/a.md": doc("id: a\n")})
        self.track()
        self.write({"specs/draft.md": "# Half-written\n"})
        rules = [ai_xf("specs/**")]
        self.assertIn("1 document(s) checked: 0 error(s)", self.run_cli("specs/a.md", rules=rules))
        self.assertIn("specs/draft.md: error:", self.run_cli("specs/draft.md", rules=rules, expect=1))
        self.run_cli(rules=rules, expect=1)

    def test_ai_xf_untracked_manifest_is_missing_for_the_commit(self):
        self.write({"specs/manifest.ai-xf.yaml": "ai-xf: \"0.5\"\nname: specs\n", "specs/a.md": doc("id: a\n")})
        rules = [ai_xf("specs/**")]
        self.run_cli(rules=rules)
        self.assertIn("missing manifest.ai-xf.yaml", self.run_cli("specs/a.md", rules=rules, expect=1))

    def test_ai_xf_rule_selection_applies_with_given_files(self):
        self.write({"kb/manifest.ai-xf.yaml": "ai-xf: \"0.5\"\nname: kb\nconformance: 0\n",
                    "kb/wiki/a.md": doc(), "kb/raw/original.md": "# An original\n"})
        self.track()
        self.run_cli("kb/wiki/a.md", rules=[ai_xf("kb/**")], expect=1)
        rules = [ai_xf("kb/**", "!kb/raw/**")]
        self.assertIn("1 document(s) checked: 0 error(s)", self.run_cli("kb/wiki/a.md", rules=rules))
        self.assertIn("kb/raw/original.md: skipped, no rule matches it.", self.run_cli("kb/raw/original.md", rules=rules))

    def test_ai_xf_given_file_outside_a_bundle_fails_alone(self):
        self.write({"specs/a.md": doc("id: a\n"), "specs/b.md": doc("id: b\n")})
        self.track()
        out = self.run_cli("specs/a.md", rules=[ai_xf("specs/**")], expect=1)
        self.assertIn("specs/a.md: error: not in an AI-XF bundle", out)
        self.assertNotIn("specs/b.md", out)
        self.assertIn("1 document(s) checked: 1 error(s)", out)

    def test_plain_output_outside_github_actions(self):
        self.write({"docs/bad.md": "# Bad\n", "docs/warned.md": doc("status: final\n")})
        out = self.run_cli(rules=[okf("docs/**")], expect=1)
        self.assertIn("docs/bad.md: error: no YAML frontmatter", out)
        self.assertIn("docs/warned.md: warning: `status: final`", out)
        self.assertIn("2 document(s) checked: 1 error(s), 1 warning(s).", out)
        self.assertNotIn("::", out)
        self.assertNotIn("### okf-validate", out)
        self.assertNotIn("| Document |", out)

    def test_plain_output_only_warnings_exit_zero(self):
        self.write({"docs/warned.md": doc("status: final\n")})
        self.assertIn("0 error(s), 1 warning(s).", self.run_cli(rules=[okf("docs/**")]))

    def test_plain_output_of_a_configuration_failure(self):
        out = self.run_cli(expect=1)
        self.assertTrue(out.startswith("error: .github/okf-validate.yml not found"), out)

    def test_github_actions_output_is_kept(self):
        self.write({"docs/bad.md": "# Bad\n", "docs/warned.md": doc("status: final\n")})
        out = self.run_action([okf("docs/**")], expect=1)
        self.assertIn("::error file=docs/bad.md::no YAML frontmatter", out)
        self.assertIn("::warning file=docs/warned.md::`status: final`", out)
        self.assertIn("### okf-validate\n\n2 document(s) checked: 1 error(s), 1 warning(s).\n\n| | Document | Finding |", out)

    def test_github_actions_output_of_a_configuration_failure(self):
        self.assertTrue(self.run_action(expect=1).startswith("::error::.github/okf-validate.yml not found"))

    def test_github_actions_output_with_given_files(self):
        self.write({"docs/bad.md": "# Bad\n"})
        env = {**os.environ, "GITHUB_ACTIONS": "true", "GITHUB_STEP_SUMMARY": ""}
        out = self.run_script("docs/bad.md", rules=[okf("docs/**")], expect=1, env=env)
        self.assertIn("::error file=docs/bad.md::no YAML frontmatter", out)

    def test_step_summary_is_written(self):
        self.write({"docs/a.md": doc()})
        summary = self.repo / "summary.md"
        self.run_cli(rules=[okf("docs/**")], GITHUB_STEP_SUMMARY=str(summary))
        self.assertIn("### okf-validate", summary.read_text())


if __name__ == "__main__":
    unittest.main()
