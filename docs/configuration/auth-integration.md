# Authentication Configuration Guide

## Overview

This document provides detailed configuration instructions for integrating yuanrong with external identity providers (Casdoor or Keycloak).

## Provider Selection

The `auth.provider` setting in `config.toml` determines which provider is used.

```toml
[auth]
provider = "casdoor" # Default and recommended
```

---

## 1. Casdoor Configuration (Recommended)

### Frontend Configuration (config.toml)

```toml
[casdoorConfig]
endpoint = "http://casdoor:8000"           # Internal endpoint for server-side calls
publicEndpoint = "http://yuanrong.org:8000" # Browser-facing URL (public)
organization = "yuanrong"                   # Casdoor organization name
application = "app-yuanrong"                # Casdoor application name
clientId = "<client-id>"                    # OAuth2 Client ID
clientSecret = "<client-secret>"            # OAuth2 Client Secret
jwtPublicKey = """
-----BEGIN PUBLIC KEY-----
...
-----END PUBLIC KEY-----
"""                                          # Application JWT Public Key
enabled = true                               # Enable Casdoor integration
```

### iam-server CLI Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--auth_provider` | `casdoor` | Set to `casdoor` |
| `--casdoor_enabled` | `false` | Enable/disable Casdoor integration |
| `--casdoor_endpoint` | `""` | Casdoor internal API endpoint |
| `--casdoor_organization` | `""` | Casdoor organization name |
| `--casdoor_application` | `""` | Casdoor application name |
| `--casdoor_client_id` | `""` | Casdoor OAuth2 client ID |
| `--casdoor_client_secret` | `""` | Casdoor OAuth2 client secret |
| `--casdoor_jwt_public_key` | `""` | Casdoor JWT public key (content or file path) |

---

## 2. Keycloak Configuration (Legacy)

### Frontend Configuration (config.toml)

```toml
[keycloakConfig]
url = "http://keycloak:8080"           # Keycloak service URL (public)
realm = "yuanrong"                      # Realm name
clientId = "frontend"                   # OAuth2 Client ID
clientSecret = "${KEYCLOAK_CLIENT_SECRET}" # Client secret (use env var)
enabled = true                          # Enable Keycloak integration
```

### iam-server CLI Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--auth_provider` | `casdoor` | Set to `keycloak` for legacy |
| `--keycloak_enabled` | `false` | Enable Keycloak integration |
| `--keycloak_url` | `""` | Keycloak service URL |
| `--keycloak_realm` | `""` | Keycloak realm name |

---

## 3. Redirect URI Requirements

Regardless of the provider, you must configure a Redirect URI in the IdP's dashboard:

- **Casdoor**: `Applications` -> `app-yuanrong` -> `Redirect URLs` -> `http://<your-public-domain>/auth/callback`
- **Keycloak**: `Clients` -> `frontend` -> `Valid Redirect URIs` -> `http://<your-public-domain>/auth/callback`

## 4. Troubleshooting

- **Check Logs**: 
  - `iam-server`: Look for "Casdoor integration is not enabled" or "JWT signature verification failed".
  - `frontend`: Look for "failed to exchange code" or "redirect_uri mismatch".
- **Verify Public Keys**: For Casdoor, ensure the `jwtPublicKey` matches exactly what is displayed in the Casdoor UI for your application.
- **Clock Sync**: Ensure all servers have synchronized time to avoid JWT expiration issues.
