# Sandbox Reverse Tunnel — Design Spec

**Date:** 2026-03-26
**Updated:** 2026-03-31
**Status:** Approved

---

## Problem

Sandbox instances run inside the yuanrong cloud platform. User code
executing in a sandbox cannot directly reach services on the user's local
machine, for example a local HTTP API at `upstream.example.com:8000`. We need a
reverse tunnel so sandbox code can transparently call local services through
a WebSocket-based bidirectional channel.

---

## Goals

- Sandbox code calls a local proxy URL
  (`https://127.0.0.1:{portB}/...`) and transparently reaches a local service
- Supports HTTP, HTTPS, and WebSocket proxying
- Single API call from the user (`yr.sandbox.create(upstream=...)`) with no
  separate server to start
- Reuses existing Traefik/JWT auth — no new auth layer
- Concurrent HTTP and WebSocket requests
- Support inter-sandbox communication via internal URLs

---

## Architecture

```text
[Local Machine]
  yr.sandbox.create(upstream="upstream.example.com:8000")
    ├── creates sandbox in cloud (Port A + Port B)
    └── starts TunnelClient in background thread
              └── connects to Port A via WSS (through Traefik)

  Local Service C: upstream.example.com:8000

         ▲ HTTP / HTTPS / WS
         │
   TunnelClient (local, background thread)
         │ WSS long-lived connection
         ▼
[Cloud Sandbox]
  Port A (:8765)  0.0.0.0   WS   ← Traefik registered, tunnel endpoint
  Port B (:8766)  127.0.0.1 HTTP ← internal proxy for sandbox code

  sandbox code:
    curl https://127.0.0.1:8766/api/data
         ↓ Port B receives
         ↓ sends request frame over WS tunnel (Port A)
         ↓ awaits response frame
         ↓ returns HTTP response
```

---

## Port Assignments

- Port B: `proxy_port` (default `8766`)
  Bind: `127.0.0.1`
  Protocol: HTTP/WS
  Purpose: user-facing proxy for sandbox code; user can override it with
  `proxy_port`
- Port A: `proxy_port - 1` (default `8765`)
  Bind: `0.0.0.0`
  Protocol: WebSocket
  Purpose: internal tunnel endpoint that the SDK reaches through Traefik;
  derived automatically and not user-facing

Port B binds only on loopback — not reachable from outside the sandbox.

---

## Wire Protocol

All messages are JSON frames sent over the WebSocket tunnel (Port A).  
Both HTTP and WebSocket proxy use the same `id`-based concurrent dispatch.

### HTTP Request / Response

```json
// sandbox → TunnelClient
{
  "type": "http_req",
  "id": "uuid-1234",
  "method": "POST",
  "path": "/api/v1/data",
  "headers": {"Content-Type": "application/json"},
  "body": "<base64-encoded>"
}

// TunnelClient → sandbox
{
  "type": "http_resp",
  "id": "uuid-1234",
  "status": 200,
  "headers": {"Content-Type": "application/json"},
  "body": "<base64-encoded>"
}
```

### WebSocket Proxy

```json
// open WS channel
{"type": "ws_connect",   "id": "chan-abc", "path": "/ws/stream"}
{"type": "ws_connected", "id": "chan-abc"}               // ack from client

// bidirectional messages
{"type": "ws_message",   "id": "chan-abc", "data": "...", "binary": false}

// close
{"type": "ws_close",     "id": "chan-abc", "code": 1000, "reason": "done"}
```

### Error Frame

```json
{"type": "error", "id": "uuid-1234", "message": "connection refused"}
```

---

## Components

### `tunnel_server.py` (runs in sandbox)

```text
TunnelServer
  ├── _ws_server      asyncio websockets server on Port A (:8765)
  │     └── _handle_tunnel_conn()   one SDK connection at a time
  │           └── _dispatch_frame() routes incoming frames to pending futures
  └── _http_server    aiohttp server on Port B (:8766, loopback only)
        ├── _handle_http()    HTTP → http_req frame → await future →
        │                     HTTP response
        └── _handle_ws()      WS Upgrade → ws_connect frame → relay messages
```

