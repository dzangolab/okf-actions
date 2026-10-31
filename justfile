default:
    @just --list

# Tag HEAD of main as vX.Y.Z, move vX to it, and push both. VERSION is x.y.z or vx.y.z; asked for if omitted, defaulting to the next minor.
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

    declared=$(sed -nE 's/^version = "(.*)"$/\1/p' pyproject.toml)
    [[ "$declared" == "${tag#v}" ]] || fail "pyproject.toml has version $declared: set it to ${tag#v} and merge that to main first"

    git tag --annotate --message "$tag" "$tag"
    git tag --force --annotate --message "$major" "$major" > /dev/null
    # Atomic, so that vX never moves without vX.Y.Z. Only vX may be overwritten.
    git push --quiet --atomic origin "refs/tags/$tag" "+refs/tags/$major" || {
        git tag --delete "$tag" > /dev/null
        fail "push failed, nothing was released"
    }

    echo "Released $tag and moved $major to $(git rev-parse --short HEAD)"
