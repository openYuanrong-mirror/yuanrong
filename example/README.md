# Example Layout

The `example/` directory is organized by scenario instead of keeping all
artifacts at the top level.

- `casdoor/`: Casdoor-based authentication setup and bootstrap scripts.
- `keycloak/`: Keycloak-based authentication setup and bootstrap scripts.
- `others/`: small standalone sample files kept for reference.
- `traefik/`: reverse proxy configuration used by auth examples.
- `webterminal/`: webterminal demo runtime and launch scripts.

Top-level helper scripts kept here:

- `restart.sh`: reinstall package artifacts and restart Yuanrong.
- `restart_local.sh`: restart without reinstalling wheel artifacts.

Maintained sandbox deployment surfaces live under `deploy/sandbox/`:

- `deploy/sandbox/docker/`: Docker Compose all-in-one sandbox deployment.
- `deploy/sandbox/k8s/`: Kubernetes and Helm sandbox deployment.
