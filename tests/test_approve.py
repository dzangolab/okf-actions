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
APPROVED_AT = "2026-10-30T09:00:00Z"
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

    def run_script(self, changed, reviews=(), merged=True, labels=(), config=None, author="alice", merger="alice", env=None):
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
        full_env = {**os.environ, "GITHUB_EVENT_PATH": str(self.root / "event.json"), "GITHUB_REPOSITORY": "o/r",
                    "OKF_APPROVE_FIXTURES": str(self.fixtures), "OKF_APPROVE_TODAY": "2026-10-30",
                    "GITHUB_STEP_SUMMARY": str(self.root / "summary.md"), **(env or {})}
        return subprocess.run([sys.executable, "-I", str(SCRIPT)], cwd=self.repo, env=full_env,
                              capture_output=True, text=True)

    def run_action(self, changed, **kwargs):
        result = self.run_script(changed, **kwargs)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def read(self, name):
        return (self.repo / name).read_text()

    def test_default_records_approvers_and_merger(self):
        self.write({"knowledge/auth.md": doc()})
        self.run_action(["knowledge/auth.md"], reviews=[("bob", "APPROVED", APPROVED_AT)], merger="carol")
        text = self.read("knowledge/auth.md")
        self.assertIn("status: stable", text)
        self.assertIn(f"verified:\n  - at: {APPROVED_AT}\n    by: human:bob\n  - at: {MERGED_AT}\n    by: human:carol", text)

    def test_default_single_dev_is_verified_by_merging(self):
        self.write({"specs/x.md": doc()})
        self.run_action(["specs/x.md"])
        text = self.read("specs/x.md")
        self.assertIn("status: stable", text)
        self.assertIn(f"  - at: {MERGED_AT}\n    by: human:alice", text)

    def test_default_ignores_codeowners(self):
        self.write({"knowledge/auth.md": doc(), "CODEOWNERS": "knowledge/ @carol\n"})
        out = self.run_action(["knowledge/auth.md"], reviews=[("bob", "APPROVED", APPROVED_AT)])
        self.assertIn("by: human:bob", self.read("knowledge/auth.md"))
        self.assertNotIn("::warning::", out)

    def test_approver_who_merges_is_recorded_once_at_merge(self):
        self.write({"specs/x.md": doc()})
        self.run_action(["specs/x.md"], reviews=[("bob", "APPROVED", APPROVED_AT)], merger="bob")
        text = self.read("specs/x.md")
        self.assertEqual(text.count("by: human:bob"), 1)
        self.assertIn(f"  - at: {MERGED_AT}\n    by: human:bob", text)

    def test_only_draft_pages_are_handled(self):
        pages = {"docs/stable.md": doc(status="stable"), "docs/deprecated.md": doc(status="deprecated"),
                 "docs/none.md": "---\ntitle: None\n---\n"}
        self.write(pages)
        self.run_action(list(pages), reviews=[("bob", "APPROVED", APPROVED_AT)])
        for name, content in pages.items():
            self.assertEqual(self.read(name), content)

    def test_page_the_pull_request_did_not_change_is_untouched(self):
        self.write({"docs/a.md": doc(), "docs/b.md": doc()})
        self.run_action(["docs/a.md"])
        self.assertIn("status: stable", self.read("docs/a.md"))
        self.assertIn("status: draft", self.read("docs/b.md"))

    def test_approvers_level_without_approval_stays_draft_and_warns(self):
        self.write({"specs/x.md": doc()})
        out = self.run_action(["specs/x.md"], config={"rules": [{"paths": ["specs/**"], "verify": ["approvers"]}]})
        text = self.read("specs/x.md")
        self.assertIn("status: draft", text)
        self.assertNotIn("verified", text)
        self.assertIn("::warning::1 document(s) stay draft", out)

    def test_approvers_level_does_not_record_merger(self):
        self.write({"specs/x.md": doc()})
        self.run_action(["specs/x.md"], reviews=[("bob", "APPROVED", APPROVED_AT)], merger="carol",
                        config={"rules": [{"paths": ["specs/**"], "verify": ["approvers"]}]})
        text = self.read("specs/x.md")
        self.assertIn("by: human:bob", text)
        self.assertNotIn("carol", text)

    def test_author_cannot_be_recorded_as_approver(self):
        self.write({"specs/x.md": doc()})
        self.run_action(["specs/x.md"], reviews=[("alice", "APPROVED", APPROVED_AT)],
                        config={"rules": [{"paths": ["specs/**"], "verify": ["approvers"]}]})
        self.assertIn("status: draft", self.read("specs/x.md"))

    def test_reviewers_level_from_codeowners(self):
        self.write({"knowledge/auth.md": doc(), "CODEOWNERS": "knowledge/ @carol\n"})
        self.run_action(["knowledge/auth.md"], reviews=[("carol", "APPROVED", APPROVED_AT)],
                        config={"rules": [{"paths": ["knowledge/**"], "verify": ["reviewers"]}]})
        text = self.read("knowledge/auth.md")
        self.assertIn("status: stable", text)
        self.assertIn(f"verified:\n  - at: {APPROVED_AT}\n    by: human:carol", text)

    def test_reviewers_level_approval_by_someone_else_stays_draft(self):
        self.write({"knowledge/auth.md": doc(), "src/app.ts": "x", ".github/CODEOWNERS": "* @bob\nknowledge/ @carol\n"})
        self.run_action(["knowledge/auth.md", "src/app.ts"], reviews=[("bob", "APPROVED", APPROVED_AT)],
                        config={"rules": [{"paths": ["knowledge/**"], "verify": ["reviewers"]}]})
        text = self.read("knowledge/auth.md")
        self.assertIn("status: draft", text)
        self.assertNotIn("verified", text)

    def test_reviewers_without_any_source_warns(self):
        self.write({"knowledge/auth.md": doc()})
        out = self.run_action(["knowledge/auth.md"], reviews=[("bob", "APPROVED", APPROVED_AT)],
                              config={"rules": [{"paths": ["knowledge/**"], "verify": ["reviewers"]}]})
        self.assertIn("::warning::`knowledge/**` uses `verify: reviewers`", out)
        self.assertIn("status: draft", self.read("knowledge/auth.md"))

    def test_rule_reviewers_override_codeowners(self):
        self.write({"knowledge/auth.md": doc(), "CODEOWNERS": "knowledge/ @carol\n"})
        self.run_action(["knowledge/auth.md"], reviews=[("dave", "APPROVED", APPROVED_AT)],
                        config={"rules": [{"paths": ["knowledge/**"], "verify": ["reviewers"], "reviewers": ["@dave"]}]})
        self.assertIn("by: human:dave", self.read("knowledge/auth.md"))

    def test_reviewers_match_whatever_the_case(self):
        self.write({"knowledge/auth.md": doc()})
        self.run_action(["knowledge/auth.md"], reviews=[("Dave", "APPROVED", APPROVED_AT)],
                        config={"rules": [{"paths": ["knowledge/**"], "verify": ["reviewers"], "reviewers": ["@dAVE"]}]})
        self.assertIn("by: human:Dave", self.read("knowledge/auth.md"))

    def test_reviewers_include_team_members(self):
        self.fixture("orgs/o/teams/seniors/members", [{"login": "carol"}])
        self.write({"knowledge/auth.md": doc()})
        self.run_action(["knowledge/auth.md"], reviews=[("carol", "APPROVED", APPROVED_AT)],
                        config={"rules": [{"paths": ["knowledge/**"], "verify": ["reviewers"], "reviewers": ["@o/seniors"]}]})
        self.assertIn("by: human:carol", self.read("knowledge/auth.md"))

    def test_unreadable_team_warns(self):
        self.write({"knowledge/auth.md": doc()})
        out = self.run_action(["knowledge/auth.md"], reviews=[("carol", "APPROVED", APPROVED_AT)],
                              config={"rules": [{"paths": ["knowledge/**"], "verify": ["reviewers"], "reviewers": ["@o/seniors"]}]})
        self.assertIn("Couldn't read the members of @o/seniors", out)
        self.assertIn("status: draft", self.read("knowledge/auth.md"))

    def test_author_rule_records_author_at_merge(self):
        self.write({"specs/feature-x.md": doc()})
        self.run_action(["specs/feature-x.md"], merger="carol",
                        config={"rules": [{"paths": ["specs/**"], "verify": ["author"]}]})
        text = self.read("specs/feature-x.md")
        self.assertIn(f"  - at: {MERGED_AT}\n    by: human:alice", text)
        self.assertNotIn("carol", text)

    def test_rule_without_verify_uses_the_default(self):
        self.write({"notes/x.md": doc()})
        self.run_action(["notes/x.md"], reviews=[("bob", "APPROVED", APPROVED_AT)], merger="carol",
                        config={"rules": [{"paths": ["notes/**"]}]})
        text = self.read("notes/x.md")
        self.assertIn("by: human:bob", text)
        self.assertIn("by: human:carol", text)

    def test_bots_are_never_recorded(self):
        self.write({"specs/x.md": doc()})
        out = self.run_action(["specs/x.md"], reviews=[("reviewer[bot]", "APPROVED", APPROVED_AT)],
                              author="dependabot[bot]", merger="mergify[bot]",
                              config={"rules": [{"paths": ["specs/**"], "verify": ["approvers", "author", "merger"]}]})
        text = self.read("specs/x.md")
        self.assertIn("status: draft", text)
        self.assertNotIn("verified", text)
        self.assertIn("stay draft", out)

    def test_stable_never_leaves_pages_alone(self):
        self.write({"specs/x.md": doc()})
        self.run_action(["specs/x.md"], reviews=[("bob", "APPROVED", APPROVED_AT)],
                        config={"rules": [{"paths": ["specs/**"], "stable": "never"}]})
        self.assertEqual(self.read("specs/x.md"), doc())

    def test_keep_status_label_leaves_pages_alone(self):
        self.write({"specs/log.md": "# Log\n", "specs/x.md": doc()})
        out = self.run_action(["specs/x.md"], reviews=[("bob", "APPROVED", APPROVED_AT)], labels=["okf: keep-status"])
        self.assertEqual(self.read("specs/x.md"), doc())
        self.assertEqual(self.read("specs/log.md"), "# Log\n")
        self.assertIn("`okf: keep-status` label", out)

    def test_keep_status_label_can_be_renamed(self):
        self.write({"specs/x.md": doc()})
        self.run_action(["specs/x.md"], labels=["wip"], env={"KEEP_STATUS_LABEL": "wip"})
        self.assertEqual(self.read("specs/x.md"), doc())

    def test_latest_review_counts(self):
        self.write({"specs/feature-x.md": doc()})
        self.run_action(["specs/feature-x.md"], reviews=[
            ("bob", "APPROVED", APPROVED_AT), ("bob", "DISMISSED", "2026-10-30T09:10:00Z"),
            ("carol", "COMMENTED", "2026-10-30T09:30:00Z")])
        text = self.read("specs/feature-x.md")
        self.assertNotIn("bob", text)
        self.assertNotIn("carol", text)

    def test_existing_verified_entries_are_kept(self):
        self.write({"knowledge/auth.md": doc(extra="verified:\n  - at: 2026-01-01T00:00:00Z\n    by: human:old\n")})
        self.run_action(["knowledge/auth.md"])
        self.assertIn(f"by: human:old\n  - at: {MERGED_AT}\n    by: human:alice\nstatus: stable", self.read("knowledge/auth.md"))

    def test_inline_verified_map_becomes_list(self):
        self.write({"specs/x.md": doc(extra="verified: { by: human:old, at: 2026-01-01T00:00:00Z }\n")})
        self.run_action(["specs/x.md"], reviews=[("bob", "APPROVED", APPROVED_AT)], merger="bob")
        self.assertIn("verified:\n  - { by: human:old, at: 2026-01-01T00:00:00Z }\n"
                      f"  - at: {MERGED_AT}\n    by: human:bob", self.read("specs/x.md"))

    def test_template_placeholder_is_removed(self):
        extra = "# Added on merge by the ai-xf-approve workflow, never by hand:\n# verified:\n#   - at: <ts>\n#     by: human:<x>\n"
        self.write({"specs/x.md": doc(extra=extra)})
        self.run_action(["specs/x.md"])
        self.assertNotIn("#", self.read("specs/x.md").split("---")[1])

    def test_readme_at_any_depth_and_files_outside_rules_untouched(self):
        self.write({"README.md": doc(title="Root"), "pkg/README.md": doc(title="Pkg"), "notes/x.md": doc()})
        self.run_action(["README.md", "pkg/README.md", "notes/x.md"])
        self.assertIn("by: human:alice", self.read("README.md"))
        self.assertIn("by: human:alice", self.read("pkg/README.md"))
        self.assertEqual(self.read("notes/x.md"), doc())

    def test_exclude_glob(self):
        self.write({"docs/a.md": doc(), "docs/generated/b.md": doc()})
        self.run_action(["docs/a.md", "docs/generated/b.md"],
                        config={"rules": [{"paths": ["docs/**", "!docs/generated/**"], "verify": ["merger"]}]})
        self.assertIn("by: human:alice", self.read("docs/a.md"))
        self.assertIn("status: draft", self.read("docs/generated/b.md"))

    def test_first_matching_rule_wins(self):
        self.write({"specs/README.md": doc()})
        self.run_action(["specs/README.md"], merger="carol", config={"rules": [
            {"paths": ["specs/**"], "verify": ["author"]}, {"paths": ["**/README.md"], "verify": ["merger"]}]})
        text = self.read("specs/README.md")
        self.assertIn("by: human:alice", text)
        self.assertNotIn("carol", text)

    def test_rules_apply_per_path_within_one_pull_request(self):
        self.write({"knowledge/a.md": doc(), "docs/b.md": doc()})
        self.run_action(["knowledge/a.md", "docs/b.md"], reviews=[("bob", "APPROVED", APPROVED_AT)], config={"rules": [
            {"paths": ["knowledge/**"], "verify": ["reviewers"], "reviewers": ["@carol"]},
            {"paths": ["docs/**"], "verify": ["author"]}]})
        self.assertIn("status: draft", self.read("knowledge/a.md"))
        self.assertIn("by: human:alice", self.read("docs/b.md"))

    def test_log_entries_in_nearest_log(self):
        self.write({"specs/log.md": "# Log\n\n## 2026-10-01\n\n**Initialization**: bundle created.\n",
                    "specs/features/x.md": doc(title="Feature X"), "specs/features/y.md": doc(status="stable")})
        self.run_action(["specs/features/x.md", "specs/features/y.md"], reviews=[("bob", "APPROVED", APPROVED_AT)])
        self.assertEqual(self.read("specs/log.md"),
                         "# Log\n\n## 2026-10-30\n\n**Update**: [Feature X](/features/x.md) merged in #7 and marked "
                         "stable; verified by @bob, @alice.\n\n## 2026-10-01\n\n**Initialization**: bundle created.\n")

    def test_preview_writes_nothing(self):
        self.write({"specs/x.md": doc()})
        out = self.run_action(["specs/x.md"], reviews=[("bob", "APPROVED", APPROVED_AT)], merged=False)
        self.assertEqual(self.read("specs/x.md"), doc())
        self.assertIn("| `specs/x.md` | draft → stable | @bob, @whoever merges |", out)

    def test_preview_reports_a_page_that_stays_draft(self):
        self.write({"specs/x.md": doc()})
        out = self.run_action(["specs/x.md"], merged=False,
                              config={"rules": [{"paths": ["specs/**"], "verify": ["approvers"]}]})
        self.assertIn("| `specs/x.md` | draft | nobody |", out)

    def test_preview_warns_about_changes_to_the_rules(self):
        self.write({"specs/x.md": doc(), "CODEOWNERS": "* @carol\n", ".github/okf-approve.yml": "{\"rules\": [{\"paths\": [\"specs/**\"]}]}"})
        out = self.run_action(["specs/x.md", "CODEOWNERS", ".github/okf-approve.yml", ".github/workflows/okf-approve.yml"],
                              merged=False, env={"GITHUB_WORKFLOW_REF": "o/r/.github/workflows/okf-approve.yml@refs/pull/7/merge"})
        self.assertIn("::warning::This pull request changes how its own documents are verified, so review these closely: "
                      ".github/okf-approve.yml, .github/workflows/okf-approve.yml, CODEOWNERS.", out)

    def test_no_warning_without_changes_to_the_rules(self):
        self.write({"specs/x.md": doc()})
        out = self.run_action(["specs/x.md"], merged=False)
        self.assertNotIn("::warning::", out)

    def test_merge_does_not_warn_about_changes_to_the_rules(self):
        self.write({"specs/x.md": doc(), "CODEOWNERS": "* @carol\n"})
        out = self.run_action(["specs/x.md", "CODEOWNERS"])
        self.assertNotIn("how its own documents", out)

    def test_non_okf_markdown_is_skipped(self):
        self.write({"docs/plain.md": "# Plain\n"})
        out = self.run_action(["docs/plain.md"])
        self.assertEqual(self.read("docs/plain.md"), "# Plain\n")
        self.assertIn("Changed: 0 document(s).", out)

    def test_old_and_invalid_config_is_rejected(self):
        for rule, message in (
                ({"verify": ["owners"]}, "`owners` was renamed `reviewers`"),
                ({"owners": ["@carol"], "verify": ["reviewers"]}, "`owners` was renamed `reviewers`"),
                ({"stable": "on-verify"}, "`stable: on-verify` was removed"),
                ({"verify": []}, "`verify` can't be empty"),
                ({"stable": "sometimes"}, "`stable` must be one of"),
                ({"verify": ["nobody"]}, "unknown `verify` value")):
            with self.subTest(rule=rule):
                self.write({"specs/x.md": doc()})
                result = self.run_script(["specs/x.md"], config={"rules": [{"paths": ["specs/**"], **rule}]})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
