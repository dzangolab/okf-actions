# okf-actions

GitHub Actions for OKF documents, one composite action per folder: `approve/` marks documents approved when their pull request is merged, `validate/` validates them against OKF or AI-XF. Each folder's `README.md` says what its action does and how it's configured. `validate/` also runs as a pre-commit hook, `okf-validate`, declared in `.pre-commit-hooks.yaml`.

## Conventions

- `approve/okf_approve.py` uses the Python standard library only: no dependencies to install on the runner.
- `validate/okf_validate.py` needs PyYAML, pinned by hash in `validate/requirements.txt`, which the action installs in a virtual environment.
- `pyproject.toml` exists for the hook, because pre-commit runs `pip install .`. It installs `validate/` as the package `okf_actions_validate`, with `vendor/`, and nothing else: anything else the validator reads at run time must be added to its package data. PyYAML is pinned there too, to the same exact version: when `validate/requirements.txt` changes, change it there as well (`tests/test_package.py` fails otherwise). Dependabot only watches `validate/`.
- `okf_validate.py` must keep working both ways: as the action runs it, `python -I` with no arguments and `CONFIG`, and as the hook runs it, with `--config` and file arguments. With no file arguments it validates the whole working tree, and output inside GitHub Actions (`GITHUB_ACTIONS=true`) stays workflow commands.
- `validate/vendor/` holds the AI-XF reference validators, copied unchanged with their licence, one folder per version. Never edit them.
- Every behaviour is covered by an end-to-end test in `tests/`, which builds a git repository, runs the script, and checks the result. `test_approve.py` also builds a pull_request event and API fixtures (`OKF_APPROVE_FIXTURES`). `test_package.py` installs the repository with `pip install .`, as pre-commit does, and needs the network.
- Pin actions, and the hook's `rev`, to full commit SHAs, with the version in a comment.
- Releases are tagged `vX.Y.Z`, with a moving `vX` tag, and cover both actions and the hook; callers are told to pin the commit SHA. Set `version` in `pyproject.toml` to the release's version before tagging.

## Checks

```
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r validate/requirements.txt
.venv/bin/python -m unittest discover -s tests
```
