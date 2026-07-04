#!/usr/bin/env python3
# Real-interop regression: the native Rust tunnel server (rrt-runtime, started in
# RRT_TUNNEL_ONLY mode) talking to the ACTUAL Python TunnelClient + a real upstream.
# Complements the in-crate cargo tests (src/runtime/tunnel.rs #[cfg(test)]).
#
# Usage (needs a built rrt-runtime on PATH or at $RRT_RUNTIME, and python deps
# websockets+httpx + yr.sandbox on sys.path):
#   RRT_RUNTIME=/path/to/rrt-runtime python3 tunnel_interop.py
WS, HTTP, UP = 18765, 18766, 18999

# 1) fake upstream the python TunnelClient will forward to
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = f"UPSTREAM-OK:{self.path}".encode()
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); data = self.rfile.read(n)
        body = b"ECHO:" + data
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass
up = http.server.ThreadingHTTPServer(("127.0.0.1", UP), H)
threading.Thread(target=up.serve_forever, daemon=True).start()

# 2) rust tunnel server (standalone)
proc = subprocess.Popen([os.environ.get("RRT_RUNTIME", "rrt-runtime")],
    env={**os.environ, "RRT_TUNNEL_ONLY": "1", "RRT_TUNNEL_WS_PORT": str(WS), "RRT_TUNNEL_HTTP_PORT": str(HTTP)})
for _ in range(50):
    try: socket.create_connection(("127.0.0.1", HTTP), 0.2).close(); break
    except OSError: time.sleep(0.1)

# 3) real python TunnelClient connects to Port A, forwards to upstream
from yr.sandbox.tunnel_client import TunnelClient
tc = TunnelClient(upstream=f"127.0.0.1:{UP}")
ok = tc.start(f"ws://127.0.0.1:{WS}", timeout=10)
assert ok, "TunnelClient failed to connect to rust server"
time.sleep(0.5)

P, F = [], []
def chk(n, c, d=""):
    (P if c else F).append(n); print(f"[{'PASS' if c else 'FAIL'}] {n}  {d}")
try:
    r = httpx.get(f"http://127.0.0.1:{HTTP}/probe", timeout=10)
    chk("GET via tunnel", r.status_code == 200 and r.text == "UPSTREAM-OK:/probe", f"{r.status_code} {r.text!r}")
    r2 = httpx.post(f"http://127.0.0.1:{HTTP}/echo", content=b"hello-rust-tunnel", timeout=10)
    chk("POST body via tunnel", r2.status_code == 200 and r2.text == "ECHO:hello-rust-tunnel", f"{r2.status_code} {r2.text!r}")
finally:
    tc.stop(); proc.terminate()
print(f"INTEROP RESULT pass={len(P)} fail={len(F)} {F}")
sys.exit(1 if F else 0)
