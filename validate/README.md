# okf-actions/validate

[← okf-actions](../README.md)

A GitHub Action that validates [OKF](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) documents against the spec and version you name: OKF itself, or [AI-XF](https://github.com/DavidROliverBA/ai-xf-format), its superset. Errors fail the run and are annotated on the files; warnings are only reported. It also runs as a [pre-commit hook](#pre-commit-hook).

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

The rules file, `.github/okf-validate.yml` (or the path given in the action's `config` input, or the hook's `--config` option), is required: what a repository's documents follow is its own decision, so there are no default rules.

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
| `version` | `okf`: `"0.2"`; `ai-xf`: `"0.5"` | The spec's version. Defaults to `"0.2"` for `okf` and `"0.5"` for `ai-xf`. Quote it, or YAML reads `0.10` as the number `0.1`. |

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

## Pre-commit hook

The `okf-validate` hook validates the markdown files in a commit against the [rules](#rules), so problems show up before the pull request does. Add it to `.pre-commit-config.yaml`:

```yaml
repos:
  - hooks:
      - id: okf-validate
    repo: https://github.com/dzangolab/okf-actions
    rev: <commit sha> # v2.2.0
```

Pin `rev` to a full commit SHA, as for the action, with the version in a comment. The hook is available from v2.2.0. `pre-commit autoupdate --freeze` moves the pin to the latest release. pre-commit installs the hook and [PyYAML](https://pypi.org/project/PyYAML/), at an exact version but not by hash, in an environment of its own, from `pyproject.toml`.

To keep the rules somewhere other than `.github/okf-validate.yml`, pass their path:

```yaml
      - args: [--config, okf-rules.yml]
        id: okf-validate
```

The hook is the same script as the action, with these differences:

- **Files:** it validates only the files pre-commit passes it, not the whole working tree, and ignores untracked files it wasn't passed, so a half-written file doesn't block an unrelated commit. A file no rule matches is reported as skipped. The rules still decide what's validated, and the first rule whose `paths` match a file applies.
- **Output:** outside GitHub Actions (`GITHUB_ACTIONS` isn't `true`), findings are plain `file: severity: message` lines and a count, rather than workflow commands and a summary table. Errors exit 1; warnings exit 0.

With an `ai-xf` rule, a file in the commit causes its whole bundle to be validated, with the markdown files the rule selects, because a change to one document can break another: a duplicate `id` can be reported on a document that isn't in the commit. Such a finding fails the commit, as it would fail the action. Other bundles aren't validated. The bundle is seen as the commit will have it, from its tracked and staged files plus the files passed, so a manifest or linked document that hasn't been added counts as missing.

The hook runs only when a markdown file is in the commit: a commit that only changes a `manifest.ai-xf.yaml`, or only deletes documents, isn't checked. The action still validates everything, so keep it in CI.

### With husky

`pre-commit install` doesn't work alongside [husky](https://typicode.github.io/husky/): husky sets `core.hooksPath`, and pre-commit refuses to install while that's set. Keep the `.pre-commit-config.yaml` entry above, install the `pre-commit` CLI, and call it from `.husky/pre-commit`, with the `PATH` line [Git GUIs](#from-git-guis-such-as-fork) need:

```sh
# Git GUIs such as Fork run hooks without your shell's PATH: add where pre-commit is usually installed
export PATH="$PATH:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$HOME/.nix-profile/bin:/etc/profiles/per-user/$USER/bin"

pre-commit run
```

`pre-commit run` checks the staged files, with unstaged changes set aside, so it behaves as the installed hook does. Every developer needs the `pre-commit` CLI, but not Node at commit time, since husky's hook runner is a shell script.

To avoid the `pre-commit` CLI, install the script itself, for example in a virtual environment with `pip install "git+https://github.com/dzangolab/okf-actions@<commit sha>" # v2.2.0`, put that environment's `bin` on `PATH`, and call it from the hook:

```sh
files=$(git -c core.quotePath=false diff --cached --name-only --diff-filter=ACMR -- '*.md')
[ -z "$files" ] || echo "$files" | tr '\n' '\0' | xargs -0 okf-validate
```

- Keep the empty check: with no file arguments, `okf-validate` validates the whole working tree, untracked files included.
- This reads files from the working tree, not the staged content, so a file with unstaged changes is validated as it is on disk, and a broken unstaged edit blocks the commit.

[lint-staged](https://github.com/lint-staged/lint-staged) works too, with `{"*.md": "okf-validate"}`, but it runs on Node, so both Node and `okf-validate` have to be on the hook's `PATH`.

### From Git GUIs such as Fork

An app opened from the Dock or Finder doesn't read your shell profile. On macOS, [Fork](https://git-fork.com) runs with `PATH=/usr/bin:/bin:/usr/sbin:/sbin`, so a hook can't find anything installed with Homebrew, pipx, uv, mise or Nix, even though the same commit works in a terminal. With husky, it looks like this:

```
.husky/pre-commit: line 1: pre-commit: command not found
husky - pre-commit script failed (code 127)
husky - command not found in PATH=node_modules/.bin:...:/usr/bin:/bin:/usr/sbin:/sbin
```

- **With `pre-commit install`:** no change is needed. The generated hook records absolute paths to the Python or pre-commit it was installed with, and the `okf-validate` hook runs from its own environment. If those paths go away, for example after upgrading Python or a Nix garbage collection, run `pre-commit install` again.
- **With husky:** start `.husky/pre-commit` with the `PATH` line above. Committing it means nobody has to configure their machine. Add any other location your team installs to, such as `$HOME/.local/share/mise/shims`. Appending keeps anything already on `PATH` first.
- **On the first commit:** pre-commit builds the hook's environment, which needs the network and takes longer. To do it from a terminal first, run `pre-commit install-hooks`.

To reproduce what a GUI sees without opening one, commit from a terminal with its `PATH`:

```sh
env -i HOME="$HOME" USER="$USER" PATH=/usr/bin:/bin:/usr/sbin:/sbin git commit -m "test"
```

## Adding a spec version

The default a rule gets without a `version` doesn't follow: to change it, change `DEFAULT_VERSIONS` in `okf_validate.py`.

- **OKF:** add an `okf_<major>_<minor>.py` checker with the same `check(path)` function, and register it in `SPECS` in `okf_validate.py`.
- **AI-XF:** copy that version's reference validator, unchanged, into `vendor/ai-xf-<version>/` with its licence; the version is supported from then on.
