# okf-actions/status

[← okf-actions](../README.md)

A GitHub Action, run by hand, that changes the status of [OKF](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) documents or records that you verified them. It needs nothing installed: run it from the Actions tab in a browser, or with `gh`.

Use it to:

- **Verify a page after its pull request was merged**, or a whole folder of pages.
- **Set a page back to `draft`** on a pull request's branch, so that [`approve`](../approve/README.md) handles it again at merge.
- **Deprecate a page.**

## Usage

Add `.github/workflows/okf-status.yml`. GitHub needs a workflow's inputs declared in the workflow itself, so all of this goes in your repository, and it must be on the default branch before the "Run workflow" button appears:

```yaml
name: OKF status

on:
  workflow_dispatch:
    inputs:
      paths:
        description: Files or globs, separated by spaces or commas
        required: true
        type: string
      status:
        default: unchanged
        options: [unchanged, deprecated, draft, stable]
        type: choice
      verify:
        default: false
        description: Record me as having verified these pages
        type: boolean

jobs:
  okf-status:
    permissions:
      contents: write
    runs-on: ubuntu-latest
    steps:
      - uses: dzangolab/okf-actions/status@<commit sha> # v3.0.0
        with:
          paths: ${{ inputs.paths }}
          status: ${{ inputs.status }}
          verify: ${{ inputs.verify }}
```

Then, from the Actions tab, choose **OKF status** and **Run workflow**, or from a terminal:

```
gh workflow run okf-status.yml -f paths="knowledge/**" -f verify=true
gh workflow run okf-status.yml --ref my-branch -f paths=knowledge/auth.md -f status=draft
```

The action commits to the branch it was run on, so pull afterwards if you're working on that branch. Committing to a protected branch needs the same permission as [`approve`](../approve/README.md#when-the-commit-fails).

## What it does

For each matching markdown file with frontmatter, other than `index.md` and `log.md`, it sets the status, records a verification when asked to, and adds a line to the nearest `log.md`.

| Input | Values | Meaning |
| --- | --- | --- |
| `paths` | Files or globs, `**` included | The documents to change. A glob starting with `!` excludes. |
| `status` | `unchanged` (default), `deprecated`, `draft`, `stable` | The new status. |
| `verify` | `true`, `false` (default) | Record the person running the workflow in `verified`. |

Only the person running the workflow is ever recorded: no input takes a name. Setting a page `stable` always records them, even without `verify`, so that no page becomes `stable` without a name against it. Setting `draft` or `deprecated` records nobody, unless `verify` is on.

The rules in `.github/okf-approve.yml` don't apply here: they decide what happens at merge. Running the workflow takes write access to the repository, so contributors working from a fork edit the page by hand in their pull request instead.
