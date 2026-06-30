#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAILPIT_DIR="${SCRIPT_DIR}/.mailpit"

mkdir -p "${MAILPIT_DIR}"

echo "==== 1. Starting Mailpit via Docker ===="
# Ensure network exists
docker network inspect yr-net >/dev/null 2>&1 || docker network create yr-net

cd "${SCRIPT_DIR}"
docker compose up -d mailpit

echo "==== 2. Configuring Casdoor email provider for Mailpit ===="
# Note: Casdoor connects to Mailpit using the service name 'mailpit' on the same Docker network
MAILPIT_SMTP_HOST="mailpit"
MAILPIT_SMTP_HOST="${MAILPIT_SMTP_HOST}" python - <<'PY'
import json
import time
import os
import urllib.request
import http.cookiejar

BASE = "http://localhost:8000"
APPLICATION_ID = "admin/yuanrong"
PROVIDER_OWNER = "admin"
EMAIL_PROVIDER_NAME = "provider_email_mailpit"
MAILPIT_HOST = os.environ["MAILPIT_SMTP_HOST"]


def wait_ready(url: str, timeout: int = 60) -> None:
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(url, timeout=3):
                return
        except Exception:
            time.sleep(2)
    raise RuntimeError(f"Timed out waiting for {url}")


def open_json(opener, req_or_url):
    with opener.open(req_or_url) as resp:
        return json.load(resp)


wait_ready(BASE)

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

login_payload = json.dumps({
    "type": "login",
    "username": "admin",
    "password": "123",
    "organization": "built-in",
    "application": "app-built-in",
}).encode()
login_req = urllib.request.Request(
    BASE + "/api/login",
    data=login_payload,
    headers={"Content-Type": "application/json"},
)
login_resp = open_json(opener, login_req)
if login_resp.get("status") != "ok":
    raise RuntimeError(f"Casdoor login failed: {login_resp}")

providers_resp = open_json(opener, BASE + f"/api/get-providers?owner={PROVIDER_OWNER}")
providers = providers_resp.get("data") or []
existing_provider = next((p for p in providers if p.get("name") == EMAIL_PROVIDER_NAME), None)

provider_obj = {
    "owner": PROVIDER_OWNER,
    "name": EMAIL_PROVIDER_NAME,
    "displayName": "Mailpit Email",
    "category": "Email",
    "type": "SMTP",
    "method": "Password",
    "host": MAILPIT_HOST,
    "port": 1025,
    "disableSsl": True,
    "receiver": "noreply@openyuanrong.org",
    "clientId": "noreply@openyuanrong.org",
    "clientSecret": "dummy",
    "clientId2": "",
    "clientSecret2": "",
    "title": "Your verification code",
    "content": "Your verification code is: %s",
}

if existing_provider is None:
    add_req = urllib.request.Request(
        BASE + "/api/add-provider",
        data=json.dumps(provider_obj).encode(),
        headers={"Content-Type": "application/json"},
    )
    add_resp = open_json(opener, add_req)
    if add_resp.get("status") != "ok":
        raise RuntimeError(f"Add provider failed: {add_resp}")
else:
    existing_provider.update(provider_obj)
    update_req = urllib.request.Request(
        BASE + f"/api/update-provider?id={PROVIDER_OWNER}/{EMAIL_PROVIDER_NAME}",
        data=json.dumps(existing_provider).encode(),
        headers={"Content-Type": "application/json"},
    )
    update_resp = open_json(opener, update_req)
    if update_resp.get("status") != "ok":
        raise RuntimeError(f"Update provider failed: {update_resp}")

app_resp = open_json(opener, BASE + f"/api/get-application?id={APPLICATION_ID}")
app = app_resp.get("data")
if not app:
    raise RuntimeError(f"Application not found: {APPLICATION_ID}")

provider_entries = []
seen = set()
for item in app.get("providers") or []:
    name = item.get("name")
    if name in {EMAIL_PROVIDER_NAME, "provider_captcha_default"}:
        if name == EMAIL_PROVIDER_NAME:
            item["rule"] = "All"
            item["canSignUp"] = True
            item["canSignIn"] = True
        else:
            item["rule"] = "None"
        provider_entries.append(item)
        seen.add(name)
    else:
        provider_entries.append(item)
        seen.add(name)

if "provider_captcha_default" not in seen:
    provider_entries.append({
        "name": "provider_captcha_default",
        "canSignUp": False,
        "canSignIn": False,
        "canUnlink": False,
        "rule": "None",
    })
if EMAIL_PROVIDER_NAME not in seen:
    provider_entries.append({
        "name": EMAIL_PROVIDER_NAME,
        "canSignUp": True,
        "canSignIn": True,
        "canUnlink": False,
        "rule": "All",
    })

app["providers"] = provider_entries

for item in app.get("signupItems") or []:
    if item.get("name") == "Email":
        item["rule"] = "Normal"

update_app_req = urllib.request.Request(
    BASE + f"/api/update-application?id={APPLICATION_ID}",
    data=json.dumps(app).encode(),
    headers={"Content-Type": "application/json"},
)
update_app_resp = open_json(opener, update_app_req)
if update_app_resp.get("status") != "ok":
    raise RuntimeError(f"Update application failed: {update_app_resp}")

print("Mailpit email provider configured for Casdoor.")
print("Mailpit UI: http://localhost:8025")
PY
