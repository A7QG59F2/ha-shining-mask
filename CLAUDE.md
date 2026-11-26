# ha-shining-mask

## Permissions

- This repo is public, so it doesn't ship a Claude Code `.claude/settings.json`. When a task needs `git push` or a pull request and pushing isn't already allowed in the session, ask the user at the start of that session whether to add the git-push rule: allow branch pushes, creating branches and pull requests; block force-pushes, pushes to `main` or `master`, deletes and merges. Don't push until they say yes.

## Pull requests

- Every pull request includes a changelog entry in this repo's `CHANGELOG.md`: newest first, in plain language, saying what changed and what to do after merging. If the repo has no changelog yet, the PR starts one.
