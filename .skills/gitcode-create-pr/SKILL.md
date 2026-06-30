---
name: gitcode-create-pr
description: Use when creating or updating a GitCode pull request in the yuanrong repository, especially for the normal fork-to-upstream flow where the branch must be pushed to origin, the PR must target upstream, and the repo template and title format must be followed
---

# GitCode PR For Yuanrong

## Overview

Create or update GitCode pull requests for this repository with the GitCode API.

This skill is **yuanrong-specific**:

- `origin` is normally your fork, for example `git@gitcode.com:yuchaow/yuanrong.git`
- `upstream` is the shared target repo, normally `git@gitcode.com:openeuler/yuanrong.git`
- the default PR target is usually `upstream/master`
- the PR body should follow `.gitee/PULL_REQUEST_TEMPLATE/PULL_REQUEST_TEMPLATE.en.md`

## Default Repo Policy

For this repository, the normal workflow is:

1. commit on the current working branch
2. push the branch to `origin`
3. create the PR against `upstream`

**Do not push working branches to `upstream` by default.**

Treat upstream pushes as exceptional. Only push to `upstream` when:

- the user explicitly asks for an upstream push
- repository policy clearly requires a same-repo branch

If neither is true, push to `origin` and open a fork PR to `upstream`.

## Auto-Detection

Run these checks first:

```bash
git remote -v
git branch --show-current
git log -1 --format="%B" | grep -qi "Signed-off-by" && echo "SIGNED=1" || echo "SIGNED=0"
git log -1 --format="%s" | grep -E "^(fix|feat|docs|style|refactor|test|chore|perf|ci|build|revert)" && echo "PREFIX=OK" || echo "PREFIX=BAD"
cat .gitee/PULL_REQUEST_TEMPLATE/PULL_REQUEST_TEMPLATE.en.md 2>/dev/null || \
cat .gitcode/PULL_REQUEST_TEMPLATE/PULL_REQUEST_TEMPLATE.en.md 2>/dev/null || \
echo "TEMPLATE_NOT_FOUND"
echo "GITCODE_APIKEY=${GITCODE_APIKEY:+set}"
```

For yuanrong, expect:

- `origin` = personal fork
- `upstream` = `openeuler/yuanrong`
- current branch = working branch to publish
- API key must be set

## Required Inputs

- `source_branch`: current working branch
- `target_branch`: normally `master`, unless the user specifies another base
- `title`: PR title
- `body`: markdown PR body

For the normal fork workflow also collect:

- `owner=openeuler`
- `repo=yuanrong`
- `fork_owner` from `origin`
- `fork_repo` from `origin`

## Commit Requirements

Commits prepared for the PR should satisfy this pattern:

```regex
^(fix|feat|docs|style|refactor|test|chore|perf|ci|build|revert)(\([^)]+\)|\[[^\]]+\])?:.+[\s\S]*Signed-off-by:.+<.+@.+>
```

Practical rules for yuanrong:

- the commit subject must start with one of `fix|feat|docs|style|refactor|test|chore|perf|ci|build|revert`
- optional scope may use either `(scope)` or `[scope]`
- the message body must include a `Signed-off-by:` trailer
- use `git commit -s`

If `Signed-off-by` is missing:

```bash
git commit --amend --no-edit --signoff
```

## PR Title And Body Rules

This repository's PR template requires:

- `/kind <type>` near the top
- a summary section
- an issue section
- an API/interface section
- a checklist section

The template also says the MR title should look like:

```text
fix[module-name]: short description
```

For yuanrong, prefer concrete module scopes such as:

- `cli`
- `sandbox`
- `functionsystem`
- `datasystem`
- `build`
- `docs`
- `yr-k8s`

## Push Rules

### Normal yuanrong fork workflow

Push to `origin`, not `upstream`:

```bash
git push origin <source_branch>
# If branch doesn't exist remotely:
git push -u origin <source_branch>
```

If the commit was amended after a previous push:

```bash
git push -f origin <source_branch>
```

### Upstream push

Only do this if the user explicitly requests it:

```bash
git push upstream <source_branch>
git push -u upstream <source_branch>
```

Before doing this, restate to yourself that this is an explicit exception, not the default.

## Create The PR

### Fork PR to upstream (default for yuanrong)

Use Python, not curl:

```python
import urllib.request, json, os

data = json.dumps({
    "head": f"{fork_owner}:{source_branch}",
    "base": target_branch,
    "title": title,
    "body": body,
    "fork_path": f"{fork_owner}/{fork_repo}",
}).encode()

req = urllib.request.Request(
    f"https://gitcode.com/api/v5/repos/{owner}/{repo}/pulls",
    data=data,
    headers={
        "Content-Type": "application/json",
        "PRIVATE-TOKEN": os.environ["GITCODE_APIKEY"],
    },
    method="POST",
)

with urllib.request.urlopen(req) as resp:
    result = json.loads(resp.read())
    print(result["web_url"], "iid:", result["iid"])
```

Use:

- `owner="openeuler"`
- `repo="yuanrong"`
- `target_branch="master"` unless the user specifies otherwise

### Same-repo PR

Only use this when the branch was intentionally pushed to `upstream`:

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
    headers={
        "Content-Type": "application/json",
        "PRIVATE-TOKEN": os.environ["GITCODE_APIKEY"],
    },
    method="POST",
)

with urllib.request.urlopen(req) as resp:
    result = json.loads(resp.read())
    print(result["web_url"], "iid:", result["iid"])
```

## Update A PR

```python
import urllib.request, json, os

data = json.dumps({"title": new_title, "body": new_body}).encode()
req = urllib.request.Request(
    f"https://gitcode.com/api/v5/repos/openeuler/yuanrong/pulls/{pr_number}",
    data=data,
    headers={
        "Content-Type": "application/json",
        "PRIVATE-TOKEN": os.environ["GITCODE_APIKEY"],
    },
    method="PATCH",
)

with urllib.request.urlopen(req) as resp:
    print(json.loads(resp.read())["web_url"])
```

## Yuanrong Checklist

Before creating the PR, confirm all of:

- [ ] branch is pushed to `origin` unless the user explicitly requested upstream push
- [ ] PR target repo is `upstream` / `openeuler/yuanrong`
- [ ] base branch is `master` unless the user specified another base
- [ ] `head` uses `fork_owner:source_branch` for fork PRs
- [ ] `fork_path` is present for fork PRs
- [ ] latest commit has allowed prefix
- [ ] latest commit has `Signed-off-by`
- [ ] PR body follows `.gitee/.../PULL_REQUEST_TEMPLATE.en.md`
- [ ] PR title uses `type[module]: description` style

## Common Mistakes

- Pushing the work branch to `upstream` out of habit
- Using `origin` as the PR target repo instead of `upstream`
- Forgetting that yuanrong normally wants fork PRs even when `upstream` exists
- Using bare `head: "<branch>"` for a fork PR
- Skipping the repo template sections
- Using a PR title that doesn't match `type[module]: description`
- Using `curl` with multiline markdown body
