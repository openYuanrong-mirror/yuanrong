//! Native Rust reverse-tunnel server (replaces spawning the python tunnel_server).
//!
//! Port A (ws_port, 0.0.0.0): WebSocket endpoint the external TunnelClient connects to.
//! Port B (http_port, 127.0.0.1): HTTP/WS surface the sandbox's own code hits; each
//! request is framed (JSON, base64 body) and forwarded over the Port-A WS to the
//! client, which relays it to the real upstream and frames the response back.
//!
//! Wire-compatible with yr/sandbox/tunnel_protocol.py (the TunnelClient stays Python):
//! JSON text frames {type, id, ...}; bodies / binary ws payloads are base64. The server
//! answers the client's app-level PingFrame with a PongFrame (heartbeat), forwards
//! Port-B HTTP as http_req / WS as ws_connect, and resolves http_resp / ws_* by id.

use super::codec::yr_deserialize;
use crate::posix::common::Arg;
use base64::Engine;
use futures_util::{SinkExt, StreamExt};
use rmpv::Value;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Duration, Instant};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::{mpsc, oneshot};
use tokio::task::AbortHandle;
use tokio_tungstenite::tungstenite::protocol::Message;

const HTTP_TIMEOUT: Duration = Duration::from_secs(600);
const WS_CONNECT_TIMEOUT: Duration = Duration::from_secs(10);
/// In-flight HTTP requests are cached this long for resend on client reconnect.
const PENDING_REQUEST_TTL: Duration = Duration::from_secs(120);

fn b64() -> base64::engine::general_purpose::GeneralPurpose {
    base64::engine::general_purpose::STANDARD
}

/// Server-local unique frame id (only needs to be unique among in-flight frames).
fn make_id() -> String {
    static N: AtomicU64 = AtomicU64::new(1);
    format!("rrt-{}", N.fetch_add(1, Ordering::Relaxed))
}

// ───────────────────────── wire frames ─────────────────────────
// Matches tunnel_protocol.py. `body` / ws binary `data` are base64 strings.
#[derive(Serialize, Deserialize, Debug, Clone)]
#[serde(tag = "type")]
enum Frame {
    #[serde(rename = "http_req")]
    HttpReq {
        id: String,
        method: String,
        path: String,
        headers: HashMap<String, String>,
        #[serde(default)]
        body: String,
    },
    #[serde(rename = "http_resp")]
    HttpResp {
        id: String,
        status: u16,
        #[serde(default)]
        headers: HashMap<String, String>,
        #[serde(default)]
        body: String,
    },
    #[serde(rename = "ws_connect")]
    WsConnect {
        id: String,
        path: String,
        headers: HashMap<String, String>,
    },
    #[serde(rename = "ws_connected")]
    WsConnected { id: String },
    #[serde(rename = "ws_message")]
    WsMessage {
        id: String,
        data: String,
        #[serde(default)]
        binary: bool,
    },
    #[serde(rename = "ws_close")]
    WsClose {
        id: String,
        #[serde(default = "default_close_code")]
        code: u16,
        #[serde(default)]
        reason: String,
    },
    #[serde(rename = "error")]
    Error { id: String, message: String },
    #[serde(rename = "ping")]
    Ping { id: String, timestamp: f64 },
    #[serde(rename = "pong")]
    Pong { id: String, timestamp: f64 },
}

fn default_close_code() -> u16 {
    1000
}

impl Frame {
    fn to_msg(&self) -> Message {
        Message::Text(serde_json::to_string(self).unwrap_or_default())
    }
}

// ───────────────────────── shared state ─────────────────────────
#[derive(Default)]
struct State {
    /// Outbound channel to the active TunnelClient WS (None when no client connected).
    sdk_tx: Mutex<Option<mpsc::UnboundedSender<Message>>>,
    /// HTTP request id -> oneshot waiting for the http_resp / error frame.
    pending_http: Mutex<HashMap<String, oneshot::Sender<Frame>>>,
    /// WS channel id -> queue of frames from the client for that channel.
    pending_ws: Mutex<HashMap<String, mpsc::UnboundedSender<Frame>>>,
    /// In-flight HTTP request frames, cached for resend when a client reconnects.
    pending_requests: Mutex<HashMap<String, (Frame, Instant)>>,
}

