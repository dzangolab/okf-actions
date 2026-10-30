# okf-approve

A GitHub Action that marks [OKF](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) documents approved when their pull request is merged: `draft` becomes `stable`, the people who vouched for them are recorded in `verified`, and an entry is added to the nearest `log.md`.

It works on any OKF document, and so on any [AI-XF](https://github.com/DavidROliverBA/ai-xf-format) document too: specs and test plans, an LLM wiki, READMEs.

## How it works

On every pull request, for each changed markdown file that has OKF frontmatter, the first rule whose `paths` match the file decides:

- **`verify`:** who is recorded in `verified`, as `human:<GitHub login>`;
- **`stable`:** whether a `draft` document becomes `stable`.

On a **merged** pull request, the action updates the documents and the nearest `log.md` above each of them, then commits to the base branch as `github-actions[bot]`. On an **open** pull request, it writes nothing: the run's summary shows what will happen on merge, so reviewers can act before it does.

Two OKF fields, two decisions: `status` says whether the content is current, `verified` says whether a person vouched for it. A merged knowledge-base page can be `stable` and still unverified, which OKF treats as a valid trust tier.

## Usage

Add `.github/workflows/okf-approve.yml`:

```yaml
name: OKF approve

on:
  pull_request:
    types: [opened, synchronize, reopened, closed]

jobs:
  okf-approve:
    if: github.event.action != 'closed' || github.event.pull_request.merged
    permissions:
      contents: write
      pull-requests: read
    runs-on: ubuntu-latest
    steps:
      - uses: dzangolab/okf-approve@<commit sha> # v1.0.0
```

Pin the action to a full commit SHA rather than a tag: a tag can be moved, a commit can't. Dependabot or Renovate keep the pin up to date.

The action pushes to the base branch. If it is protected, let `github-actions[bot]` push to it, or the commit fails after the merge.

## Rules

Without a rules file, these defaults apply:

```yaml
rules:
  - paths: [knowledge/**, docs/**, "**/README.md"]
    verify: [owners]
    stable: on-merge
  - paths: [specs/**]
    verify: [approvers]
    stable: on-merge
```

To change them, add `.github/okf-approve.yml` (or the path given in the `config` input). The first rule whose `paths` match a document applies; documents no rule matches are left alone.

| Key | Values | Meaning |
| --- | --- | --- |
| `paths` | Globs, `**` included | The documents the rule applies to. A glob starting with `!` excludes, e.g. `!docs/generated/**`. |
| `verify` | Any of `approvers`, `author`, `merger`, `owners` | Who is recorded in `verified`. `[]` records nobody. |
| `owners` | `@user` or `@org/team` entries | Who counts for `verify: owners`. Without it, `CODEOWNERS` is used. |
| `stable` | `on-merge` (default), `on-verify`, `never` | When a `draft` becomes `stable`: always on merge, only when someone is recorded, or never. |

What each `verify` value records:

- **`approvers`:** every reviewer whose latest review approves, except the pull request's author (GitHub never lets authors approve their own pull requests). Use it when someone else approves the documents.
- **`author`:** the pull request's author, at merge. Use it when the author's word is the verification, e.g. a CTO writing specs for others to implement.
- **`merger`:** whoever merged, at merge. Use it for a repository with a single maintainer.
- **`owners`:** the approvers who own the document. Use it when documents change in pull requests that are mainly about code, such as an LLM wiki: an approval of the code doesn't vouch for the knowledge base unless it comes from one of its owners. Owners come from the rule's `owners`, else from `CODEOWNERS` (`.github/`, the root or `docs/`). With neither, nobody qualifies: the documents stay unverified and the run warns.

Matching a team needs a token that can read the organization's teams (a fine-grained token or a GitHub App with organization "Members: read"), passed in the `token` input. Without one, team entries are skipped, with a warning.

### Examples

A repository of specs, where the author's merge is enough:

```yaml
rules:
  - paths: [specs/**]
    verify: [author, approvers]
```

A monorepo with specs that someone else must approve, and a wiki maintained alongside the code:

```yaml
rules:
  - paths: [specs/**]
    verify: [approvers]
    stable: on-verify
  - paths: [knowledge/**, "**/README.md"]
    verify: [owners]
    owners: ["@dzangolab/architects"]
```

## Opting out

A reviewer who approves a pull request for its code, without vouching for its documents, adds the `okf: unverified` label (or the label set in the `unverified-label` input) before the merge. Nobody is then recorded for that pull request.

## What changes in a document

```yaml
status: stable            # was: draft
verified:
  - at: 2026-10-30T09:00:00Z
    by: human:carol
```

A document that is already `stable` gains a `verified` entry when a qualifying person approves a pull request that changes it. Existing `verified` entries are kept, and a single inline `verified: { … }` map becomes a list. And in the nearest `log.md`, under today's date:

```markdown
**Update**: [Auth flow](/auth.md) merged in #42 and marked stable; verified by @carol.
```

## Development

The action is one Python script with no dependencies. Run the tests with:

```
python3 -m unittest discover -s tests
```

## License

[MIT](LICENSE).
