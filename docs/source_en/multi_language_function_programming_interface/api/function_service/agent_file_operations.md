# Agent Instance File Operations

## Description

This group of APIs performs file upload, download, listing, and directory creation operations within an already-created Agent instance's filesystem. All operations are streamed through the existing TCP tunnel to the Agent Executor HTTP server, reusing the same authenticated connection as SSH, WebSocket, and other channels.

## Constraints

- `instanceId` must be the `instance_id` (UUID) returned when the Agent instance was created. A non-existent or already-deleted instance returns 404.
- Authentication goes through frontend's global `GlobalJWTAuthMiddleware`, consistent with other function service REST APIs. When `enable_func_token_auth` is on, a valid JWT must be carried (see the auth section of [Agent Instance Protocol Invocation Channels](./agent_invoke_channels.md)).
- File upload size cap is **512MB** (`maxFileUploadSize`). Frontend validates `Content-Length` before reading the body; requests exceeding 513MB (512MB + 1MB multipart overhead allowance) are rejected immediately with 413. Requests with `Content-Length` between 512MB and 513MB pass the pre-check, but if the actual file content (excluding multipart boundary overhead) exceeds 512MB, the streaming transfer is aborted and 413 is returned. In both cases, the 413 response is sent before the response body, so clients can detect the error accordingly, reduce the file size, and retry.
- Download supports HTTP `Range` header for resumable transfers. Downloading an empty file (0 bytes) with a Range header returns 416 (per RFC 7233); without a Range header, it returns 200 with an empty response body.
- Upload uses `multipart/form-data` encoding; the `path` field must precede the `file` field.
- Upload overwrites if the target file already exists (atomic replace via temporary file)
- The `path` parameter for all interfaces is an absolute path inside the instance. All callers must have passed JWT authentication and are considered trusted. Security is guaranteed by the Agent instance's own filesystem isolation (container-level or process-level sandbox); no additional path traversal validation is performed. Paths containing NUL bytes (`\x00`) return 400.
- The `mode` parameter accepts 3-4 digit octal strings (regex `^[0-7]{3,4}$`), e.g. `644`, `755`, `4755`. Invalid formats (e.g. `abc`, `999`, `7x5`) return 400. Special bits (SUID `4xxx`, SGID `2xxx`, sticky `1xxx`) are allowed, consistent with standard `chmod` behavior. The caller is responsible for the permissions they set within the instance.

## Upload File

### URI

`POST /api/agent/:instanceId/files/upload`

### Request Parameters

#### Request Path Parameters

| **Parameter** | **Required** | **Type** | **Description** |
| -------- | ---------- | ---------- | ----------- |
| instanceId | Yes | string | Instance ID (the UUID returned at creation). |

#### Request Query Parameters

| **Parameter** | **Required** | **Type** | **Description** |
| -------- | ---------- | ---------- | ----------- |
| mode | No | string | File permissions (3-4 digit octal, e.g. `644`, `755`, `4755`). If empty, not set. Invalid format returns 400. |

#### Request Body Parameters (multipart/form-data)

| **Name** | **Type** | **Required** | **Description** |
| -------- | ------ | ---------- | ----------- |
| path | string | Yes | Upload target path (absolute path inside the instance). **Must precede the `file` field.** |
| file | binary | Yes | File content. |

### Response Parameters

| **Name** | **Type** | **Description** |
| -------- | -------- | -------- |
| code | int | Status code; `200` means success. |
| success | boolean | Whether the upload succeeded. |
| path | string | Actual written path. |
| size | int | Actual bytes written. |

### Examples

```bash
curl -X POST "http://{frontend}:8888/api/agent/0b6c6322-6533-4901-8000-00000000bb0b/files/upload?mode=644" \
  -F "path=/home/agentos/upload.bin" \
  -F "file=@./local_file.bin"
# When auth is on, carry: -H "X-Auth: <jwt>"
```

