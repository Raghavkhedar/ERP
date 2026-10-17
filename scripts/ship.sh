#!/usr/bin/env bash
# Ship the current feature branch: check, push, open a PR into production,
# wait for CI, merge, then sync production locally and delete the branch.
# Safe to run again if it stops part-way.
# Usage: scripts/ship.sh "PR title" "PR description"
set -euo pipefail

BASE=production
branch=$(git branch --show-current)

if [[ "$branch" == "$BASE" ]]; then
  echo "You are on $BASE. Switch to a feature branch first." >&2
  exit 1
fi
if [[ -n "$(git status --porcelain)" ]]; then
  echo "Uncommitted changes. Commit or stash them first:" >&2
  git status --short >&2
  exit 1
fi

echo "==> Lint, format and tests"
uv run ruff check .
uv run ruff format --check .
uv run pytest -q

echo "==> Pushing $branch"
git push -u origin "$branch"

if gh pr view "$branch" >/dev/null 2>&1; then
  echo "==> PR already open for $branch"
else
  if [[ $# -lt 2 ]]; then
    echo "No PR yet. Usage: scripts/ship.sh \"PR title\" \"PR description\"" >&2
    exit 1
  fi
  echo "==> Opening PR into $BASE"
  gh pr create --base "$BASE" --head "$branch" --title "$1" --body "$2"
fi

echo "==> Waiting for CI"
sleep 10 # give GitHub a moment to start the checks
gh pr checks "$branch" --watch --fail-fast

read -r -p "CI is green. Merge $branch into $BASE? [y/N] " answer
if [[ "$answer" != [yY] ]]; then
  echo "Not merged. Run the script again when ready."
  exit 0
fi

echo "==> Merging"
gh pr merge "$branch" --merge

echo "==> Syncing $BASE"
git switch "$BASE"
git pull --ff-only

if git merge-base --is-ancestor "$branch" "$BASE"; then
  git branch -d "$branch"
  echo "==> Done: $branch is merged and deleted."
  git log --oneline -3
else
  echo "$branch is not in $BASE yet, so it was kept. Check the PR on GitHub." >&2
  exit 1
fi
