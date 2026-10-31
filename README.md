# okf-actions

GitHub Actions, and a [pre-commit](https://pre-commit.com) hook, for [OKF](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) documents, and so for [AI-XF](https://github.com/DavidROliverBA/ai-xf-format) documents too: specs and test plans, an LLM wiki, READMEs.

| Action | What it does |
| --- | --- |
| [`approve`](approve/README.md) | Marks documents approved when their pull request is merged: `draft` becomes `stable`, the people who vouched for them are recorded in `verified`, and an entry is added to the nearest `log.md`. |
| [`validate`](validate/README.md) | Validates documents against the spec and version each rule names: OKF 0.2, or AI-XF 0.5 at a conformance level. |

Each action is a folder, which callers name after the repository:

```yaml
- uses: dzangolab/okf-actions/approve@<commit sha> # v2.0.0
- uses: dzangolab/okf-actions/validate@<commit sha> # v2.0.0
```

Pin the actions to a full commit SHA rather than a tag: a tag can be moved, a commit can't. Dependabot or Renovate keep the pin up to date. Both actions, and the hook below, share the repository's tags, so a release of one is a release of all.

The repository was `dzangolab/okf-approve` until v2.0.0, where the approve action moved from the root to `approve/`.

## Pre-commit hook

The `okf-validate` hook runs the [`validate`](validate/README.md#pre-commit-hook) checks on the markdown files in a commit, from the same rules file. Add it to `.pre-commit-config.yaml`, pinned the same way, to a commit SHA with the version in a comment (the hook is available from v2.2.0):

```yaml
repos:
  - hooks:
      - id: okf-validate
    repo: https://github.com/dzangolab/okf-actions
    rev: <commit sha> # v2.2.0
```

Using husky, or committing from a Git GUI such as Fork? See [With husky](validate/README.md#with-husky) and [From Git GUIs such as Fork](validate/README.md#from-git-guis-such-as-fork).

## Development

The actions are Python scripts, tested end to end. `approve` uses the standard library only; `validate` needs PyYAML, and the packaging tests download setuptools and PyYAML to install the hook:

```
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r validate/requirements.txt
.venv/bin/python -m unittest discover -s tests
```

## License

[MIT](LICENSE). The vendored AI-XF reference validator keeps [its own MIT licence](validate/vendor/ai-xf-0.5/LICENSE).
