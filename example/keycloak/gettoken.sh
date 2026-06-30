KEYCLOAK_URL="http://172.17.0.4:8080"
CLIENT_SECRET="7bdbbbf5ea02234e52ccee46b60ae82"

TOKEN_RESP=$(curl -s -X POST "${KEYCLOAK_URL}/realms/yuanrong/protocol/openid-connect/token" \
      -H "Content-Type: application/x-www-form-urlencoded" \
      -d "client_id=frontend&client_secret=${CLIENT_SECRET}&grant_type=password&username=testuser&password=test123&scope=openidprofile email")

ID_TOKEN=$(echo "$TOKEN_RESP" | grep -o '"id_token":"[^"]*"' | cut -d'"' -f4)

# 2. 调用 IAM token exchange
curl -X POST http://172.17.0.2:31112/iam-server/v1/token/exchange \
      -H "Content-Type: application/json" \
      -d "{\"id_token\": \"${ID_TOKEN}\", \"expires_in\": 3600}"
