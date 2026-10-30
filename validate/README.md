# okf-actions/validate

[← okf-actions](../README.md)

A GitHub Action that validates [OKF](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) documents against the spec and version you name: OKF itself, or [AI-XF](https://github.com/DavidROliverBA/ai-xf-format), its superset. Errors fail the run and are annotated on the files; warnings are only reported.

## Usage

Add `.github/workflows/okf-validate.yml`:

```yaml
name: OKF validate

on:
  pull_request:
  push:
    branches:
      - main

permissions:
  contents: read

jobs:
  okf-validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<commit sha> # v7.0.1
      - uses: dzangolab/okf-actions/validate@<commit sha> # v2.0.0
```

It validates the working tree, so check out the repository first. It installs [PyYAML](https://pypi.org/project/PyYAML/), pinned by hash, in a virtual environment of its own.

## Rules

The rules file, `.github/okf-validate.yml` (or the path given in the `config` input), is required: what a repository's documents follow is its own decision, so there are no defaults.

```yaml
rules:
  - paths: [specs/**]
    spec: ai-xf
    version: "0.5"
  - paths: [knowledge/**, "**/README.md"]
    spec: okf
    version: "0.2"
```

The first rule whose `paths` match a markdown file applies; files no rule matches aren't validated.

| Key | Values | Meaning |
| --- | --- | --- |
| `level` | `0` to `3` | `ai-xf` only: the [conformance level](https://github.com/DavidROliverBA/ai-xf-format/blob/main/SPEC.md#11-conformance-levels) to check. Defaults to the bundle manifest's `conformance`, else `1`. |
| `paths` | Globs, `**` included | The documents the rule applies to. A glob starting with `!` excludes, e.g. `!docs/generated/**`. |
| `spec` | `okf`, `ai-xf` | The spec to validate against. |
| `version` | `okf`: `"0.2"`; `ai-xf`: `"0.5"` | The spec's version. Quote it, or YAML reads `0.10` as the number `0.1`. |

### `spec: okf`

Each file is checked on its own, against OKF 0.2:

- **Errors**, what [§11](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md#11-conformance) makes conformance:
  - a concept document without parseable YAML frontmatter, or without a non-empty `type`;
  - an `index.md` with frontmatter other than `okf_version`;
  - a `log.md` date heading that isn't `## YYYY-MM-DD`.
- **Warnings**, the recommendations of §5 to §9:
  - `status` other than `draft`, `stable` or `deprecated`;
  - `generated` without `by`, `verified` entries without `by` and `at`;
  - actors that aren't `human:<id>`, `process:<id>` or `<producer>/<version>`;
  - timestamps that aren't ISO 8601;
  - `tags` that isn't a list;
  - `log.md` dates that aren't newest first.

### `spec: ai-xf`

AI-XF validates bundles, not single files: links must resolve and `id`s be unique across a bundle. A file's bundle is the nearest folder at or above it with a `manifest.ai-xf.yaml`, and a matched file with none is an error. Each bundle is validated by the [AI-XF reference validator](vendor/ai-xf-0.5/README.md) of the rule's version, with the markdown files in it that the rule selects: exclude what isn't a concept, such as ingested originals, with a `!` glob. The run warns when the manifest's `ai-xf` declares another version than the rule's.

## Adding a spec version

- **OKF:** add an `okf_<major>_<minor>.py` checker with the same `check(path)` function, and register it in `SPECS` in `okf_validate.py`.
- **AI-XF:** copy that version's reference validator, unchanged, into `vendor/ai-xf-<version>/` with its licence; the version is supported from then on.
