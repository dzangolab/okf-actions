"""End-to-end test of `just release`: runs the recipe in a clone of a bare origin, and
checks the tags that reach the origin. Skipped where just isn't installed."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@example.com", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}


@unittest.skipUnless(shutil.which("just"), "just is not installed")
class ReleaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.origin = Path(self.tmp.name) / "origin.git"
        self.repo = Path(self.tmp.name) / "repo"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", self.origin], check=True, env=ENV)
        subprocess.run(["git", "clone", "-q", self.origin, self.repo], check=True, env=ENV, capture_output=True)
        self.git("checkout", "-q", "-b", "main")
        shutil.copy(ROOT / "justfile", self.repo / "justfile")
        self.commit_version("2.2.0")
        for tag in ("v2.2.0", "v2"):
            self.git("tag", "-a", "-m", tag, tag)
        self.git("push", "-q", "origin", "main", "--tags")
        self.old_head = self.git("rev-parse", "HEAD")

    def git(self, *args, cwd=None):
        result = subprocess.run(["git", *args], cwd=cwd or self.repo, check=True, env=ENV, capture_output=True, text=True)
        return result.stdout.strip()

    def commit_version(self, version):
        (self.repo / "pyproject.toml").write_text(f'[project]\nname = "x"\nversion = "{version}"\n')
        self.git("add", ".")
        self.git("commit", "-q", "-m", f"chore: version {version}")

    def bump(self, version):
        """Commits the version and pushes it, as merging the bump to main would."""
        self.commit_version(version)
        self.git("push", "-q", "origin", "main")
        return self.git("rev-parse", "HEAD")

    def release(self, *args, stdin="", expect=0):
        result = subprocess.run(["just", "release", *args], cwd=self.repo, input=stdin, env=ENV, capture_output=True, text=True)
        self.assertEqual(result.returncode, expect, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def origin_commit(self, tag):
        """The commit a tag on the origin points to, None if it isn't there."""
        result = subprocess.run(["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}^{{commit}}"],
                                cwd=self.origin, env=ENV, capture_output=True, text=True)
        return result.stdout.strip() or None

    def assert_refused(self, message, *args, tags=("v2.3.0",)):
        self.assertIn(message, self.release(*args, expect=1))
        self.assertEqual(self.origin_commit("v2"), self.old_head)
        for tag in tags:
            self.assertIsNone(self.origin_commit(tag))

    def test_pushes_full_and_major_tag_from_a_bare_version(self):
        head = self.bump("2.3.0")
        self.release("2.3.0")
        self.assertEqual(self.origin_commit("v2.3.0"), head)
        self.assertEqual(self.origin_commit("v2"), head)
        self.assertEqual(self.origin_commit("v2.2.0"), self.old_head)

    def test_accepts_a_v_prefix(self):
        head = self.bump("2.3.0")
        self.release("v2.3.0")
        self.assertEqual(self.origin_commit("v2.3.0"), head)
        self.assertEqual(self.origin_commit("v2"), head)
        self.assertIsNone(self.origin_commit("vv2.3.0"))

    def test_tags_are_annotated(self):
        self.bump("2.3.0")
        self.release("2.3.0")
        for tag in ("v2.3.0", "v2"):
            self.assertEqual(self.git("cat-file", "-t", f"refs/tags/{tag}", cwd=self.origin), "tag")

    def test_default_increments_the_minor_of_the_latest_release(self):
        self.git("tag", "-a", "-m", "v2.10.4", "v2.10.4")
        self.git("push", "-q", "origin", "v2.10.4")
        head = self.bump("2.11.0")
        self.release(stdin="\n")
        self.assertEqual(self.origin_commit("v2.11.0"), head)
        self.assertEqual(self.origin_commit("v2"), head)

    def test_prompt_accepts_another_version(self):
        head = self.bump("3.0.0")
        self.release(stdin="3.0.0\n")
        self.assertEqual(self.origin_commit("v3.0.0"), head)
        self.assertEqual(self.origin_commit("v3"), head)
        self.assertEqual(self.origin_commit("v2"), self.old_head)

    def test_patch_of_an_older_major_moves_only_that_major(self):
        self.git("tag", "-a", "-m", "v1.0.0", "v1.0.0", "HEAD")
        self.git("tag", "-a", "-m", "v1", "v1", "HEAD")
        self.git("push", "-q", "origin", "v1.0.0", "v1")
        head = self.bump("1.0.1")
        self.release("1.0.1")
        self.assertEqual(self.origin_commit("v1"), head)
        self.assertEqual(self.origin_commit("v2"), self.old_head)

    def test_refuses_a_malformed_version(self):
        for version in ("2.3", "2.3.0.1", "2.3.x", "vv2.3.0", "02.3.0", "2.3.0-rc1"):
            with self.subTest(version):
                self.assert_refused("is not x.y.z or vx.y.z", version, tags=())

    def test_refuses_an_existing_tag(self):
        self.assert_refused("v2.2.0 already exists", "2.2.0", tags=())

    def test_refuses_a_version_older_than_the_latest_of_its_major(self):
        self.commit_version("2.1.0")
        self.git("push", "-q", "origin", "main")
        self.assert_refused("v2.1.0 is older than v2.2.0", "2.1.0", tags=("v2.1.0",))

    def test_refuses_a_version_pyproject_does_not_declare(self):
        self.assert_refused("set it to 2.3.0", "2.3.0")

    def test_refuses_a_dirty_working_tree(self):
        self.bump("2.3.0")
        (self.repo / "untracked").write_text("")
        self.assertIn("not clean", self.release("2.3.0", expect=1))
        self.assertIsNone(self.origin_commit("v2.3.0"))

    def test_refuses_another_branch(self):
        self.bump("2.3.0")
        self.git("checkout", "-q", "-b", "feat/x")
        self.assertIn("not on main", self.release("2.3.0", expect=1))
        self.assertIsNone(self.origin_commit("v2.3.0"))

    def test_refuses_a_main_that_is_not_pushed(self):
        self.commit_version("2.3.0")
        self.assertIn("not at origin/main", self.release("2.3.0", expect=1))
        self.assertIsNone(self.origin_commit("v2.3.0"))

    def test_a_failed_push_leaves_it_possible_to_retry(self):
        head = self.bump("2.3.0")
        hook = self.origin / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        self.assertIn("push failed", self.release("2.3.0", expect=1))
        self.assertIsNone(self.origin_commit("v2.3.0"))
        self.assertEqual(self.origin_commit("v2"), self.old_head)
        hook.unlink()
        self.release("2.3.0")
        self.assertEqual(self.origin_commit("v2.3.0"), head)
        self.assertEqual(self.origin_commit("v2"), head)


if __name__ == "__main__":
    unittest.main()
