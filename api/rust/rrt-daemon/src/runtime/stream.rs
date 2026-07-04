//! Native sandbox stream sessions for WebSocket data-plane operations.
//!
//! These methods keep file descriptors in the RRT process so frontend WS
//! frames no longer need to be translated into stateless file chunk actions.
//! The public method surface is intentionally small:
//! - sandbox_stream_open  {type:"file", path, mode:"read"|"write"}
//! - sandbox_stream_send  {stream_id, data:<msgpack bin|string>}
//! - sandbox_stream_recv  {stream_id, limit}
//! - sandbox_stream_close {stream_id}

use super::codec::{kw_str, map_value};
use rmpv::Value;
use std::collections::{BTreeMap, HashMap};
use std::fs::{File, OpenOptions};
use std::io::{Read, Write};
use std::path::Path;
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Mutex, OnceLock};

const DEFAULT_RECV_LIMIT: usize = 64 * 1024;
const MAX_RECV_LIMIT: usize = 4 * 1024 * 1024;

enum StreamEntry {
    FileRead {
        file: File,
        path: String,
    },
    FileWrite {
        file: File,
        path: String,
        offset: u64,
    },
    // Directory transfer over a single stream: the payload is a tar archive.
    // TarWrite pipes incoming bytes into `tar -x` (extract into path);
    // TarRead streams `tar -c` (archive of path) out chunk by chunk.
    TarWrite {
        child: Child,
        stdin: Option<ChildStdin>,
        path: String,
        offset: u64,
    },
    TarRead {
        child: Child,
        stdout: ChildStdout,
        path: String,
    },
}

fn streams() -> &'static Mutex<HashMap<String, StreamEntry>> {
    static STREAMS: OnceLock<Mutex<HashMap<String, StreamEntry>>> = OnceLock::new();
    STREAMS.get_or_init(|| Mutex::new(HashMap::new()))
}

fn next_stream_id() -> String {
    static NEXT: AtomicU64 = AtomicU64::new(1);
    format!("rrt-stream-{}", NEXT.fetch_add(1, Ordering::Relaxed))
}

fn nil() -> Value {
    Value::Nil
}

fn err(msg: impl Into<String>) -> Value {
    Value::from(msg.into())
}

fn kw_i64(kw: &BTreeMap<String, Value>, key: &str) -> Option<i64> {
    kw.get(key).and_then(|v| v.as_i64())
}

fn kw_bytes(kw: &BTreeMap<String, Value>, key: &str) -> Option<Vec<u8>> {
    kw.get(key).and_then(|v| match v {
        Value::Binary(bytes) => Some(bytes.clone()),
        Value::String(s) => s.as_str().map(|s| s.as_bytes().to_vec()),
        _ => None,
    })
}

