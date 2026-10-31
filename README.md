# okf-actions

Provides GitHub Actions and a [pre-commit](https://pre-commit.com) hook for markdown documents that follow the [OKF specification](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) or the [AI-XF specification](https://github.com/DavidROliverBA/ai-xf-format) such as: specs and test plans, LLM wiki pages, READMEs, general documentation.

## Github Actions

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

The actions are Python scripts, tested end to end. `approve` uses the standard library only; `validate` needs PyYAML. The recipes need [just](https://just.systems).

### Testing

```
just test
```

This creates a virtual environment in `.venv` if there isn't one, installs PyYAML in it, and runs all the tests. The packaging tests download setuptools and PyYAML to install the hook, so they need the network.

### Releasing

```
just release          # prompts "Version [v2.3.0]:"
just release 2.3.0
just release v2.3.0
```

The recipe sets `version` in `pyproject.toml`, commits that to `main`, tags the commit as `vX.Y.Z`, moves `vX` to it, and pushes all of it. The `version`  argument can be either `x.y.z` or `vx.y.z`. Without it, the recipe asks, and pressing Enter accepts the next minor version after the latest release. The tag is always in the form of `vx.y.z`.

If `pyproject.toml` already declares the version, there is no commit, and the tags go on the head of `main`. If anything fails, including the push, the local changes are undone, so the release can be retried. The recipe refuses to release if:

- `main` is not checked out, the working tree is not clean, or `main` differs from `origin/main`.
- The tag already exists.
- The version is older than the latest release of its major version, which would move `vX` backwards. A patch to an older major version is fine, and moves only that major version's tag.

## Just recipes

| Recipe | What it does |
| --- | --- |
| `just` | Lists the recipes. |
| `just release [version]` | Releases a new version: see [Releasing](#releasing). |
| `just test` | Runs all the tests: see [Testing](#testing). |

## License

[MIT](LICENSE). The vendored AI-XF reference validator keeps [its own MIT licence](validate/vendor/ai-xf-0.5/LICENSE).
