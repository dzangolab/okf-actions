default:
    @just --list

# Set the version in pyproject.toml, commit it to main, tag that as vX.Y.Z, move vX to it, and push all of it. VERSION is x.y.z or vx.y.z; asked for if omitted, defaulting to the next minor.
release $version="":
    #!/usr/bin/env bash
    set -euo pipefail

    fail() { echo "error: $*" >&2; exit 1; }
    # The vX.Y.Z tags, oldest first, optionally only those with a prefix such as "v2.".
    release_tags() { git tag --list "${1:-v}*" | { grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' || true; } | sort -V; }

    # Moving tags are rejected by a plain fetch, hence --force.
    git fetch --quiet --force --tags origin main

    if [[ -z "$version" ]]; then
        latest=$(release_tags | tail -n 1)
        if [[ -n "$latest" ]]; then
            IFS=. read -r major minor _ <<< "${latest#v}"
            suggested="v$major.$((minor + 1)).0"
        else
            suggested=v0.1.0
        fi
        read -r -p "Version [$suggested]: " version
        version=${version:-$suggested}
    fi

    number='(0|[1-9][0-9]*)'
    [[ "$version" =~ ^v?$number\.$number\.$number$ ]] || fail "'$version' is not x.y.z or vx.y.z"
    tag="v${version#v}"
    major="${tag%%.*}"

    [[ "$(git branch --show-current)" == main ]] || fail "not on main"
    [[ -z "$(git status --porcelain)" ]] || fail "the working tree is not clean"
    [[ "$(git rev-parse HEAD)" == "$(git rev-parse origin/main)" ]] || fail "main is not at origin/main"
    ! git rev-parse --quiet --verify "refs/tags/$tag" > /dev/null || fail "$tag already exists"

    # Moving vX back to an older release would downgrade everyone following it.
    newest=$( { release_tags "$major."; echo "$tag"; } | sort -V | tail -n 1)
    [[ "$newest" == "$tag" ]] || fail "$tag is older than $newest"

    # From here on, a failure undoes the local changes, so the release can be retried.
    # The working tree is known to be clean. The next run's fetch restores vX.
    start=$(git rev-parse HEAD)
    undo() {
        git reset --quiet --hard "$start"
        git tag --delete "$tag" > /dev/null 2>&1 || true
    }
    trap undo EXIT

    sed -i.bak -E "s/^version = \".*\"$/version = \"${tag#v}\"/" pyproject.toml
    rm pyproject.toml.bak
    # Already declared, for instance by a merged pull request: there's nothing to commit.
    git diff --quiet pyproject.toml || git commit --quiet --message "chore(release): $tag" pyproject.toml

    git tag --annotate --message "$tag" "$tag"
    git tag --force --annotate --message "$major" "$major" > /dev/null
    # Atomic, so that neither main nor vX moves without vX.Y.Z. Only vX may be overwritten.
    git push --quiet --atomic origin HEAD:refs/heads/main "refs/tags/$tag" "+refs/tags/$major" || fail "push failed, nothing was released"
    trap - EXIT

    echo "Released $tag and moved $major to $(git rev-parse --short HEAD)"

# Run all the tests, in .venv, which is created if missing.
test:
    test -d .venv || python3 -m venv .venv
    .venv/bin/pip install --quiet --require-hashes -r validate/requirements.txt
    .venv/bin/python -m unittest discover -s tests