pub fn sandbox_stream_open(kw: &BTreeMap<String, Value>) -> Value {
    let stream_type = kw_str(kw, "type").unwrap_or_else(|| "file".to_string());
    let path = kw_str(kw, "path").unwrap_or_default();
    let mode = kw_str(kw, "mode").unwrap_or_else(|| "read".to_string());
    if path.is_empty() {
        return map_value(vec![
            ("stream_id", Value::from("")),
            ("type", Value::from(stream_type)),
            ("mode", Value::from(mode)),
            ("path", Value::from(path)),
            ("error", err("path is required")),
        ]);
    }

    let is_read = matches!(mode.as_str(), "read" | "download");
    let is_write = matches!(mode.as_str(), "write" | "upload");
    if !is_read && !is_write {
        return map_value(vec![
            ("stream_id", Value::from("")),
            ("type", Value::from(stream_type)),
            ("mode", Value::from(mode)),
            ("path", Value::from(path)),
            ("error", err("mode must be read or write")),
        ]);
    }

    let open_result: std::io::Result<StreamEntry> = match stream_type.as_str() {
        "file" => {
            if is_read {
                OpenOptions::new()
                    .read(true)
                    .open(&path)
                    .map(|file| StreamEntry::FileRead {
                        file,
                        path: path.clone(),
                    })
            } else {
                if let Some(parent) = Path::new(&path).parent() {
                    let _ = std::fs::create_dir_all(parent);
                }
                OpenOptions::new()
                    .create(true)
                    .write(true)
                    .truncate(true)
                    .open(&path)
                    .map(|file| StreamEntry::FileWrite {
                        file,
                        path: path.clone(),
                        offset: 0,
                    })
            }
        }
        // Directory transfer: the byte stream is a tar archive. The sandbox
        // image provides `tar`; shelling out avoids a Rust archive crate in the
        // static musl build. read = `tar -c` archive of path; write = `tar -x`
        // extract into path.
        "tar" => {
            if is_read {
                Command::new("tar")
                    .args(["-c", "-f", "-", "-C", &path, "."])
                    .stdin(Stdio::null())
                    .stdout(Stdio::piped())
                    .stderr(Stdio::null())
                    .spawn()
                    .and_then(|mut child| match child.stdout.take() {
                        Some(stdout) => Ok(StreamEntry::TarRead {
                            child,
                            stdout,
                            path: path.clone(),
                        }),
                        None => Err(std::io::Error::new(
                            std::io::ErrorKind::Other,
                            "tar stdout unavailable",
                        )),
                    })
            } else {
                let _ = std::fs::create_dir_all(&path);
                Command::new("tar")
                    .args(["-x", "-f", "-", "-C", &path])
                    .stdin(Stdio::piped())
                    .stdout(Stdio::null())
                    .stderr(Stdio::null())
                    .spawn()
                    .and_then(|mut child| match child.stdin.take() {
                        Some(stdin) => Ok(StreamEntry::TarWrite {
                            child,
                            stdin: Some(stdin),
                            path: path.clone(),
                            offset: 0,
                        }),
                        None => Err(std::io::Error::new(
                            std::io::ErrorKind::Other,
                            "tar stdin unavailable",
                        )),
                    })
            }
        }
        _ => {
            return map_value(vec![
                ("stream_id", Value::from("")),
                ("type", Value::from(stream_type)),
                ("mode", Value::from(mode)),
                ("path", Value::from(path)),
                ("error", err("type must be file or tar")),
            ]);
        }
    };

    match open_result {
        Ok(entry) => {
            let stream_id = next_stream_id();
            streams().lock().unwrap().insert(stream_id.clone(), entry);
            map_value(vec![
                ("stream_id", Value::from(stream_id)),
                ("type", Value::from(stream_type)),
                ("mode", Value::from(mode)),
                ("path", Value::from(path)),
                ("error", nil()),
            ])
        }
        Err(e) => map_value(vec![
            ("stream_id", Value::from("")),
            ("type", Value::from(stream_type)),
            ("mode", Value::from(mode)),
            ("path", Value::from(path)),
            ("error", err(e.to_string())),
        ]),
    }
}

pub fn sandbox_stream_send(kw: &BTreeMap<String, Value>) -> Value {
    let stream_id = kw_str(kw, "stream_id").unwrap_or_default();
    let data = match kw_bytes(kw, "data") {
        Some(data) => data,
        None => {
            return map_value(vec![
                ("stream_id", Value::from(stream_id)),
                ("bytes_written", Value::from(0i64)),
                ("offset", Value::from(0i64)),
                ("error", err("data is required")),
            ]);
        }
    };

    let mut guard = streams().lock().unwrap();
    match guard.get_mut(&stream_id) {
        Some(StreamEntry::FileWrite {
            file,
            path: _,
            offset,
        }) => match file.write_all(&data) {
            Ok(_) => {
                *offset += data.len() as u64;
                map_value(vec![
                    ("stream_id", Value::from(stream_id)),
                    ("bytes_written", Value::from(data.len() as i64)),
                    ("offset", Value::from(*offset as i64)),
                    ("error", nil()),
                ])
            }
            Err(e) => map_value(vec![
                ("stream_id", Value::from(stream_id)),
                ("bytes_written", Value::from(0i64)),
                ("offset", Value::from(*offset as i64)),
                ("error", err(e.to_string())),
            ]),
        },
        Some(StreamEntry::TarWrite { stdin, offset, .. }) => match stdin.as_mut() {
            Some(w) => match w.write_all(&data) {
                Ok(_) => {
                    *offset += data.len() as u64;
                    map_value(vec![
                        ("stream_id", Value::from(stream_id)),
                        ("bytes_written", Value::from(data.len() as i64)),
                        ("offset", Value::from(*offset as i64)),
                        ("error", nil()),
                    ])
                }
                Err(e) => map_value(vec![
                    ("stream_id", Value::from(stream_id)),
                    ("bytes_written", Value::from(0i64)),
                    ("offset", Value::from(*offset as i64)),
                    ("error", err(e.to_string())),
                ]),
            },
            None => map_value(vec![
                ("stream_id", Value::from(stream_id)),
                ("bytes_written", Value::from(0i64)),
                ("offset", Value::from(*offset as i64)),
                ("error", err("tar stream stdin already closed")),
            ]),
        },
        Some(StreamEntry::FileRead { .. }) | Some(StreamEntry::TarRead { .. }) => map_value(vec![
            ("stream_id", Value::from(stream_id)),
            ("bytes_written", Value::from(0i64)),
            ("offset", Value::from(0i64)),
            ("error", err("stream is not writable")),
        ]),
        None => map_value(vec![
            ("stream_id", Value::from(stream_id)),
            ("bytes_written", Value::from(0i64)),
            ("offset", Value::from(0i64)),
            ("error", err("unknown stream_id")),
        ]),
    }
}

