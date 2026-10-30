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

    def run_action(self, rules=None, expect=0):
        if rules is not None:
            self.write({".github/okf-validate.yml": json.dumps({"rules": rules})})
        env = {**os.environ, "GITHUB_STEP_SUMMARY": ""}
        result = subprocess.run([sys.executable, "-I", str(SCRIPT)], cwd=self.repo, env=env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, expect, result.stdout + result.stderr)
        return result.stdout + result.stderr

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

    def test_ai_xf_declared_version_mismatch_warns(self):
        self.write({"specs/manifest.ai-xf.yaml": "ai-xf: \"0.4\"\nname: specs\n", "specs/a.md": doc("id: a\n")})
        self.assertIn("declares AI-XF 0.4, but the rule validates against 0.5", self.run_action([ai_xf("specs/**")]))


if __name__ == "__main__":
    unittest.main()
