# okf-actions/approve

[← okf-actions](../README.md)

A GitHub Action that marks `draft` [OKF](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) documents `stable` when their pull request is merged, and records who is responsible. It works on markdown documents that follow the [OKF specification](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) or the [AI-XF specification](https://github.com/DavidROliverBA/ai-xf-format/blob/main/SPEC.md) such as: specs and test plans, LLM wiki pages, READMEs, general documentation.

## What this action does, and doesn't do

When a pull request is merged, the action looks at each page that pull request changed. It only acts on a page when all of these are true:

- its `status` is `draft` (a page with no `status` counts as `stable`);
- it's a markdown file with frontmatter, other than `index.md` and `log.md`;
- it matches a rule. By default, that means these paths, and no others:
  - `**/README.md`
  - `docs/**`
  - `knowledge/**`
  - `specs/**`

For each such page it sets `status: stable`, records who is responsible in `verified`, adds a line to the nearest `log.md`, and commits to the base branch.

**It leaves every other page alone.** It never changes a `stable` or `deprecated` page, or a page the pull request didn't change. You can change a page's status or `verified` entries at any time, by hand or with the [`status`](../status/README.md) action. Git records who did it and when.

**It never blocks a merge.** It records what happened and enforces nothing, so leave its check out of your required status checks. If a page should not be merged without approval, that's a repository setting: see [Requiring approval](#requiring-approval).

**A page never becomes `stable` without a name against it.** If nobody qualifies under the page's rule, the pull request still merges and the page stays `draft`.

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
      - uses: dzangolab/okf-actions/approve@<commit sha> # v3.0.0
```

Pin the action to a full commit SHA rather than a tag: a tag can be moved, a commit can't. Dependabot or Renovate keep the pin up to date.

That's all a repository needs: without a rules file, the defaults apply, and neither `CODEOWNERS` nor any other setup is required.

While a pull request is open, the action writes nothing. Each run's summary shows what would happen on merge, as of that run. The run also warns if the pull request changes the rules file, `CODEOWNERS` or the workflow, because those decide how its own pages are verified.

## Who verifies a page

`verified` names the people responsible for the page becoming `stable`. Approving or merging makes you responsible, whether or not you read the page.

Each level below is stricter than the one before. The action never prevents a merge at any level.

| Level | Config | Who is recorded | If nobody qualifies |
| --- | --- | --- | --- |
| 1 (default) | `verify: [approvers, merger]` | Everyone who approved, and whoever merged | Only possible if a bot merged with no approvals: the page stays `draft` |
| 2 | `verify: [approvers]` | Everyone who approved, except the author | The page stays `draft` |
| 3 | `verify: [reviewers]` | Approvers who are in the rule's `reviewers`, or in `CODEOWNERS` | The page stays `draft` |

A page can have several people in `verified`, so a reviewer who approves and a colleague who merges are both recorded. Somebody who approves and also merges is recorded once.

### Level 1: anyone who approves or merges

Needs no configuration. It suits a single developer, who can't approve their own pull requests on GitHub: merging is how they verify, and nothing else is needed.

### Level 2: somebody other than the author

```yaml
rules:
  - paths: [knowledge/**, specs/**]
    verify: [approvers]
```

The merger is only recorded if they approved too. To make that approval mandatory, see [Requiring approval](#requiring-approval): without it, a pull request nobody approved still merges, with its pages left `draft`.

### Level 3: only named people

```yaml
rules:
  - paths: [knowledge/**]
    reviewers: ["@dzangolab/seniors", "@carol"]
    verify: [reviewers]
```

An approval from anyone else doesn't count, so approving the code doesn't vouch for the knowledge base unless the approver is one of its reviewers. Without `reviewers` in the rule, `CODEOWNERS` is used (`.github/`, the root or `docs/`). With neither, nobody qualifies and the run warns.

Matching a team needs a token that can read the organization's teams (a fine-grained token or a GitHub App with organization "Members: read"), passed in the `token` input: the default token can't. Without one, team entries are skipped, with a warning. Personal repositories have no teams, so list `@users`.

### Other values

`author` records the pull request's author at merge, for when the author's word is enough, e.g. a CTO writing specs for others to implement. `merger` alone records only whoever merges. Both can be combined with the others. People only: bot accounts are never recorded.

## Rules

Without a rules file, this default applies:

```yaml
rules:
  - paths: ["**/README.md", docs/**, knowledge/**, specs/**]
    stable: on-merge
    verify: [approvers, merger]
```

To change it, add `.github/okf-approve.yml` (or the path given in the `config` input). It replaces the default entirely.

| Key | Values | Meaning |
| --- | --- | --- |
| `paths` | Globs, `**` included | The documents the rule applies to, relative to the repository's root: `knowledge/**`, not `/knowledge/**`. A glob starting with `!` excludes, e.g. `!docs/generated/**`. |
| `reviewers` | `@user` or `@org/team` entries | Who counts for `verify: reviewers`. Without it, `CODEOWNERS` is used. |
| `stable` | `on-merge` (default), `never` | `never` turns the action off for these pages. |
| `verify` | Any of `approvers`, `author`, `merger`, `reviewers`; defaults to `[approvers, merger]` | Who is recorded. It can't be empty. |

Rules apply per path and the first match wins, so one repository can mix levels, and one pull request can touch pages under different rules. Documents no rule matches are left alone.

```yaml
rules:
  - paths: [knowledge/**]
    reviewers: ["@dzangolab/seniors"]
    verify: [reviewers]
  - paths: [docs/**]
    verify: [merger]
  - paths: [specs/**]
    verify: [approvers]
```

## Approving the code but not the pages

A pull request's approval covers all of it: GitHub has no way to approve some pages and not others. To vouch for only some of them, split the pull request.

An approval makes the reviewer responsible for the pages. A reviewer who doesn't want that adds the `okf: keep-status` label (or the label set in the `keep-status-label` input) before the merge, or doesn't approve. Anyone who can label the pull request can add it, and the author can too if they already know the pages aren't ready.

With the label, nothing happens to the pull request's pages: drafts stay `draft`, and nobody is recorded.

## Requiring approval

The action can't require anything, but GitHub can, with a branch ruleset:

- **"Require a pull request before merging", with required approvals:** nothing merges unapproved, and a reviewer's "Request changes" blocks the merge until it's resolved. This locks out a single developer unless they bypass it.
- **"Require conversation resolution before merging":** a reviewer's unresolved review comment blocks the merge. This lets reviewers block when they feel strongly, without anyone having to approve routine pull requests.
- **"Require review from Code Owners":** the same as required approvals, limited to the owners of the changed files. Pair it with level 3.
- **"Dismiss stale pull request approvals when new commits are pushed":** a later commit cancels earlier approvals. Otherwise the action records an approval even if commits followed it. The action ignores dismissed reviews.

Admins bypass these rules by default. Check that your plan offers them for private repositories.

## After the merge

To verify a page later, or to verify a `stable` page, use one of these:

- **The [`status`](../status/README.md) action:** it records whoever runs it, for one page or a whole folder.
- **A pull request that sets the page to `draft`:** at merge it becomes `stable` again, with the people responsible recorded. Doing this for many pages at once verifies a whole knowledge base, with the approvers and merger responsible for all of it.
- **By hand:** add the entry to `verified` yourself, in a commit or a pull request. The action keeps existing entries.

A page left `draft` by a merge becomes `stable` when a later pull request changes it and meets its rule.

## What changes in a document

```yaml
status: stable            # was: draft
verified:
  - at: 2026-11-02T09:00:00Z    # when they approved
    by: human:carol
  - at: 2026-11-02T11:30:00Z    # when they merged
    by: human:dave
```

Existing `verified` entries are kept, and a single inline `verified: { … }` map becomes a list. And in the nearest `log.md`, under today's date:

```markdown
**Update**: [Auth flow](/auth.md) merged in #42 and marked stable; verified by @carol, @dave.
```

## When the commit fails

The action pushes to the base branch after the merge. If the push fails, the pull request is already merged and its pages stay `draft`; use the [`status`](../status/README.md) action, or a follow-up pull request, to finish the job. The push fails when:

- the base branch is protected and `github-actions[bot]` isn't allowed to push to it;
- the pull request came from a fork, whose token is read-only.

## Upgrading from v2

- `owners` is now `reviewers`, as a key and as a `verify` value.
- Only `draft` pages are handled: `stable` pages no longer gain `verified` entries.
- A repository with no rules file, or a rule with no `verify`, now records approvers and the merger. To keep the old behaviour, name it in a rules file: `verify: [reviewers]` for `knowledge/**`, `docs/**` and `**/README.md`, `verify: [approvers]` for `specs/**`.
- Without a qualifying person, a page now stays `draft` instead of becoming `stable`.
- `okf: unverified` and the `unverified-label` input are replaced by `okf: keep-status` and `keep-status-label`, which also keep the status.
- `stable: on-verify` and `verify: []` are errors: the first is now how every rule works, and `stable: never` replaces the second.
