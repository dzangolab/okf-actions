# okf-actions

GitHub Actions for [OKF](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) documents, and so for [AI-XF](https://github.com/DavidROliverBA/ai-xf-format) documents too: specs and test plans, an LLM wiki, READMEs.

| Action | What it does |
| --- | --- |
| [`approve`](approve/README.md) | Marks documents approved when their pull request is merged: `draft` becomes `stable`, the people who vouched for them are recorded in `verified`, and an entry is added to the nearest `log.md`. |
| [`validate`](validate/README.md) | Validates documents against the spec and version each rule names: OKF 0.2, or AI-XF 0.5 at a conformance level. |

Each action is a folder, which callers name after the repository:

```yaml
- uses: dzangolab/okf-actions/approve@<commit sha> # v2.0.0
- uses: dzangolab/okf-actions/validate@<commit sha> # v2.0.0
```

Pin the actions to a full commit SHA rather than a tag: a tag can be moved, a commit can't. Dependabot or Renovate keep the pin up to date. Both actions share the repository's tags, so a release of one is a release of both.

The repository was `dzangolab/okf-approve` until v2.0.0, where the approve action moved from the root to `approve/`.

## Development

The actions are Python scripts, tested end to end. `approve` uses the standard library only; `validate` needs PyYAML:

```
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r validate/requirements.txt
.venv/bin/python -m unittest discover -s tests
```

## License

[MIT](LICENSE). The vendored AI-XF reference validator keeps [its own MIT licence](validate/vendor/ai-xf-0.5/LICENSE).