pub fn sandbox_stream_recv(kw: &BTreeMap<String, Value>) -> Value {
    let stream_id = kw_str(kw, "stream_id").unwrap_or_default();
    let limit = kw_i64(kw, "limit")
        .unwrap_or(DEFAULT_RECV_LIMIT as i64)
        .clamp(1, MAX_RECV_LIMIT as i64) as usize;

    let mut guard = streams().lock().unwrap();
    match guard.get_mut(&stream_id) {
        Some(StreamEntry::FileRead { file, path: _ }) => {
            let mut buf = vec![0u8; limit];
            match file.read(&mut buf) {
                Ok(n) => {
                    buf.truncate(n);
                    map_value(vec![
                        ("stream_id", Value::from(stream_id)),
                        ("data", Value::Binary(buf)),
                        ("bytes_read", Value::from(n as i64)),
                        ("eof", Value::Boolean(n == 0)),
                        ("error", nil()),
                    ])
                }
                Err(e) => map_value(vec![
                    ("stream_id", Value::from(stream_id)),
                    ("data", Value::Binary(Vec::new())),
                    ("bytes_read", Value::from(0i64)),
                    ("eof", Value::Boolean(true)),
                    ("error", err(e.to_string())),
                ]),
            }
        }
        Some(StreamEntry::TarRead { stdout, .. }) => {
            let mut buf = vec![0u8; limit];
            match stdout.read(&mut buf) {
                Ok(n) => {
                    buf.truncate(n);
                    map_value(vec![
                        ("stream_id", Value::from(stream_id)),
                        ("data", Value::Binary(buf)),
                        ("bytes_read", Value::from(n as i64)),
                        ("eof", Value::Boolean(n == 0)),
                        ("error", nil()),
                    ])
                }
                Err(e) => map_value(vec![
                    ("stream_id", Value::from(stream_id)),
                    ("data", Value::Binary(Vec::new())),
                    ("bytes_read", Value::from(0i64)),
                    ("eof", Value::Boolean(true)),
                    ("error", err(e.to_string())),
                ]),
            }
        }
        Some(StreamEntry::FileWrite { .. }) | Some(StreamEntry::TarWrite { .. }) => {
            map_value(vec![
                ("stream_id", Value::from(stream_id)),
                ("data", Value::Binary(Vec::new())),
                ("bytes_read", Value::from(0i64)),
                ("eof", Value::Boolean(true)),
                ("error", err("stream is not readable")),
            ])
        }
        None => map_value(vec![
            ("stream_id", Value::from(stream_id)),
            ("data", Value::Binary(Vec::new())),
            ("bytes_read", Value::from(0i64)),
            ("eof", Value::Boolean(true)),
            ("error", err("unknown stream_id")),
        ]),
    }
}

pub fn sandbox_stream_close(kw: &BTreeMap<String, Value>) -> Value {
    let stream_id = kw_str(kw, "stream_id").unwrap_or_default();
    let removed = streams().lock().unwrap().remove(&stream_id);
    match removed {
        Some(StreamEntry::FileRead { path, .. }) | Some(StreamEntry::FileWrite { path, .. }) => {
            map_value(vec![
                ("stream_id", Value::from(stream_id)),
                ("path", Value::from(path)),
                ("error", nil()),
            ])
        }
        Some(StreamEntry::TarWrite {
            mut child,
            stdin,
            path,
            ..
        }) => {
            // Close tar's stdin so it sees EOF and flushes the extraction,
            // then surface a non-zero exit as an error.
            drop(stdin);
            let status = child.wait();
            let error = match status {
                Ok(s) if s.success() => nil(),
                Ok(s) => err(format!("tar extract failed: {}", s)),
                Err(e) => err(e.to_string()),
            };
            map_value(vec![
                ("stream_id", Value::from(stream_id)),
                ("path", Value::from(path)),
                ("error", error),
            ])
        }
        Some(StreamEntry::TarRead {
            mut child, path, ..
        }) => {
            let _ = child.wait();
            map_value(vec![
                ("stream_id", Value::from(stream_id)),
                ("path", Value::from(path)),
                ("error", nil()),
            ])
        }
        None => map_value(vec![
            ("stream_id", Value::from(stream_id)),
            ("error", err("unknown stream_id")),
        ]),
    }
}