**Concurrency model:**

- Port A runs one long-lived SDK connection; frames dispatched by `id`
- Port B: each incoming request/WS gets a unique `id`, sends frame, awaits `asyncio.Future`
- `_dispatch_frame()` resolves the correct future when a response/message arrives

### `tunnel_client.py` (runs locally, background thread)

```text
TunnelClient
  ├── connect(tunnel_url)    connects WebSocket to Port A
  ├── _recv_loop()           dispatches incoming frames:
  │     ├── http_req   → httpx request to upstream → http_resp frame back
  │     └── ws_connect → open WS to upstream → relay ws_message / ws_close
  └── ws_channels: dict[id, WebSocketClientProtocol]
```

### `sandbox.py` extensions

```python
@yr.instance
class SandboxInstance:
    """Underlying instance class decorated with @yr.instance."""

    def start_tunnel_server(self, ws_port: int = 8765, http_port: int = 8766) -> None:
        """Start TunnelServer in a background thread within this sandbox instance."""
        import asyncio
        import threading
        from yr.sandbox.tunnel_server import TunnelServer

        def _run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            server = TunnelServer(ws_port=ws_port, http_port=http_port)
            loop.run_until_complete(server.start())
            loop.run_forever()

        t = threading.Thread(target=_run, name="tunnel-server", daemon=True)
        t.start()

    def get_internal_urls(self) -> Dict[int, str]:
        """Return internal cluster URLs for port-forwarded services.

        Reads YR_INTERNAL_HOST_IP and YR_PORT_FORWARDINGS environment variables
        injected by Runtime Manager. Other sandbox instances can call this method
        via RPC to discover how to reach this sandbox's forwarded ports.

        Returns:
            Dict[int, str]: Mapping from container port to internal URL.
                e.g. {8080: "https://192.0.2.1:40001", 9090: "https://192.0.2.1:40002"}
        """
        host_ip = os.environ.get("YR_INTERNAL_HOST_IP", "")
        pf_str = os.environ.get("YR_PORT_FORWARDINGS", "")
        if not host_ip or not pf_str:
            return {}

        result = {}
        for mapping in pf_str.split(";"):
            parts = mapping.split(":")
            if len(parts) >= 3:
                protocol = parts[0].lower()
                host_port = parts[1]
                container_port = int(parts[2])
                scheme = "https" if protocol == "https" else "https"
                result[container_port] = f"https://{host_ip}:{host_port}"
        return result


def create(upstream: str = None, proxy_port: int = 8766, ...) -> Sandbox:
    """Factory function to create a Sandbox with optional reverse tunnel."""
    # Port B = proxy_port (user-facing, loopback-only)
    # Port A = proxy_port - 1 (WS tunnel endpoint, Traefik-registered)
    tunnel_port = proxy_port - 1
    opt = yr.InvokeOptions()
    opt.skip_serialize = True

    if upstream is not None:
        tunnel_pf = yr.PortForwarding(port=tunnel_port)
        opt.port_forwardings = [tunnel_pf]
        instance = SandboxInstance.options(opt).invoke(working_dir, env)

        # Start tunnel server inside sandbox as background thread
        yr.get(instance.start_tunnel_server.invoke(tunnel_port, proxy_port))

        # Build WSS URL for tunnel Port A via Traefik
        instance_id = yr.get(instance.get_name.invoke())
        gateway_host = _get_gateway_host()
        tunnel_url = _build_gateway_url(instance_id, tunnel_port, gateway_host)
        tunnel_ws_url = tunnel_url.replace("https://", "wss://")

        # Start local TunnelClient in background thread
        from yr.sandbox.tunnel_client import TunnelClient
        tunnel_client = TunnelClient(upstream)
        tunnel_client.start(tunnel_ws_url)

        sb = Sandbox(...)
        sb._tunnel_client = tunnel_client
        return sb

    return Sandbox(...)


class Sandbox:
    """Wrapper class for convenient sandbox operations."""

    def get_tunnel_url(self) -> str:
        """Return the internal HTTP proxy URL for sandbox code to call.

        Returns:
            str: e.g. "https://127.0.0.1:8766"

        Raises:
            RuntimeError: if no upstream was configured.
        """
        if self._tunnel_client is None:
            raise RuntimeError("No upstream configured. Pass upstream= to create().")
        return f"https://127.0.0.1:{self._proxy_port}"

    def get_internal_urls(self) -> Dict[int, str]:
        """Return internal cluster URLs for port-forwarded services.

        Other sandbox instances can use these URLs to reach this sandbox's
        forwarded ports on the internal network.

        Returns:
            Dict[int, str]: Mapping from container port to internal URL.
        """
        return yr.get(self._instance.get_internal_urls.invoke())

    def terminate(self):
        """Stop tunnel client (if any) and terminate the sandbox instance."""
        if self._tunnel_client is not None:
            self._tunnel_client.stop()
            self._tunnel_client = None
        self._instance.terminate()
```

