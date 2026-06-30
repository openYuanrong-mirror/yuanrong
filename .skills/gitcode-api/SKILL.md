---
name: gitcode-api
description: Use when calling GitCode REST APIs for repositories, issues, or pull requests and you need the live endpoint details that work with fork-based PR flows
---

# GitCode API Skill

## Base URL

```bash
BASE_URL="https://gitcode.com/api/v5"
```

Use `https://gitcode.com/api/v5`. The live PR APIs in this workflow were reached through `gitcode.com`, not `api.gitcode.com`.

## Authentication

| Method | Header/Param |
|--------|--------------|
| Bearer Token | `Authorization: Bearer {token}` |
| Private Token | `PRIVATE-TOKEN: {token}` |
| Query Param | `?access_token={token}` |

Tokens: `https://gitcode.com/setting/token-classic`

## Core Endpoints

### User

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/user` | Get authenticated user |
| GET | `/users/{username}` | Get public user info |
| GET | `/user/repos` | List authenticated user repos |
| GET | `/user/merge_requests` | List authenticated user PRs |

### Repositories

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/repos/{owner}/{repo}` | Get repository info |
| GET | `/repos/{owner}/{repo}/branches` | List branches |
| GET | `/repos/{owner}/{repo}/commits` | List commits |
| GET | `/repos/{owner}/{repo}/contents/{path}` | Get file content |
| GET | `/repos/{owner}/{repo}/git/trees/{sha}` | Get repository tree |
| GET | `/repos/{owner}/{repo}/tags` | List tags |
| GET | `/repos/{owner}/{repo}/forks` | List forks |

### Issues

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/repos/{owner}/{repo}/issues` | List issues |
| GET | `/repos/{owner}/{repo}/issues/{number}` | Get issue |
| POST | `/repos/{owner}/issues` | Create issue |
| PATCH | `/repos/{owner}/issues/{number}` | Update issue |
| GET | `/repos/{owner}/{repo}/issues/{number}/comments` | List comments |
| POST | `/repos/{owner}/{repo}/issues/{number}/comments` | Create comment |

### Pull Requests

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/repos/{owner}/{repo}/pulls` | Create PR |
| GET | `/repos/{owner}/{repo}/pulls` | List PRs |
| GET | `/repos/{owner}/{repo}/pulls/{number}` | Get PR |
| PATCH | `/repos/{owner}/{repo}/pulls/{number}` | Update PR title/body |
| GET | `/repos/{owner}/{repo}/pulls/{number}/commits` | List PR commits |
| GET | `/repos/{owner}/{repo}/pulls/{number}/files` | List changed files |

### Search

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/search/users?q={keyword}` | Search users |
| GET | `/search/repositories?q={keyword}` | Search repositories |
| GET | `/search/issues?q={keyword}` | Search issues |

## Working Patterns

### Create a fork PR

```bash
curl -sS -X POST "${BASE_URL}/repos/${owner}/${repo}/pulls" \
  -H "Content-Type: application/json" \
  -H "PRIVATE-TOKEN: ${GITCODE_APIKEY}" \
  -d '{
    "head": "<fork_owner>:<source_branch>",
    "base": "<target_branch>",
    "title": "fix[<module>]: summary",
    "body": "PR body",
    "fork_path": "<fork_owner>/<fork_repo>"
  }'
```

### Update an existing PR

```bash
curl -sS -X PATCH "${BASE_URL}/repos/${owner}/${repo}/pulls/${pr_number}" \
  -H "Content-Type: application/json" \
  -H "PRIVATE-TOKEN: ${GITCODE_APIKEY}" \
  -d '{
    "title": "New Title",
    "body": "Updated PR body"
  }'
```

## Important Notes

- Push the source branch before creating the PR.
- For fork PRs, set `head` to `fork_owner:branch`.
- Keep `fork_path`, but do not rely on it alone. In live calls, `fork_path` without `head: fork_owner:branch` was not enough.
- Prefer `web_url`, then `html_url`, then `url` when extracting the final PR link from the response.
- `GET /repos/{owner}/{repo}/contents/{path}` returns file content metadata; use it when you need to inspect templates such as `.gitee/PULL_REQUEST_TEMPLATE/PULL_REQUEST_TEMPLATE.en.md`.
- `GET /repos/{owner}/{repo}/branches` and `GET /repos/{owner}/{repo}/commits?sha=<branch>` are the quickest checks when you need to confirm a branch was pushed before creating a fork PR.

## Quick Examples

### Get repo info

```bash
curl -sS -H "PRIVATE-TOKEN: ${GITCODE_APIKEY}" \
  "${BASE_URL}/repos/<owner>/<repo>"
```

### Check a fork branch exists

```bash
curl -sS -H "PRIVATE-TOKEN: ${GITCODE_APIKEY}" \
  "${BASE_URL}/repos/<fork_owner>/<fork_repo>/branches/<urlencoded_branch>"
```

### Read the PR template

```bash
curl -sS -H "PRIVATE-TOKEN: ${GITCODE_APIKEY}" \
  "${BASE_URL}/repos/<owner>/<repo>/contents/.gitee/PULL_REQUEST_TEMPLATE/PULL_REQUEST_TEMPLATE.en.md"
```

### List PR files

```bash
curl -sS -H "PRIVATE-TOKEN: ${GITCODE_APIKEY}" \
  "${BASE_URL}/repos/<owner>/<repo>/pulls/<pr_number>/files"
```

## Common Mistakes

- Using `https://api.gitcode.com/api/v5` instead of `https://gitcode.com/api/v5`
- Creating the PR before pushing the fork branch
- Using `head: "branch-name"` instead of `head: "fork_owner:branch-name"` for fork PRs
- Returning the raw API response instead of the PR URL
