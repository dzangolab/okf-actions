"""End-to-end test of what the pre-commit hook runs: installs the repository with
`pip install .`, as pre-commit does, in a virtual environment, and runs the console
script on a git repository. Needs the network, for setuptools and PyYAML."""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DOCUMENT = "---\nid: a\ntitle: Doc\ntype: Concept\n---\n\n# Doc\n"


class PackageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls.tmp.name)
        source = tmp / "source"
        # A copy, as `pip install .` writes build/ and *.egg-info/ next to pyproject.toml.
        shutil.copytree(ROOT, source, ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", "build", "*.egg-info"))
        subprocess.run([sys.executable, "-m", "venv", tmp / "venv"], check=True)
        cls.bin = tmp / "venv" / "bin"
        subprocess.run([cls.bin / "pip", "install", "--quiet", "."], cwd=source, check=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.repo_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.repo_dir.name)
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)

    def tearDown(self):
        self.repo_dir.cleanup()

    def write(self, files):
        for name, content in files.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)

    def run_hook(self, *args, expect=0):
        result = subprocess.run([self.bin / "okf-validate", *args], cwd=self.repo, capture_output=True, text=True,
                                env={k: v for k, v in os.environ.items() if k not in ("CONFIG", "GITHUB_ACTIONS")})
        self.assertEqual(result.returncode, expect, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def test_installed_script_validates_okf(self):
        self.write({"docs/a.md": DOCUMENT, "docs/b.md": "# B\n",
                    "rules.yml": json.dumps({"rules": [{"paths": ["docs/**"], "spec": "okf", "version": "0.2"}]})})
        self.assertIn("1 document(s) checked: 0 error(s)", self.run_hook("--config", "rules.yml", "docs/a.md"))
        self.assertIn("docs/b.md: error:", self.run_hook("--config", "rules.yml", "docs/b.md", expect=1))

    def test_installed_script_runs_the_vendored_ai_xf_validator(self):
        self.write({"specs/manifest.ai-xf.yaml": "ai-xf: \"0.5\"\nname: specs\n", "specs/a.md": DOCUMENT, "specs/b.md": DOCUMENT,
                    "rules.yml": json.dumps({"rules": [{"paths": ["specs/**"], "spec": "ai-xf", "version": "0.5"}]})})
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True)
        self.assertIn("duplicate id `a`", self.run_hook("--config", "rules.yml", "specs/a.md", expect=1))
        subprocess.run(["git", "rm", "-qf", "specs/b.md"], cwd=self.repo, check=True)
        self.assertIn("specs: AI-XF 0.5 level 1 achieved", self.run_hook("--config", "rules.yml", "specs/a.md"))

    def test_only_the_validator_is_installed(self):
        shown = subprocess.run([self.bin / "pip", "show", "--files", "okf-actions"], capture_output=True, text=True, check=True).stdout
        installed = {line.strip() for line in shown.split("Files:")[1].splitlines()}
        self.assertLessEqual({"okf_actions_validate/okf_0_2.py", "okf_actions_validate/okf_validate.py",
                              "okf_actions_validate/vendor/ai-xf-0.5/LICENSE",
                              "okf_actions_validate/vendor/ai-xf-0.5/ai-xf-validate.py"}, installed)
        for path in installed:
            self.assertNotRegex(path, r"^(approve|tests|validate)/")
            self.assertNotIn("okf_approve", path)
            self.assertNotIn("test_", path)

    def test_hook_runs_the_console_script(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
        hook, = yaml.safe_load((ROOT / ".pre-commit-hooks.yaml").read_text())
        self.assertEqual(hook["id"], "okf-validate")
        self.assertEqual(hook["language"], "python")
        self.assertIn(hook["entry"], project["scripts"])

    def test_pyyaml_pin_matches_the_action(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
        action = re.match(r"\S+", (ROOT / "validate" / "requirements.txt").read_text()).group()
        self.assertEqual(project["dependencies"], [action])


if __name__ == "__main__":
    unittest.main()
