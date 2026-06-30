## Keycloak Integration

### Services

- **Keycloak**: `http://172.17.0.4:8080` (Docker container `yr-keycloak`)
- **IAM Server**: `http://172.17.0.2:31112` (inside yr runtime)

### Test Accounts

- **Realm**: `yuanrong`
- **Client**: `frontend` / Secret: `7bdbbbf5ea02234e52ccee46b60ae824`
- **User**: `testuser` / `test123`

### Token Exchange Flow

```bash
# 1. Get Keycloak ID token
KEYCLOAK_URL="http://172.17.0.4:8080"
CLIENT_SECRET="7bdbbbf5ea02234e52ccee46b60ae824"

TOKEN_RESP=$(curl -s -X POST "${KEYCLOAK_URL}/realms/yuanrong/protocol/openid-connect/token" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d "client_id=frontend&client_secret=${CLIENT_SECRET}&grant_type=password&username=testuser&password=test123&scope=openid%20profile%20email")

ID_TOKEN=$(echo "$TOKEN_RESP" | grep -o '"id_token":"[^"]*"' | cut -d'"' -f4)

# 2. Exchange for IAM token
curl -X POST http://172.17.0.2:31112/iam-server/v1/token/exchange \
  -H "Content-Type: application/json" \
  -d "{
    \"id_token\": \"${ID_TOKEN}\",
    \"expires_in\": 3600
  }"
```

### Security Features Implemented

1. **expires_in validation**: 60-7200 seconds
2. **JWT claim validation**: iss, aud, azp, nbf, iat, exp
3. **HTTPS enforcement**: JWKS fetch requires HTTPS
4. **RequestFilter security**: Unified request filtering
5. **Key rotation support**: Auto-refresh JWKS on kid miss

## Keycloak Setup

### Initialize Realm and Users

```bash
cd example/keycloak
./init-realm.sh
```

### Web Console

```
http://localhost:8080/admin
```
- Username: `admin`
- Password: `admin123`


### IAM Token Exchange Returns 404

1. Check IAM server is running: `ps aux | grep iam_server`
2. Check Keycloak is enabled in IAM startup flags: `ps aux | grep iam_server | grep keycloak`
3. Verify new code is installed: `pip show openyuanrong-functionsystem`

### Token Exchange Validation Errors

| Error | Cause | Fix |
|-------|--------|-----|
| `expires_in` out of range | Value not in 60-7200s | Use valid value |
| `JWT issuer validation failed` | Wrong realm/URL | Check `--keycloak_url` and `--keycloak_realm` |
| `JWT audience validation failed` | Wrong client | Check client configuration |
| `JWKS fetch failed` | HTTPS required | Ensure Keycloak uses HTTPS |

## Container Networking

- `yr-keycloak`: `172.17.0.4:8080`
- `dev`/`dev2`: `172.17.0.2/31112` (IAM), `172.17.0.3:31112` (alt)

Use `docker ps` to check current IP mappings.