---

## User API

### Reverse Tunnel for Local Services

```python
import yr

yr.init()

# proxy_port = Port B (default 8766, user-facing)
# Port A = proxy_port - 1 (default 8765, internal, Traefik-registered)
sb = yr.sandbox.create(
    upstream="upstream.example.com:8000",
    proxy_port=8766,   # optional, default 8766
)

# Get the internal proxy URL for use inside sandbox
url = sb.get_tunnel_url()  # → "https://127.0.0.1:8766"

# Sandbox code accesses local service C transparently
tunnel_url = sb.get_tunnel_url()
result = yr.get(sb.exec(["curl", tunnel_url + "/api/v1/data"]))
print(result)

sb.terminate()
yr.finalize()
```

### Inter-Sandbox Communication

Sandbox instances can discover each other's internal URLs via `get_internal_urls()`:

```python
import yr

yr.init()

# Create sandbox A with port forwarding
sb_a = yr.sandbox.create(ports=["tcp:8080"])

# Get internal URLs that other sandboxes can use to reach sb_a
internal_urls = sb_a.get_internal_urls()
# Returns: {8080: "https://192.0.2.1:40001"}

# Create sandbox B that needs to call sb_a
sb_b = yr.sandbox.create()

# sb_b can now call sb_a via the internal URL
target_url = internal_urls[8080]
result = yr.get(sb_b.exec(["curl", target_url + "/api/data"]))

sb_a.terminate()
sb_b.terminate()
yr.finalize()
```

**Environment Variables (injected by Runtime Manager):**

| Variable | Format | Example |
|----------|--------|---------|
| `YR_INTERNAL_HOST_IP` | IP address | `192.0.2.1` |
| `YR_PORT_FORWARDINGS` | `protocol:host_port:container_port;...` | `tcp:40001:8080;https:40002:443` |

---

## Dependencies

| Library      | Side            | Use                            |
| ------------ | --------------- | ------------------------------ |
| `websockets` | sandbox + local | WS server (Port A) and client  |
| `aiohttp`    | sandbox         | HTTP server (Port B)           |
| `httpx`      | local           | async HTTP client to upstream  |
| `asyncio`    | both            | concurrency                    |

All are pure Python, no new system dependencies.

---

## Limitations & Future Work

- One SDK connection at a time (Port A). If SDK disconnects, in-flight
  requests get error frames; TunnelClient reconnects automatically.
- HTTPS upstream (`https://...`): TunnelClient forwards as-is with no
  MITM/certificate inspection.
- WS-over-WS: supported via channel multiplexing, but each channel is independent.
- No request size limit in v1 — large bodies buffered fully in memory.
- Inter-sandbox communication requires Runtime Manager to inject
  `YR_INTERNAL_HOST_IP` and `YR_PORT_FORWARDINGS` environment variables.