Response:

```json
{"code":200,"success":true,"path":"/home/agentos/upload.bin","size":1048576}
```

### Error Codes

| **HTTP status** | **Description** |
| -------- | -------- |
| 200 | Upload succeeded. |
| 400 | Bad request. `path` is empty, `file` field is missing, `path` field does not precede `file`, `mode` format is invalid, or multipart parsing failed. |
| 404 | Instance does not exist or has been deleted. |
| 413 | File size exceeds the 512MB limit. |
| 500 | Internal server error. OS-level error during file write (e.g. insufficient disk space), or target path is an existing directory. |

## Download File

### URI

`GET /api/agent/:instanceId/files/download`

### Request Parameters

#### Request Path Parameters

| **Parameter** | **Required** | **Type** | **Description** |
| -------- | ---------- | ---------- | ----------- |
| instanceId | Yes | string | Instance ID (the UUID returned at creation). |

#### Request Query Parameters

| **Parameter** | **Required** | **Type** | **Description** |
| -------- | ---------- | ---------- | ----------- |
| path | Yes | string | Download file path (absolute path inside the instance). |

#### Request Header Parameters

| **Parameter** | **Required** | **Type** | **Description** |
| -------- | ---------- | ---------- | ----------- |
| Range | No | string | Standard HTTP Range header for resumable download. Format `bytes=<start>-<end>`, e.g. `bytes=0-1023`. |

### Response Parameters

The response body is the binary stream of the file. Response headers include:

| **Name** | **Type** | **Description** |
| -------- | -------- | -------- |
| Content-Type | string | Always `application/octet-stream`. |
| Content-Length | string | Response body byte count. On Range requests, this is the slice length (not the total file size). |
| Accept-Ranges | string | Always `bytes`, indicating resumable download support. |
| Content-Range | string | Only returned on successful Range requests. Format `bytes <start>-<end>/<total>`. |

### Examples

```bash
# Full download
curl -o ./downloaded.bin "http://{frontend}:8888/api/agent/0b6c6322-6533-4901-8000-00000000bb0b/files/download?path=/home/agentos/data.bin"
# When auth is on, carry: -H "X-Auth: <jwt>"

# Resumable download (from byte 1024 onward)
curl -o ./rest.bin -H "Range: bytes=1024-" "http://{frontend}:8888/api/agent/0b6c6322-6533-4901-8000-00000000bb0b/files/download?path=/home/agentos/data.bin"
```

### Error Codes

| **HTTP status** | **Description** |
| -------- | -------- |
| 200 | Download succeeded (no Range header). |
| 206 | Partial content (Range request succeeded). |
| 400 | `path` is empty. |
| 404 | Instance does not exist or file path not found. |
| 416 | Range request not satisfiable (e.g. empty file with Range, start exceeds file size). |
| 500 | Internal server error. OS-level error during file read, or path is a directory. |

## List Files

### URI

`GET /api/agent/:instanceId/files/list`

### Request Parameters

#### Request Path Parameters

| **Parameter** | **Required** | **Type** | **Description** |
| -------- | ---------- | ---------- | ----------- |
| instanceId | Yes | string | Instance ID (the UUID returned at creation). |

#### Request Query Parameters

| **Parameter** | **Required** | **Type** | **Description** |
| -------- | ---------- | ---------- | ----------- |
| path | Yes | string | Target path to list (absolute path inside the instance). Can be a file or directory. When `path` points to a file, `items` contains a single element describing that file. |
| recursive | No | string | Whether to recursively list subdirectories. Values `true`/`false`, default `false`. |
| max_depth | No | int | Maximum recursion depth. Only effective when `recursive=true`; when `recursive=false`, this parameter is ignored. Must be a non-negative integer. When `0` (default), uses the system limit of 20. When a value greater than 20 is provided, it is silently truncated to 20. Negative or non-integer values return 400. |

