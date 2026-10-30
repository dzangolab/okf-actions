# okf-actions

GitHub Actions for OKF documents, one composite action per folder: `approve/` marks documents approved when their pull request is merged, `validate/` validates them against OKF or AI-XF. Each folder's `README.md` says what its action does and how it's configured.

## Conventions

- `approve/okf_approve.py` uses the Python standard library only: no dependencies to install on the runner.
- `validate/okf_validate.py` needs PyYAML, pinned by hash in `validate/requirements.txt`, which the action installs in a virtual environment.
- `validate/vendor/` holds the AI-XF reference validators, copied unchanged with their licence, one folder per version. Never edit them.
- Every behaviour is covered by an end-to-end test in `tests/`, which builds a git repository, runs the script, and checks the result. `test_approve.py` also builds a pull_request event and API fixtures (`OKF_APPROVE_FIXTURES`).
- Pin actions to full commit SHAs, with the version in a comment.
- Releases are tagged `vX.Y.Z`, with a moving `vX` tag, and cover both actions; callers are told to pin the commit SHA.

## Checks

```
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r validate/requirements.txt
.venv/bin/python -m unittest discover -s tests
```