impl State {
    fn send_to_client(&self, frame: &Frame) -> Result<(), ()> {
        let guard = self.sdk_tx.lock().unwrap();
        match guard.as_ref() {
            Some(tx) => tx.send(frame.to_msg()).map_err(|_| ()),
            None => Err(()),
        }
    }
}

fn aborts() -> &'static Mutex<Vec<AbortHandle>> {
    static A: OnceLock<Mutex<Vec<AbortHandle>>> = OnceLock::new();
    A.get_or_init(|| Mutex::new(Vec::new()))
}

/// Start the native tunnel server. Positional args carry ws_port then http_port
/// (akernel `start_tunnel_server.invoke(ws, http)`). Returns Nil once Port B is
/// listening (parity with the python ready check), Err if it never binds.
pub fn start_tunnel_server(args: &[Arg], deploy_dir: &str) -> Result<Value, String> {
    let pos: Vec<i64> = args
        .iter()
        .skip(2)
        .step_by(2)
        .filter_map(|a| yr_deserialize(&a.value))
        .filter_map(|v| v.as_i64())
        .collect();
    let ws_port = pos.first().copied().unwrap_or(8765) as u16;
    let http_port = pos.get(1).copied().unwrap_or(8766) as u16;
    let _ = deploy_dir;
    rrt_info!("[rrt-runtime] tunnel start ws={ws_port} http={http_port}");

    let handle = tokio::runtime::Handle::try_current()
        .map_err(|_| "no tokio runtime to host tunnel server".to_string())?;
    let state = Arc::new(State::default());
    let jh = handle.spawn(run_servers(ws_port, http_port, state));
    aborts().lock().unwrap().push(jh.abort_handle());

    // Wait for Port B to accept connections (multi-thread runtime serves the
    // spawned task on another worker while we poll here).
    for _ in 0..50 {
        if std::net::TcpStream::connect(("127.0.0.1", http_port)).is_ok() {
            return Ok(Value::Nil);
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    Err(format!(
        "tunnel_server not ready on port {http_port} within 5s"
    ))
}

/// Standalone entry (tools/tests): run the tunnel server forever on the given
/// ports, without the RuntimeRPC dispatch wrapper.
pub async fn run_standalone(ws_port: u16, http_port: u16) {
    run_servers(ws_port, http_port, Arc::new(State::default())).await;
}

async fn run_servers(ws_port: u16, http_port: u16, state: Arc<State>) {
    let porta = match TcpListener::bind(("0.0.0.0", ws_port)).await {
        Ok(l) => l,
        Err(e) => {
            rrt_error!("[rrt-runtime] tunnel port_a_bind_failed ws_port={ws_port} error={e}");
            return;
        }
    };
    let portb = match TcpListener::bind(("127.0.0.1", http_port)).await {
        Ok(l) => l,
        Err(e) => {
            rrt_error!("[rrt-runtime] tunnel port_b_bind_failed http_port={http_port} error={e}");
            return;
        }
    };
    rrt_info!("[rrt-runtime] tunnel listening ws=0.0.0.0:{ws_port} http=127.0.0.1:{http_port}");
    serve(porta, portb, state).await;
}

/// Drive both accept loops over pre-bound listeners (split out for tests).
async fn serve(porta: TcpListener, portb: TcpListener, state: Arc<State>) {
    let s2 = state.clone();
    tokio::join!(accept_port_a(porta, state), accept_port_b(portb, s2));
}

// ───────────────────────── Port A: TunnelClient WS ─────────────────────────
async fn accept_port_a(listener: TcpListener, state: Arc<State>) {
    loop {
        match listener.accept().await {
            Ok((stream, _)) => {
                let st = state.clone();
                tokio::spawn(async move {
                    if let Err(e) = handle_client(stream, st).await {
                        rrt_warn!("[rrt-runtime] tunnel client_conn_ended error={e}");
                    }
                });
            }
            Err(e) => {
                rrt_error!("[rrt-runtime] tunnel port_a_accept_error error={e}");
                tokio::time::sleep(Duration::from_millis(50)).await;
            }
        }
    }
}

async fn handle_client(stream: TcpStream, state: Arc<State>) -> Result<(), String> {
    let ws = tokio_tungstenite::accept_async(stream)
        .await
        .map_err(|e| format!("ws accept: {e}"))?;
    let (mut sink, mut rx_ws) = ws.split();
    let _active = super::activity::enter(); // Count the tunnel WS client connection as busy.
    let (tx, mut rx) = mpsc::unbounded_channel::<Message>();
    // This connection becomes the active client (a reconnect replaces the previous).
    *state.sdk_tx.lock().unwrap() = Some(tx);
    rrt_info!("[rrt-runtime] tunnel client connected");
    // Resend HTTP requests that were in flight when the previous client dropped.
    resend_pending_requests(&state);

    // Outbound pump: frames queued by Port B -> client WS.
    let out = tokio::spawn(async move {
        while let Some(m) = rx.recv().await {
            if sink.send(m).await.is_err() {
                break;
            }
        }
    });

    // Inbound: client frames -> dispatch.
    while let Some(msg) = rx_ws.next().await {
        match msg {
            Ok(Message::Text(t)) => match serde_json::from_str::<Frame>(&t) {
                Ok(frame) => dispatch_from_client(frame, &state),
                Err(e) => rrt_warn!("[rrt-runtime] tunnel drop_malformed_frame error={e}"),
            },
            Ok(Message::Close(_)) | Err(_) => break,
            _ => {}
        }
    }

    out.abort();
    // Notify any open WS channels of the disconnect (parity with python finally).
    let drained: Vec<_> = state.pending_ws.lock().unwrap().drain().collect();
    for (_, q) in drained {
        let _ = q.send(Frame::WsClose {
            id: String::new(),
            code: 1001,
            reason: "tunnel client disconnected".into(),
        });
    }
    rrt_info!("[rrt-runtime] tunnel client disconnected");
    Ok(())
}

/// Drop cached requests older than the TTL (and unblock their waiters).
fn cleanup_expired_requests(state: &Arc<State>) {
    let now = Instant::now();
    let expired: Vec<String> = {
        let mut pr = state.pending_requests.lock().unwrap();
        let ex: Vec<String> = pr
            .iter()
            .filter(|(_, (_, ts))| now.duration_since(*ts) > PENDING_REQUEST_TTL)
            .map(|(k, _)| k.clone())
            .collect();
        for k in &ex {
            pr.remove(k);
        }
        ex
    };
    // Dropping the oneshot sender unblocks the waiting HTTP handler (-> closes conn).
    let mut ph = state.pending_http.lock().unwrap();
    for k in &expired {
        ph.remove(k);
    }
}

/// On client (re)connect, resend any HTTP requests still in flight.
fn resend_pending_requests(state: &Arc<State>) {
    cleanup_expired_requests(state);
    let frames: Vec<Frame> = state
        .pending_requests
        .lock()
        .unwrap()
        .values()
        .map(|(f, _)| f.clone())
        .collect();
    if !frames.is_empty() {
        rrt_info!(
            "[rrt-runtime] tunnel resending_pending_requests count={}",
            frames.len()
        );
        for f in &frames {
            let _ = state.send_to_client(f);
        }
    }
}

fn dispatch_from_client(frame: Frame, state: &Arc<State>) {
    match &frame {
        Frame::Ping { id, timestamp } => {
            let _ = state.send_to_client(&Frame::Pong {
                id: id.clone(),
                timestamp: *timestamp,
            });
        }
        Frame::HttpResp { id, .. } => {
            if let Some(tx) = state.pending_http.lock().unwrap().remove(id) {
                let _ = tx.send(frame);
            }
        }
        Frame::Error { id, .. } => {
            // Deliver to whichever side is waiting on this id.
            let http = state.pending_http.lock().unwrap().remove(id);
            if let Some(tx) = http {
                let _ = tx.send(frame);
            } else if let Some(q) = state.pending_ws.lock().unwrap().get(id) {
                let _ = q.send(frame);
            }
        }
        Frame::WsConnected { id } | Frame::WsMessage { id, .. } | Frame::WsClose { id, .. } => {
            if let Some(q) = state.pending_ws.lock().unwrap().get(id) {
                let _ = q.send(frame);
            }
        }
        _ => {}
    }
}

// ───────────────────────── Port B: sandbox HTTP/WS ─────────────────────────
async fn accept_port_b(listener: TcpListener, state: Arc<State>) {
    loop {
        match listener.accept().await {
            Ok((stream, _)) => {
                let st = state.clone();
                tokio::spawn(async move {
                    let _ = handle_port_b(stream, st).await;
                });
            }
            Err(e) => {
                rrt_error!("[rrt-runtime] tunnel port_b_accept_error error={e}");
                tokio::time::sleep(Duration::from_millis(50)).await;
            }
        }
    }
}

async fn handle_port_b(stream: TcpStream, state: Arc<State>) -> Result<(), String> {
    // Peek (don't consume) to branch HTTP vs WS upgrade; tungstenite then does
    // the WS handshake itself on the un-consumed stream.
    let mut peek = [0u8; 8192];
    let n = stream.peek(&mut peek).await.map_err(|e| e.to_string())?;
    let head = String::from_utf8_lossy(&peek[..n]).to_lowercase();
    let is_ws = head.contains("upgrade: websocket");
    if is_ws {
        handle_port_b_ws(stream, state).await
    } else {
        handle_port_b_http(stream, state).await
    }
}

/// Read one HTTP/1.1 request (request line + headers + Content-Length body).
async fn read_http_request(
    stream: &mut TcpStream,
) -> Result<(String, String, HashMap<String, String>, Vec<u8>), String> {
    let mut buf = Vec::with_capacity(8192);
    let mut tmp = [0u8; 4096];
    let header_end = loop {
        if let Some(pos) = find_subslice(&buf, b"\r\n\r\n") {
            break pos;
        }
        let r = stream.read(&mut tmp).await.map_err(|e| e.to_string())?;
        if r == 0 {
            return Err("connection closed before headers".into());
        }
        buf.extend_from_slice(&tmp[..r]);
        if buf.len() > 1 << 20 {
            return Err("request headers too large".into());
        }
    };
    let head = String::from_utf8_lossy(&buf[..header_end]).to_string();
    let mut lines = head.split("\r\n");
    let req_line = lines.next().unwrap_or("");
    let mut parts = req_line.split_whitespace();
    let method = parts.next().unwrap_or("GET").to_string();
    let path = parts.next().unwrap_or("/").to_string();
    let mut headers = HashMap::new();
    for line in lines {
        if let Some((k, v)) = line.split_once(':') {
            headers.insert(k.trim().to_string(), v.trim().to_string());
        }
    }
    let clen: usize = headers
        .iter()
        .find(|(k, _)| k.eq_ignore_ascii_case("content-length"))
        .and_then(|(_, v)| v.parse().ok())
        .unwrap_or(0);
    let mut body = buf[header_end + 4..].to_vec();
    while body.len() < clen {
        let r = stream.read(&mut tmp).await.map_err(|e| e.to_string())?;
        if r == 0 {
            break;
        }
        body.extend_from_slice(&tmp[..r]);
    }
    if body.len() > clen {
        body.truncate(clen);
    }
    Ok((method, path, headers, body))
}

fn find_subslice(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    haystack.windows(needle.len()).position(|w| w == needle)
}

async fn handle_port_b_http(mut stream: TcpStream, state: Arc<State>) -> Result<(), String> {
    let (method, path, mut headers, body) = read_http_request(&mut stream).await?;
    headers.retain(|k, _| !k.eq_ignore_ascii_case("host"));
    let id = make_id();
    let frame = Frame::HttpReq {
        id: id.clone(),
        method,
        path,
        headers,
        body: b64().encode(&body),
    };
    let (tx, rx) = oneshot::channel::<Frame>();
    state.pending_http.lock().unwrap().insert(id.clone(), tx);
    // Cache for resend if the client drops and reconnects mid-request.
    state
        .pending_requests
        .lock()
        .unwrap()
        .insert(id.clone(), (frame.clone(), Instant::now()));
    // Best-effort send; if no client, we still wait (parity: tunnel may reconnect).
    let _ = state.send_to_client(&frame);

    let result = tokio::time::timeout(HTTP_TIMEOUT, rx).await;
    state.pending_http.lock().unwrap().remove(&id);
    state.pending_requests.lock().unwrap().remove(&id);

    match result {
        Ok(Ok(Frame::HttpResp {
            status,
            headers,
            body,
            ..
        })) => {
            let body_bytes = b64().decode(body.as_bytes()).unwrap_or_default();
            // Strip hop-by-hop / framing headers; we set Content-Length ourselves.
            let mut out = format!("HTTP/1.1 {} {}\r\n", status, reason_phrase(status));
            for (k, v) in &headers {
                let lk = k.to_ascii_lowercase();
                if lk == "content-length" || lk == "transfer-encoding" || lk == "connection" {
                    continue;
                }
                out.push_str(&format!("{k}: {v}\r\n"));
            }
            out.push_str(&format!("Content-Length: {}\r\n", body_bytes.len()));
            out.push_str("Connection: close\r\n\r\n");
            stream
                .write_all(out.as_bytes())
                .await
                .map_err(|e| e.to_string())?;
            stream
                .write_all(&body_bytes)
                .await
                .map_err(|e| e.to_string())?;
            let _ = stream.flush().await;
            Ok(())
        }
        Ok(Ok(Frame::Error { .. })) => {
            // Close TCP without a response so the caller sees a transport-level
            // error (matches connecting to an unreachable upstream).
            Ok(())
        }
        Ok(Ok(_)) | Ok(Err(_)) => Ok(()),
        Err(_) => {
            let msg = "Tunnel timeout";
            let resp = format!(
                "HTTP/1.1 504 Gateway Timeout\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                msg.len(),
                msg
            );
            let _ = stream.write_all(resp.as_bytes()).await;
            Ok(())
        }
    }
}

async fn handle_port_b_ws(stream: TcpStream, state: Arc<State>) -> Result<(), String> {
    // Capture the request path/headers via the tungstenite handshake callback.
    let captured: Arc<Mutex<(String, HashMap<String, String>)>> =
        Arc::new(Mutex::new((String::from("/"), HashMap::new())));
    let cap = captured.clone();
    let ws = tokio_tungstenite::accept_hdr_async(
        stream,
        |req: &tokio_tungstenite::tungstenite::handshake::server::Request,
         resp: tokio_tungstenite::tungstenite::handshake::server::Response| {
            let mut g = cap.lock().unwrap();
            g.0 = req
                .uri()
                .path_and_query()
                .map(|p| p.as_str().to_string())
                .unwrap_or_else(|| "/".into());
            for (k, v) in req.headers() {
                if !k.as_str().eq_ignore_ascii_case("host") {
                    g.1.insert(k.as_str().to_string(), v.to_str().unwrap_or("").to_string());
                }
            }
            Ok(resp)
        },
    )
    .await
    .map_err(|e| format!("port B ws accept: {e}"))?;
    let (path, headers) = {
        let g = captured.lock().unwrap();
        (g.0.clone(), g.1.clone())
    };

    let (mut sink, mut src) = ws.split();
    let id = make_id();
    let (q_tx, mut q_rx) = mpsc::unbounded_channel::<Frame>();
    state.pending_ws.lock().unwrap().insert(id.clone(), q_tx);

    if state
        .send_to_client(&Frame::WsConnect {
            id: id.clone(),
            path,
            headers,
        })
        .is_err()
    {
        state.pending_ws.lock().unwrap().remove(&id);
        return Ok(());
    }
    // Await ws_connected ack (10s).
    match tokio::time::timeout(WS_CONNECT_TIMEOUT, q_rx.recv()).await {
        Ok(Some(Frame::WsConnected { .. })) => {}
        _ => {
            state.pending_ws.lock().unwrap().remove(&id);
            return Ok(());
        }
    }

    // Bidirectional pump. Port-B-ws -> client (WsMessage); client queue -> Port-B-ws.
    loop {
        tokio::select! {
            biased;
            msg = src.next() => match msg {
                Some(Ok(Message::Text(t))) => {
                    let _ = state.send_to_client(&Frame::WsMessage { id: id.clone(), data: t, binary: false });
                }
                Some(Ok(Message::Binary(b))) => {
                    let _ = state.send_to_client(&Frame::WsMessage { id: id.clone(), data: b64().encode(&b), binary: true });
                }
                Some(Ok(Message::Close(_))) | Some(Err(_)) | None => {
                    let _ = state.send_to_client(&Frame::WsClose { id: id.clone(), code: 1000, reason: String::new() });
                    break;
                }
                _ => {}
            },
            f = q_rx.recv() => match f {
                Some(Frame::WsMessage { data, binary, .. }) => {
                    let out = if binary {
                        Message::Binary(b64().decode(data.as_bytes()).unwrap_or_default())
                    } else {
                        Message::Text(data)
                    };
                    if sink.send(out).await.is_err() { break; }
                }
                Some(Frame::WsClose { .. }) | Some(Frame::Error { .. }) | None => {
                    let _ = sink.send(Message::Close(None)).await;
                    break;
                }
                _ => {}
            },
        }
    }
    state.pending_ws.lock().unwrap().remove(&id);
    Ok(())
}

// ───────────────────────── E2E regression tests ─────────────────────────
// Drive the real server over localhost: a fake (Rust) TunnelClient on Port A
// and raw HTTP / a WS client on Port B, exercising the actual frame protocol
// the python TunnelClient also speaks.
#[cfg(test)]
mod tests {
    use super::*;
    use tokio_tungstenite::connect_async;

    async fn spawn_test_server() -> (u16, u16) {
        let porta = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let portb = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let wp = porta.local_addr().unwrap().port();
        let hp = portb.local_addr().unwrap().port();
        tokio::spawn(serve(porta, portb, Arc::new(State::default())));
        (wp, hp)
    }

    async fn connect_client(
        ws_port: u16,
    ) -> tokio_tungstenite::WebSocketStream<tokio_tungstenite::MaybeTlsStream<TcpStream>> {
        let (c, _) = connect_async(format!("ws://127.0.0.1:{ws_port}/"))
            .await
            .unwrap();
        // Let the server register this as the active client.
        tokio::time::sleep(Duration::from_millis(100)).await;
        c
    }

    async fn next_frame<S>(ws: &mut S) -> Frame
    where
        S: StreamExt<Item = Result<Message, tokio_tungstenite::tungstenite::Error>> + Unpin,
    {
        loop {
            match ws.next().await {
                Some(Ok(Message::Text(t))) => return serde_json::from_str(&t).unwrap(),
                Some(Ok(_)) => continue,
                other => panic!("expected text frame, got {other:?}"),
            }
        }
    }

    async fn http_get(port: u16, path: &str) -> String {
        let mut s = TcpStream::connect(("127.0.0.1", port)).await.unwrap();
        let req = format!("GET {path} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n");
        s.write_all(req.as_bytes()).await.unwrap();
        let mut buf = Vec::new();
        let _ = s.read_to_end(&mut buf).await;
        String::from_utf8_lossy(&buf).to_string()
    }

    #[test]
    fn frame_json_matches_python_protocol() {
        // body is base64; tagged by "type" — wire-compatible with tunnel_protocol.py.
        let f = Frame::HttpReq {
            id: "x".into(),
            method: "GET".into(),
            path: "/p".into(),
            headers: HashMap::new(),
            body: b64().encode(b"hi"),
        };
        let j: serde_json::Value =
            serde_json::from_str(&serde_json::to_string(&f).unwrap()).unwrap();
        assert_eq!(j["type"], "http_req");
        assert_eq!(j["id"], "x");
        assert_eq!(j["body"], "aGk="); // base64("hi")
                                       // parse a client http_resp frame
        let raw =
            r#"{"type":"http_resp","id":"x","status":201,"headers":{"X-A":"b"},"body":"cG9uZw=="}"#;
        match serde_json::from_str::<Frame>(raw).unwrap() {
            Frame::HttpResp { status, body, .. } => {
                assert_eq!(status, 201);
                assert_eq!(b64().decode(body.as_bytes()).unwrap(), b"pong");
            }
            o => panic!("{o:?}"),
        }
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn http_tunnel_roundtrip() {
        let (ws_port, http_port) = spawn_test_server().await;
        let mut client = connect_client(ws_port).await;
        let task = tokio::spawn(async move {
            let f = next_frame(&mut client).await;
            let id = match f {
                Frame::HttpReq {
                    id, path, method, ..
                } => {
                    assert_eq!(path, "/hello");
                    assert_eq!(method, "GET");
                    id
                }
                o => panic!("expected http_req, got {o:?}"),
            };
            client
                .send(
                    Frame::HttpResp {
                        id,
                        status: 200,
                        headers: HashMap::new(),
                        body: b64().encode(b"pong"),
                    }
                    .to_msg(),
                )
                .await
                .unwrap();
        });
        let resp = http_get(http_port, "/hello").await;
        assert!(resp.contains("200"), "resp={resp}");
        assert!(resp.ends_with("pong"), "resp={resp}");
        task.await.unwrap();
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn ping_gets_pong() {
        let (ws_port, _hp) = spawn_test_server().await;
        let mut client = connect_client(ws_port).await;
        client
            .send(
                Frame::Ping {
                    id: "p1".into(),
                    timestamp: 1.5,
                }
                .to_msg(),
            )
            .await
            .unwrap();
        match next_frame(&mut client).await {
            Frame::Pong { id, timestamp } => {
                assert_eq!(id, "p1");
                assert_eq!(timestamp, 1.5);
            }
            o => panic!("expected pong, got {o:?}"),
        }
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn http_error_closes_without_response() {
        let (ws_port, http_port) = spawn_test_server().await;
        let mut client = connect_client(ws_port).await;
        let task = tokio::spawn(async move {
            let id = match next_frame(&mut client).await {
                Frame::HttpReq { id, .. } => id,
                o => panic!("{o:?}"),
            };
            client
                .send(
                    Frame::Error {
                        id,
                        message: "upstream unreachable".into(),
                    }
                    .to_msg(),
                )
                .await
                .unwrap();
        });
        let resp = http_get(http_port, "/boom").await;
        // Error -> TCP closed with no HTTP response (transport-level failure).
        assert!(!resp.contains("HTTP/1.1 200"), "resp={resp}");
        task.await.unwrap();
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn ws_tunnel_roundtrip() {
        let (ws_port, http_port) = spawn_test_server().await;
        let mut client = connect_client(ws_port).await;
        let task = tokio::spawn(async move {
            // ws_connect -> ws_connected, then echo one ws_message.
            let id = match next_frame(&mut client).await {
                Frame::WsConnect { id, path, .. } => {
                    assert_eq!(path, "/chat");
                    id
                }
                o => panic!("expected ws_connect, got {o:?}"),
            };
            client
                .send(Frame::WsConnected { id: id.clone() }.to_msg())
                .await
                .unwrap();
            match next_frame(&mut client).await {
                Frame::WsMessage { data, binary, .. } => {
                    assert!(!binary);
                    assert_eq!(data, "hi");
                }
                o => panic!("expected ws_message, got {o:?}"),
            }
            client
                .send(
                    Frame::WsMessage {
                        id,
                        data: "hi-echo".into(),
                        binary: false,
                    }
                    .to_msg(),
                )
                .await
                .unwrap();
        });
        let (mut bws, _) = connect_async(format!("ws://127.0.0.1:{http_port}/chat"))
            .await
            .unwrap();
        bws.send(Message::Text("hi".into())).await.unwrap();
        match bws.next().await {
            Some(Ok(Message::Text(t))) => assert_eq!(t, "hi-echo"),
            o => panic!("expected echo, got {o:?}"),
        }
        task.await.unwrap();
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn reconnect_resends_pending_http() {
        let (ws_port, http_port) = spawn_test_server().await;
        // client1 connects, receives the request, then drops WITHOUT responding.
        let mut c1 = connect_client(ws_port).await;
        let http_task = tokio::spawn(async move { http_get(http_port, "/persist").await });
        match next_frame(&mut c1).await {
            Frame::HttpReq { path, .. } => assert_eq!(path, "/persist"),
            o => panic!("expected http_req, got {o:?}"),
        }
        drop(c1); // simulate tunnel client disconnect mid-request
        tokio::time::sleep(Duration::from_millis(150)).await;
        // client2 reconnects -> server must resend the still-pending request.
        let mut c2 = connect_client(ws_port).await;
        let id = match next_frame(&mut c2).await {
            Frame::HttpReq { id, path, .. } => {
                assert_eq!(path, "/persist");
                id
            }
            o => panic!("reconnect should resend http_req, got {o:?}"),
        };
        c2.send(
            Frame::HttpResp {
                id,
                status: 200,
                headers: HashMap::new(),
                body: b64().encode(b"resent-ok"),
            }
            .to_msg(),
        )
        .await
        .unwrap();
        let resp = http_task.await.unwrap();
        assert!(
            resp.contains("200") && resp.ends_with("resent-ok"),
            "resp={resp}"
        );
    }
}

fn reason_phrase(status: u16) -> &'static str {
    match status {
        200 => "OK",
        201 => "Created",
        204 => "No Content",
        301 => "Moved Permanently",
        302 => "Found",
        304 => "Not Modified",
        400 => "Bad Request",
        401 => "Unauthorized",
        403 => "Forbidden",
        404 => "Not Found",
        500 => "Internal Server Error",
        502 => "Bad Gateway",
        503 => "Service Unavailable",
        504 => "Gateway Timeout",
        _ => "OK",
    }
}
