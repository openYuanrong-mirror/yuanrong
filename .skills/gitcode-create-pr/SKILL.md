---
name: gitcode-create-pr
description: Use when creating or updating a GitCode pull request, especially for fork-to-upstream flows where head/base formatting and push order matter
---

# GitCode PR

## Overview

Create or update GitCode pull requests with the GitCode API.

Use the repository PR template at `.gitee/PULL_REQUEST_TEMPLATE/PULL_REQUEST_TEMPLATE.en.md` when preparing the PR body.

## Required Inputs

- `owner`: target repository owner
- `repo`: target repository name
- `source_branch`: branch containing the changes
- `target_branch`: branch to merge into
- `title`: PR title
- `body`: PR description in markdown

For fork PRs also collect:

- `fork_owner`
- `fork_repo`

## Commit Requirements

Commits prepared for the PR should satisfy this pattern:

```regex
^(fix|feat|docs|style|refactor|test|chore|perf|ci|build|revert)(\([^)]+\)|\[[^\]]+\])?:.+[\s\S]*Signed-off-by:.+<.+@.+>
```

Practical rules:

- The subject must start with one of `fix|feat|docs|style|refactor|test|chore|perf|ci|build|revert`
- An optional scope may use either `(scope)` or `[scope]`
- The message body must include a `Signed-off-by:` trailer
- Use `git commit -s` so the trailer is generated correctly
- Reject or rewrite commits that do not meet this format before opening the PR

## Create a PR

### 1. Amend commit to add Signed-off-by (if missing)

```bash
git commit --amend --no-edit --signoff
```

### 2. Push the source branch

```bash
git push <fork-remote> <source_branch>
# If the commit was amended after a previous push:
git push -f <fork-remote> <source_branch>
```

### 3. Create the PR

`curl` fails with shell-escaped JSON when the body contains newlines or special
characters. **Use Python instead** — it handles quoting correctly:

Same-repository PR:

```python
import urllib.request, json, os
data = json.dumps({
    "head": source_branch,
    "base": target_branch,
    "title": title,
    "body": body,
}).encode()
req = urllib.request.Request(
    f"https://gitcode.com/api/v5/repos/{owner}/{repo}/pulls",
    data=data,
    headers={"Content-Type": "application/json",
             "PRIVATE-TOKEN": os.environ["GITCODE_APIKEY"]},
    method="POST",
)
with urllib.request.urlopen(req) as resp:
    result = json.loads(resp.read())
    print(result["web_url"], "  iid:", result["iid"])
```

Cross-repository PR from a fork:

```python
import urllib.request, json, os
data = json.dumps({
    "head": f"{fork_owner}:{source_branch}",   # MUST include fork_owner prefix
    "base": target_branch,
    "title": title,
    "body": body,
    "fork_path": f"{fork_owner}/{fork_repo}",
}).encode()
req = urllib.request.Request(
    f"https://gitcode.com/api/v5/repos/{owner}/{repo}/pulls",
    data=data,
    headers={"Content-Type": "application/json",
             "PRIVATE-TOKEN": os.environ["GITCODE_APIKEY"]},
    method="POST",
)
with urllib.request.urlopen(req) as resp:
    result = json.loads(resp.read())
    print(result["web_url"], "  iid:", result["iid"])
```

The response JSON contains `web_url` and `iid` (PR number) on success.

## Update a PR

```python
import urllib.request, json, os
data = json.dumps({"title": new_title, "body": new_body}).encode()
req = urllib.request.Request(
    f"https://gitcode.com/api/v5/repos/{owner}/{repo}/pulls/{pr_number}",
    data=data,
    headers={"Content-Type": "application/json",
             "PRIVATE-TOKEN": os.environ["GITCODE_APIKEY"]},
    method="PATCH",
)
with urllib.request.urlopen(req) as resp:
    print(json.loads(resp.read())["web_url"])
```

## Notes

- GitCode fork PRs **require** `head` to be `fork_owner:branch` — bare branch names
  return `400 head或base不能为空`.
- `fork_path` supplements `head` but does not replace the owner prefix.
- If the API returns `400 head或base不能为空`, the `head` format is wrong — add the
  `fork_owner:` prefix.
- Before creating or updating a PR, verify the branch history does not contain
  commits that violate the required commit-message pattern.
- The `Signed-off-by:` trailer must appear **after** `Co-authored-by:` if both
  are present.

## Common Mistakes

- Creating the PR before pushing the source branch
- Using `https://api.gitcode.com/api/v5` instead of `https://gitcode.com/api/v5`
- Using `curl` with multi-line body strings — special characters break JSON escaping;
  use Python `json.dumps` instead
- Using bare `head: "<branch>"` for fork PRs (missing `fork_owner:` prefix)
- Forgetting the `Signed-off-by:` trailer or using a subject prefix outside the allowed set
- Omitting the repository PR template when writing the body
