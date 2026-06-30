# Authentication Integration Guide

## Overview

The yuanrong system supports multiple external identity providers (IdP) for user authentication and authorization. The current architecture primarily uses **Casdoor** as the default identity provider due to its lightweight nature and support for advanced features like quota management. **Keycloak** is also supported for legacy installations or specific enterprise requirements.

The integration follows a hybrid authentication model:

- **External IdP (Casdoor/Keycloak)**: Manages user authentication via OAuth2/OIDC.
- **iam-server**: Handles token exchange, issues internal JWTs, and manages service-to-service authentication.
- **Frontend**: Orchestrates the login flow and handles browser-side session management.

## 1. Casdoor Integration (Recommended)

Casdoor is a Go-based, lightweight UI-first identity provider. It is the recommended choice for yuanrong.

### Architecture

```text
                          ┌─────────────────────────────────────────────┐
                          │                  YuanRong                   │
                          │                                             │
   ┌─────────┐            │  ┌───────────┐           ┌──────────────┐  │
   │ Browser │──OAuth2───▶│  │ Frontend  │──code──▶  │  iam-server  │  │
   │ / CLI   │◀──cookie──│  │  (Go/Gin) │  exchange  │   (C++)      │  │
   └─────────┘            │  └─────┬─────┘           └──────┬───────┘  │
                          │        │                        │          │
                          │        │  auth URL              │  JWT     │
                          │        │  redirection           │  verify  │
                          │        ▼                        ▼          │
                          │  ┌─────────────────────────────────────┐   │
                          │  │           Casdoor (Go)              │   │
                          │  │  Org: yuanrong                      │   │
                          │  │  App: app-yuanrong                  │   │
                          │  └─────────────────────────────────────┘   │
                          └─────────────────────────────────────────────┘
```

### Key Features

- **Lightweight**: Low memory footprint (~150MB).
- **Quota Management**: User CPU and Memory quotas are stored in Casdoor's `Custom Fields` and injected into the internal IAM token.
- **Rich Social Login**: Supports various social providers and email/SMS registration.

### Configuration

#### Frontend (config.toml)

```toml
[auth]
provider = "casdoor"  # Options: "casdoor", "keycloak"

[casdoorConfig]
endpoint = "http://casdoor:8000"
publicEndpoint = "http://yuanrong.org:8000" # Browser-facing URL
organization = "yuanrong"
application = "app-yuanrong"
clientId = "<client-id>"
clientSecret = "<client-secret>"
jwtPublicKey = "<rsa-public-key-content>"
enabled = true
```

#### iam-server (CLI Flags)

| Flag | Description |
|------|-------------|
| `--auth_provider` | Set to `casdoor` |
| `--casdoor_enabled` | Enable Casdoor integration |
| `--casdoor_endpoint` | Internal API endpoint |
| `--casdoor_organization` | Casdoor organization name |
| `--casdoor_application` | Casdoor application name |
| `--casdoor_client_id` | OAuth2 client ID |
| `--casdoor_client_secret` | OAuth2 client secret |
| `--casdoor_jwt_public_key` | Public key for JWT verification |

## 2. Keycloak Integration (Legacy)

Keycloak is a powerful, enterprise-grade identity provider. While still supported, it is no longer the primary focus of new feature development.

### Configuration

#### Frontend (config.toml)

```toml
[auth]
provider = "keycloak"

[keycloakConfig]
url = "http://keycloak:8080"
realm = "yuanrong"
clientId = "frontend"
clientSecret = "${KEYCLOAK_CLIENT_SECRET}"
enabled = true
```

#### iam-server (CLI Flags)

| Flag | Description |
|------|-------------|
| `--auth_provider` | Set to `keycloak` |
| `--keycloak_enabled` | Enable Keycloak integration |
| `--keycloak_url` | Keycloak service URL |
| `--keycloak_realm` | Realm name |

## 3. Token Exchange Flow

Both providers use a similar token exchange flow to provide a unified experience within the yuanrong system.

1. **Authentication**: User logs in via Casdoor/Keycloak.
2. **Code Exchange**: The Frontend receives an authorization `code` and sends it to `iam-server`.
3. **Verification**: `iam-server` verifies the code (or ID Token) with the configured IdP.
4. **Internal Token Issuance**: `iam-server` issues a signed internal JWT containing:
   - User identity
   - Roles (mapped from IdP roles)
   - Resource quotas (fetched from IdP attributes)
5. **Session**: The Frontend sets the internal JWT in an `iam_token` HttpOnly cookie.

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/auth/login` | GET | Redirect to IdP login page |
| `/auth/callback` | GET | Handle OAuth2 callback |
| `/auth/token/exchange` | POST | Exchange external ID Token for IAM token |
| `/auth/user` | GET | Get current user info & quotas |

## 4. Quota Management (Casdoor Only)

One of the primary reasons for moving to Casdoor is integrated quota management.

- **Storage**: Quotas are stored in Casdoor user custom fields (`cpu_limit`, `mem_limit`).
- **Propagation**: During token exchange, `iam-server` reads these fields and includes them in the internal JWT claims.
- **Enforcement**: The `functionsystem` parses the internal JWT and enforces these limits using cgroups.

## 5. Troubleshooting

### Redirect URI Issues

Ensure that the `Redirect URI` configured in Casdoor/Keycloak matches exactly with the `publicEndpoint` of your Frontend (usually `http://<domain>/auth/callback`).

### JWT Verification Failure

For Casdoor, ensure the `jwtPublicKey` in `config.toml` matches the public key provided in the Casdoor UI for the corresponding application.

### Provider Mismatch

If you change the `auth.provider` in one service, ensure all services (`frontend`, `iam-server`) are updated and restarted.
