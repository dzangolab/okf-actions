"""End-to-end tests: each test builds a git repository, a pull_request event and
API fixtures, runs okf_approve.py, and checks the documents, logs and output."""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "approve" / "okf_approve.py"
MERGED_AT = "2026-10-30T10:00:00Z"


def doc(status="draft", title="Doc", extra=""):
    return f"---\n{extra}status: {status}\ntitle: {title}\ntype: Concept\n---\n\n# {title}\n"


class OkfApproveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.fixtures = self.root / "fixtures"
        self.repo.mkdir()
        self.fixtures.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, files):
        for name, content in files.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True)

    def fixture(self, path, data):
        name = re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-") + ".json"
        (self.fixtures / name).write_text(json.dumps(data))

    def run_action(self, changed, reviews=(), merged=True, labels=(), config=None, author="alice", merger="alice"):
        if config is not None:
            self.write({".github/okf-approve.yml": json.dumps(config)})
        self.fixture("repos/o/r/pulls/7/files", [{"filename": f, "status": "modified"} for f in changed])
        self.fixture("repos/o/r/pulls/7/reviews", [
            {"state": state, "submitted_at": at, "user": {"login": login}} for login, state, at in reviews])
        event = {"pull_request": {
            "number": 7, "user": {"login": author}, "merged": merged,
            "merged_at": MERGED_AT if merged else None,
            "merged_by": {"login": merger} if merged else None,
            "labels": [{"name": label} for label in labels]}}
        (self.root / "event.json").write_text(json.dumps(event))
        env = {**os.environ, "GITHUB_EVENT_PATH": str(self.root / "event.json"), "GITHUB_REPOSITORY": "o/r",
               "OKF_APPROVE_FIXTURES": str(self.fixtures), "OKF_APPROVE_TODAY": "2026-10-30",
               "GITHUB_STEP_SUMMARY": str(self.root / "summary.md")}
        result = subprocess.run([sys.executable, "-I", str(SCRIPT)], cwd=self.repo, env=env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def read(self, name):
        return (self.repo / name).read_text()

    def test_kb_owner_approval_verifies(self):
        self.write({"knowledge/auth.md": doc(), "CODEOWNERS": "knowledge/ @carol\n"})
        self.run_action(["knowledge/auth.md"], reviews=[("carol", "APPROVED", "2026-10-30T09:00:00Z")])
        text = self.read("knowledge/auth.md")
        self.assertIn("status: stable", text)
        self.assertIn("verified:\n  - at: 2026-10-30T09:00:00Z\n    by: human:carol", text)

    def test_kb_code_approval_by_non_owner_leaves_unverified(self):
        self.write({"knowledge/auth.md": doc(), "src/app.ts": "x", ".github/CODEOWNERS": "* @bob\nknowledge/ @carol\n"})
        self.run_action(["knowledge/auth.md", "src/app.ts"], reviews=[("bob", "APPROVED", "2026-10-30T09:00:00Z")])
        text = self.read("knowledge/auth.md")
        self.assertIn("status: stable", text)
        self.assertNotIn("verified", text)

    def test_owners_without_any_source_warns(self):
        self.write({"knowledge/auth.md": doc()})
        out = self.run_action(["knowledge/auth.md"], reviews=[("bob", "APPROVED", "2026-10-30T09:00:00Z")])
        self.assertIn("::warning::`knowledge/**, docs/**, **/README.md` uses `verify: owners`", out)
        self.assertNotIn("verified", self.read("knowledge/auth.md"))

    def test_rule_owners_override_codeowners(self):
        self.write({"knowledge/auth.md": doc(), "CODEOWNERS": "knowledge/ @carol\n"})
        self.run_action(["knowledge/auth.md"], reviews=[("dave", "APPROVED", "2026-10-30T09:00:00Z")],
                        config={"rules": [{"paths": ["knowledge/**"], "verify": ["owners"], "owners": ["@dave"]}]})
        self.assertIn("by: human:dave", self.read("knowledge/auth.md"))

    def test_specs_default_records_approvers_not_author(self):
        self.write({"specs/feature-x.md": doc()})
        self.run_action(["specs/feature-x.md"], reviews=[
            ("bob", "APPROVED", "2026-10-30T09:00:00Z"), ("carol", "COMMENTED", "2026-10-30T09:30:00Z")])
        text = self.read("specs/feature-x.md")
        self.assertIn("by: human:bob", text)
        self.assertNotIn("carol", text)
        self.assertNotIn("alice", text)

    def test_author_rule_records_author_at_merge(self):
        self.write({"specs/feature-x.md": doc()})
        self.run_action(["specs/feature-x.md"], config={"rules": [{"paths": ["specs/**"], "verify": ["author"]}]})
        self.assertIn(f"  - at: {MERGED_AT}\n    by: human:alice", self.read("specs/feature-x.md"))

    def test_on_verify_keeps_draft_without_verifier(self):
        self.write({"specs/feature-x.md": doc()})
        self.run_action(["specs/feature-x.md"],
                        config={"rules": [{"paths": ["specs/**"], "verify": ["approvers"], "stable": "on-verify"}]})
        self.assertIn("status: draft", self.read("specs/feature-x.md"))

    def test_latest_review_counts(self):
        self.write({"specs/feature-x.md": doc()})
        self.run_action(["specs/feature-x.md"], reviews=[
            ("bob", "APPROVED", "2026-10-30T09:00:00Z"), ("bob", "DISMISSED", "2026-10-30T09:10:00Z")])
        self.assertNotIn("verified", self.read("specs/feature-x.md"))

    def test_unverified_label_records_nobody(self):
        self.write({"specs/feature-x.md": doc()})
        out = self.run_action(["specs/feature-x.md"], reviews=[("bob", "APPROVED", "2026-10-30T09:00:00Z")],
                              labels=["okf: unverified"])
        text = self.read("specs/feature-x.md")
        self.assertIn("status: stable", text)
        self.assertNotIn("verified", text)
        self.assertIn("label", out)

    def test_stable_doc_gains_owner_verification(self):
        self.write({"knowledge/auth.md": doc(status="stable", extra="verified:\n  - at: 2026-01-01T00:00:00Z\n    by: human:old\n"),
                    "CODEOWNERS": "knowledge/ @carol\n"})
        self.run_action(["knowledge/auth.md"], reviews=[("carol", "APPROVED", "2026-10-30T09:00:00Z")])
        text = self.read("knowledge/auth.md")
        self.assertIn("by: human:old\n  - at: 2026-10-30T09:00:00Z\n    by: human:carol\nstatus: stable", text)

    def test_inline_verified_map_becomes_list(self):
        self.write({"specs/x.md": doc(extra="verified: { by: human:old, at: 2026-01-01T00:00:00Z }\n")})
        self.run_action(["specs/x.md"], reviews=[("bob", "APPROVED", "2026-10-30T09:00:00Z")])
        self.assertIn("verified:\n  - { by: human:old, at: 2026-01-01T00:00:00Z }\n  - at: 2026-10-30T09:00:00Z\n"
                      "    by: human:bob", self.read("specs/x.md"))

    def test_template_placeholder_is_removed(self):
        extra = "# Added on merge by the ai-xf-approve workflow, never by hand:\n# verified:\n#   - at: <ts>\n#     by: human:<x>\n"
        self.write({"specs/x.md": doc(extra=extra)})
        self.run_action(["specs/x.md"], reviews=[("bob", "APPROVED", "2026-10-30T09:00:00Z")])
        self.assertNotIn("#", self.read("specs/x.md").split("---")[1])

    def test_readme_at_any_depth_and_files_outside_rules_untouched(self):
        self.write({"README.md": doc(title="Root"), "pkg/README.md": doc(title="Pkg"), "notes/x.md": doc(),
                    "CODEOWNERS": "* @carol\n"})
        self.run_action(["README.md", "pkg/README.md", "notes/x.md"],
                        reviews=[("carol", "APPROVED", "2026-10-30T09:00:00Z")])
        self.assertIn("by: human:carol", self.read("README.md"))
        self.assertIn("by: human:carol", self.read("pkg/README.md"))
        self.assertIn("status: draft", self.read("notes/x.md"))

    def test_exclude_glob(self):
        self.write({"docs/a.md": doc(), "docs/generated/b.md": doc()})
        self.run_action(["docs/a.md", "docs/generated/b.md"],
                        config={"rules": [{"paths": ["docs/**", "!docs/generated/**"], "verify": ["merger"]}]})
        self.assertIn("by: human:alice", self.read("docs/a.md"))
        self.assertIn("status: draft", self.read("docs/generated/b.md"))

    def test_first_matching_rule_wins(self):
        self.write({"specs/README.md": doc()})
        self.run_action(["specs/README.md"], config={"rules": [
            {"paths": ["specs/**"], "verify": ["author"]}, {"paths": ["**/README.md"], "verify": []}]})
        self.assertIn("by: human:alice", self.read("specs/README.md"))

    def test_log_entries_in_nearest_log(self):
        self.write({"specs/log.md": "# Log\n\n## 2026-10-01\n\n**Initialization**: bundle created.\n",
                    "specs/features/x.md": doc(title="Feature X"), "specs/features/y.md": doc(status="stable")})
        self.run_action(["specs/features/x.md", "specs/features/y.md"])
        self.assertEqual(self.read("specs/log.md"),
                         "# Log\n\n## 2026-10-30\n\n**Update**: [Feature X](/features/x.md) merged in #7 and marked "
                         "stable, unverified.\n\n## 2026-10-01\n\n**Initialization**: bundle created.\n")

    def test_preview_writes_nothing(self):
        self.write({"specs/x.md": doc()})
        out = self.run_action(["specs/x.md"], reviews=[("bob", "APPROVED", "2026-10-30T09:00:00Z")], merged=False)
        self.assertIn("status: draft", self.read("specs/x.md"))
        self.assertIn("| `specs/x.md` | draft → stable | @bob |", out)

    def test_non_okf_markdown_is_skipped(self):
        self.write({"docs/plain.md": "# Plain\n"})
        out = self.run_action(["docs/plain.md"])
        self.assertEqual(self.read("docs/plain.md"), "# Plain\n")
        self.assertIn("Changed: 0 document(s).", out)


if __name__ == "__main__":
    unittest.main()