> **System limits**: Listing returns at most **10000** entries (`DEFAULT_MAX_LIST_ENTRIES`), with a maximum recursion depth of **20** levels (`DEFAULT_MAX_LIST_DEPTH`). When either limit is exceeded, the result is truncated to that limit. Both recursive and non-recursive listing are subject to a 30-second timeout (`DEFAULT_LIST_TIMEOUT_SECONDS`); exceeding it returns a 504 timeout error.

### Response Parameters

| **Name** | **Type** | **Description** |
| -------- | -------- | -------- |
| code | int | Status code; `200` means success. |
| items | array | List of files/directories. Each item see below. |

#### Item

| **Name** | **Type** | **Description** |
| -------- | -------- | -------- |
| name | string | File/directory name. |
| path | string | Full path. |
| size | int | Size in bytes (0 for directories). |
| is_directory | boolean | Whether it is a directory. |
| modified_time | string | Last modified time (ISO 8601 UTC). |
| type | string | `file` or `directory`. |

### Examples

```bash
curl "http://{frontend}:8888/api/agent/0b6c6322-6533-4901-8000-00000000bb0b/files/list?path=/home/agentos&recursive=true&max_depth=2"
# When auth is on, carry: -H "X-Auth: <jwt>"
```

Response:

```json
{
  "code": 200,
  "items": [
    {"name": "data.bin", "path": "/home/agentos/data.bin", "size": 1048576, "is_directory": false, "modified_time": "2026-01-01T00:00:00+00:00", "type": "file"},
    {"name": "logs", "path": "/home/agentos/logs", "size": 0, "is_directory": true, "modified_time": "2026-01-01T00:00:00+00:00", "type": "directory"}
  ]
}
```

### Error Codes

| **HTTP status** | **Description** |
| -------- | -------- |
| 200 | List succeeded. |
| 400 | `path` is empty, or `max_depth` is negative or non-integer. |
| 404 | Instance does not exist or path not found. |
| 504 | Listing timed out (default 30 seconds). |

## Create Directory

### URI

`POST /api/agent/:instanceId/files/mkdir`

### Request Parameters

#### Request Path Parameters

| **Parameter** | **Required** | **Type** | **Description** |
| -------- | ---------- | ---------- | ----------- |
| instanceId | Yes | string | Instance ID (the UUID returned at creation). |

#### Request Query Parameters

| **Parameter** | **Required** | **Type** | **Description** |
| -------- | ---------- | ---------- | ----------- |
| path | Yes | string | Directory path to create (absolute path inside the instance). |
| mode | No | string | Directory permissions (3-4 digit octal, e.g. `755`, `4755`). If empty, not set. Invalid format returns 400. |
| recursive | No | string | Whether to create parent directories. Values `true`/`false`, default `false`. |

### Response Parameters

| **Name** | **Type** | **Description** |
| -------- | -------- | -------- |
| code | int | Status code; `200` means success. |
| success | boolean | Whether the creation succeeded. |
| path | string | Actual created path. |
| created | boolean | Whether the target directory itself was newly created (`false` means it already existed). When `recursive=true` and parent directories are also created, `created` only reflects the final target directory, not intermediate ones. |

### Examples

```bash
curl -X POST "http://{frontend}:8888/api/agent/0b6c6322-6533-4901-8000-00000000bb0b/files/mkdir?path=/home/agentos/subdir&mode=755&recursive=true"
# When auth is on, carry: -H "X-Auth: <jwt>"
```

Response:

```json
{"code":200,"success":true,"path":"/home/agentos/subdir","created":true}
```

### Error Codes

| **HTTP status** | **Description** |
| -------- | -------- |
| 200 | Directory created successfully. |
| 400 | `path` is empty, `mode` format is invalid, or parent directory does not exist (without `recursive=true`). |
| 404 | Instance does not exist or has been deleted. |
| 500 | Internal server error. OS-level error during directory creation. |
