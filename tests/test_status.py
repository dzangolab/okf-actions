"""End-to-end tests: each test builds a git repository, runs okf_status.py with the
action's inputs, and checks the documents, logs and output."""

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "status" / "okf_status.py"
ENTRY = r"  - at: \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\n    by: human:alice"


def doc(status="draft", title="Doc", extra=""):
    return f"---\n{extra}status: {status}\ntitle: {title}\ntype: Concept\n---\n\n# {title}\n"


class OkfStatusTest(unittest.TestCase):
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
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True)

    def read(self, name):
        return (self.repo / name).read_text()

    def run_script(self, paths, status="unchanged", verify="false", actor="alice"):
        env = {**os.environ, "GITHUB_ACTOR": actor, "OKF_APPROVE_TODAY": "2026-10-30",
               "PATHS": paths, "STATUS": status, "VERIFY": verify}
        env.pop("GITHUB_STEP_SUMMARY", None)
        return subprocess.run([sys.executable, "-I", str(SCRIPT)], cwd=self.repo, env=env,
                              capture_output=True, text=True)

    def run_action(self, *args, **kwargs):
        result = self.run_script(*args, **kwargs)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_verify_records_the_actor_and_leaves_the_status(self):
        self.write({"knowledge/a.md": doc(status="stable")})
        self.run_action("knowledge/a.md", verify="true")
        text = self.read("knowledge/a.md")
        self.assertIn("status: stable", text)
        self.assertRegex(text, "verified:\n" + ENTRY)

    def test_setting_stable_always_records_the_actor(self):
        self.write({"knowledge/a.md": doc()})
        self.run_action("knowledge/a.md", status="stable")
        text = self.read("knowledge/a.md")
        self.assertIn("status: stable", text)
        self.assertRegex(text, "verified:\n" + ENTRY)

    def test_setting_stable_on_a_stable_page_changes_nothing(self):
        self.write({"knowledge/a.md": doc(status="stable")})
        self.run_action("knowledge/a.md", status="stable")
        self.assertEqual(self.read("knowledge/a.md"), doc(status="stable"))

    def test_setting_draft_or_deprecated_records_nobody(self):
        for status in ("deprecated", "draft"):
            with self.subTest(status=status):
                self.write({"knowledge/a.md": doc(status="stable")})
                self.run_action("knowledge/a.md", status=status)
                text = self.read("knowledge/a.md")
                self.assertIn(f"status: {status}", text)
                self.assertNotIn("verified", text)

    def test_a_status_can_be_combined_with_verify(self):
        self.write({"knowledge/a.md": doc(status="stable")})
        self.run_action("knowledge/a.md", status="deprecated", verify="true")
        text = self.read("knowledge/a.md")
        self.assertIn("status: deprecated", text)
        self.assertRegex(text, "verified:\n" + ENTRY)

    def test_a_page_without_status_gains_one(self):
        self.write({"knowledge/a.md": "---\ntitle: A\n---\n"})
        self.run_action("knowledge/a.md", status="draft")
        self.assertEqual(self.read("knowledge/a.md"), "---\ntitle: A\nstatus: draft\n---\n")

    def test_existing_verified_entries_are_kept(self):
        self.write({"knowledge/a.md": doc(status="stable", extra="verified:\n  - at: 2026-01-01T00:00:00Z\n    by: human:old\n")})
        self.run_action("knowledge/a.md", verify="true")
        self.assertRegex(self.read("knowledge/a.md"), "by: human:old\n" + ENTRY)

    def test_globs_excludes_and_several_paths(self):
        self.write({"knowledge/a.md": doc(), "knowledge/sub/b.md": doc(), "knowledge/skip/c.md": doc(),
                    "docs/d.md": doc(), "notes/e.md": doc(), "knowledge/data.txt": "x"})
        self.run_action("knowledge/**, !knowledge/skip/** docs/d.md", status="stable")
        for name in ("knowledge/a.md", "knowledge/sub/b.md", "docs/d.md"):
            self.assertIn("status: stable", self.read(name))
        for name in ("knowledge/skip/c.md", "notes/e.md"):
            self.assertIn("status: draft", self.read(name))

    def test_index_log_and_non_okf_files_are_skipped(self):
        self.write({"docs/index.md": doc(), "docs/log.md": "# Log\n", "docs/plain.md": "# Plain\n", "docs/a.md": doc()})
        self.run_action("docs/**", status="stable")
        self.assertEqual(self.read("docs/index.md"), doc())
        self.assertEqual(self.read("docs/plain.md"), "# Plain\n")
        self.assertIn("status: stable", self.read("docs/a.md"))

    def test_log_entries(self):
        for status, verify, how in (
                ("stable", "false", "marked stable; verified by @alice."),
                ("draft", "false", "marked draft by @alice."),
                ("unchanged", "true", "verified by @alice.")):
            with self.subTest(status=status):
                start = "draft" if status == "stable" else "stable"
                self.write({"docs/log.md": "# Log\n", "docs/a.md": doc(status=start, title="A")})
                self.run_action("docs/a.md", status=status, verify=verify)
                self.assertEqual(self.read("docs/log.md"), f"# Log\n\n## 2026-10-30\n\n**Update**: [A](/a.md) {how}\n")

    def test_summary_reports_the_change(self):
        self.write({"docs/a.md": doc()})
        self.assertIn("| `docs/a.md` | draft → stable | @alice |", self.run_action("docs/a.md", status="stable"))

    def test_invalid_requests_are_rejected(self):
        self.write({"docs/a.md": doc()})
        for kwargs, message in (
                ({"paths": ""}, "`paths` is required"),
                ({"paths": "docs/a.md"}, "Nothing to do"),
                ({"paths": "docs/a.md", "status": "published"}, "`status` must be one of"),
                ({"paths": "nowhere/**", "status": "draft"}, "No document matches"),
                ({"paths": "docs/a.md", "status": "stable", "actor": "renovate[bot]"}, "is a bot"),
                ({"paths": "docs/a.md", "verify": "true", "actor": "renovate[bot]"}, "is a bot")):
            with self.subTest(kwargs=kwargs):
                result = self.run_script(**kwargs)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stdout + result.stderr)
        self.assertEqual(self.read("docs/a.md"), doc())


if __name__ == "__main__":
    unittest.main()
