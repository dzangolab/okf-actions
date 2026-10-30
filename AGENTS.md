# okf-approve

A GitHub Action (composite, `action.yml`) that runs `okf_approve.py` on pull request events to mark OKF documents approved on merge. See `README.md` for what it does and how it's configured.

## Conventions

- `okf_approve.py` uses the Python standard library only: no dependencies to install on the runner.
- Every behaviour is covered by an end-to-end test in `tests/test_okf_approve.py`, which builds a git repository, a pull_request event and API fixtures (`OKF_APPROVE_FIXTURES`), then runs the script.
- Pin actions to full commit SHAs, with the version in a comment.
- Releases are tagged `vX.Y.Z`, with a moving `vX` tag; callers are told to pin the commit SHA.

## Checks

```
python3 -m unittest discover -s tests
```
