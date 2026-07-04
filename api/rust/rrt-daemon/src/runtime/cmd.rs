//! Rust implementation of akernel `cmd_start/cmd_poll/cmd_wait/cmd_kill/cmd_list/cmd_send_stdin`.
//! Semantics match `akernel_sdk/instance.py`, including response dict fields, error messages, and DEVNULL default stdin.
//!
//! Process-table design: the whole Child is moved to a waiter thread that owns wait(); kill sends signals directly to the OS pid,
//! avoiding wait/kill contention over the same &mut Child in Rust. Exit codes are broadcast through (Mutex<Option<i32>>, Condvar),
//! and cmd_poll/cmd_wait wait on the Condvar with timeouts, matching Python's background waiter thread plus Event.

use super::codec::{kw_str, map_value};
use rmpv::Value;
use std::collections::{BTreeMap, HashMap};
use std::io::{Read, Write};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Condvar, Mutex, OnceLock};
use std::time::{Duration, Instant};

struct ExitState {
    code: Mutex<Option<i64>>,
    cond: Condvar,
}

struct Reader {
    buf: Arc<Mutex<Vec<u8>>>,
    finished: Arc<AtomicBool>,
}

struct ProcEntry {
    cmd: String,
    stdin: Option<std::process::ChildStdin>,
    stdout: Reader,
    stderr: Reader,
    exit: Arc<ExitState>,
}

fn procs() -> &'static Mutex<HashMap<i64, ProcEntry>> {
    static P: OnceLock<Mutex<HashMap<i64, ProcEntry>>> = OnceLock::new();
    P.get_or_init(|| Mutex::new(HashMap::new()))
}

fn spawn_reader(stream: Option<impl Read + Send + 'static>) -> Reader {
    let buf = Arc::new(Mutex::new(Vec::new()));
    let finished = Arc::new(AtomicBool::new(false));
    if let Some(mut s) = stream {
        let buf2 = buf.clone();
        let fin2 = finished.clone();
        std::thread::spawn(move || {
            let mut chunk = [0u8; 4096];
            loop {
                match s.read(&mut chunk) {
                    Ok(0) | Err(_) => break,
                    Ok(n) => buf2.lock().unwrap().extend_from_slice(&chunk[..n]),
                }
            }
            fin2.store(true, Ordering::SeqCst);
        });
    } else {
        finished.store(true, Ordering::SeqCst);
    }
    Reader { buf, finished }
}

fn kw_i64(kw: &BTreeMap<String, Value>, key: &str) -> Option<i64> {
    kw.get(key).and_then(|v| v.as_i64())
}

fn kw_bool(kw: &BTreeMap<String, Value>, key: &str) -> Option<bool> {
    kw.get(key).and_then(|v| v.as_bool())
}

/// wait_timeout may be int or float because client poll intervals include jitter.
fn kw_f64(kw: &BTreeMap<String, Value>, key: &str) -> Option<f64> {
    kw.get(key)
        .and_then(|v| v.as_f64().or_else(|| v.as_i64().map(|i| i as f64)))
}

fn nil() -> Value {
    Value::Nil
}

/// Wait for an exit code up to timeout; None means infinite. Returns Some(code) or None on timeout.
fn wait_exit(exit: &ExitState, timeout: Option<Duration>) -> Option<i64> {
    let guard = exit.code.lock().unwrap();
    match timeout {
        None => {
            let mut g = guard;
            while g.is_none() {
                g = exit.cond.wait(g).unwrap();
            }
            *g
        }
        Some(d) => {
            let deadline = Instant::now() + d;
            let mut g = guard;
            while g.is_none() {
                let now = Instant::now();
                if now >= deadline {
                    return None;
                }
                let (ng, _) = exit.cond.wait_timeout(g, deadline - now).unwrap();
                g = ng;
            }
            *g
        }
    }
}

/// Match Python `_collect_proc_output`: wait for readers to drain for up to 5s and decode lossily.
fn collect_output(entry: &ProcEntry) -> (String, String) {
    let deadline = Instant::now() + Duration::from_secs(5);
    while Instant::now() < deadline {
        if entry.stdout.finished.load(Ordering::SeqCst)
            && entry.stderr.finished.load(Ordering::SeqCst)
        {
            break;
        }
        std::thread::sleep(Duration::from_millis(20));
    }
    let out = String::from_utf8_lossy(&entry.stdout.buf.lock().unwrap()).into_owned();
    let err = String::from_utf8_lossy(&entry.stderr.buf.lock().unwrap()).into_owned();
    (out, err)
}

/// cmd_start(cmd, envs, cwd, want_stdin) → {pid, error}。
pub fn cmd_start(kw: &BTreeMap<String, Value>) -> Value {
    let cmd = kw_str(kw, "cmd").unwrap_or_default();
    let cwd = kw_str(kw, "cwd");
    let want_stdin = kw_bool(kw, "want_stdin").unwrap_or(false);

    let mut c = Command::new("/bin/sh");
    c.arg("-c").arg(&cmd);
    c.stdout(Stdio::piped()).stderr(Stdio::piped());
    // Default stdin uses /dev/null: a PIPE without a writer never reaches EOF, matching the Python behavior.
    c.stdin(if want_stdin {
        Stdio::piped()
    } else {
        Stdio::null()
    });
    if let Some(d) = &cwd {
        if !d.is_empty() {
            c.current_dir(d);
        }
    }
    if let Some(Value::Map(kvs)) = kw.get("envs") {
        for (k, v) in kvs {
            if let (Some(k), Some(v)) = (k.as_str(), v.as_str()) {
                c.env(k, v);
            }
        }
    }

    let mut child = match c.spawn() {
        Ok(ch) => ch,
        Err(e) => {
            return map_value(vec![
                ("pid", Value::from(-1i64)),
                ("error", Value::from(e.to_string())),
            ])
        }
    };
    let pid = child.id() as i64;
    let stdin = child.stdin.take();
    let stdout = spawn_reader(child.stdout.take());
    let stderr = spawn_reader(child.stderr.take());

    let exit = Arc::new(ExitState {
        code: Mutex::new(None),
        cond: Condvar::new(),
    });
    let exit2 = exit.clone();
    // Move the whole Child to the waiter thread: it owns wait(), and exit codes are broadcast through the Condvar.
    std::thread::spawn(move || {
        let code = child.wait().ok().and_then(|s| s.code()).unwrap_or(-1) as i64;
        *exit2.code.lock().unwrap() = Some(code);
        exit2.cond.notify_all();
    });

    procs().lock().unwrap().insert(
        pid,
        ProcEntry {
            cmd,
            stdin,
            stdout,
            stderr,
            exit,
        },
    );
    map_value(vec![("pid", Value::from(pid)), ("error", nil())])
}

/// cmd_wait(pid, timeout) → {stdout, stderr, exit_code}。
pub fn cmd_wait(kw: &BTreeMap<String, Value>) -> Value {
    let pid = kw_i64(kw, "pid").unwrap_or(-1);
    let timeout = kw_f64(kw, "timeout").map(Duration::from_secs_f64);
    let exit = {
        let p = procs().lock().unwrap();
        match p.get(&pid) {
            Some(e) => e.exit.clone(),
            None => {
                return map_value(vec![
                    ("stdout", Value::from("")),
                    ("stderr", Value::from(format!("No process with pid {pid}"))),
                    ("exit_code", Value::from(-1i64)),
                ])
            }
        }
    };
    match wait_exit(&exit, timeout) {
        Some(code) => {
            let p = procs().lock().unwrap();
            let entry = p.get(&pid).expect("entry exists");
            let (out, err) = collect_output(entry);
            map_value(vec![
                ("stdout", Value::from(out)),
                ("stderr", Value::from(err)),
                ("exit_code", Value::from(code)),
            ])
        }
        None => map_value(vec![
            ("stdout", Value::from("")),
            (
                "stderr",
                Value::from(format!("process {pid} wait timed out")),
            ),
            ("exit_code", Value::from(-1i64)),
        ]),
    }
}

/// cmd_poll(pid, wait_timeout=10) → {status: done|running|error, ...}。
pub fn cmd_poll(kw: &BTreeMap<String, Value>) -> Value {
    let pid = kw_i64(kw, "pid").unwrap_or(-1);
    let wait_timeout = kw_f64(kw, "wait_timeout").unwrap_or(10.0);
    let exit = {
        let p = procs().lock().unwrap();
        match p.get(&pid) {
            Some(e) => e.exit.clone(),
            None => {
                return map_value(vec![
                    ("status", Value::from("error")),
                    ("error", Value::from(format!("No process with pid {pid}"))),
                ])
            }
        }
    };
    match wait_exit(&exit, Some(Duration::from_secs_f64(wait_timeout.max(0.0)))) {
        Some(code) => {
            let p = procs().lock().unwrap();
            let entry = p.get(&pid).expect("entry exists");
            let (out, err) = collect_output(entry);
            map_value(vec![
                ("status", Value::from("done")),
                ("stdout", Value::from(out)),
                ("stderr", Value::from(err)),
                ("exit_code", Value::from(code)),
            ])
        }
        None => map_value(vec![("status", Value::from("running"))]),
    }
}

/// cmd_list() → {processes: [{pid, cmd, running}]}。
pub fn cmd_list(_kw: &BTreeMap<String, Value>) -> Value {
    let p = procs().lock().unwrap();
    let processes: Vec<Value> = p
        .iter()
        .map(|(pid, e)| {
            map_value(vec![
                ("pid", Value::from(*pid)),
                ("cmd", Value::from(e.cmd.clone())),
                (
                    "running",
                    Value::from(e.exit.code.lock().unwrap().is_none()),
                ),
            ])
        })
        .collect();
    map_value(vec![("processes", Value::Array(processes))])
}

/// cmd_kill(pid) → {killed, error}。
pub fn cmd_kill(kw: &BTreeMap<String, Value>) -> Value {
    let pid = kw_i64(kw, "pid").unwrap_or(-1);
    {
        let p = procs().lock().unwrap();
        if !p.contains_key(&pid) {
            return map_value(vec![
                ("killed", Value::from(false)),
                ("error", Value::from(format!("No process with pid {pid}"))),
            ]);
        }
    }
    // Child lives in the waiter thread, so send SIGKILL directly to the OS pid; the waiter's wait() then returns.
    let r = unsafe { libc::kill(pid as libc::pid_t, libc::SIGKILL) };
    if r == 0 {
        map_value(vec![("killed", Value::from(true)), ("error", nil())])
    } else {
        let e = std::io::Error::last_os_error();
        map_value(vec![
            ("killed", Value::from(false)),
            ("error", Value::from(e.to_string())),
        ])
    }
}

/// cmd_send_stdin(pid, data, eof=False) → {error}。
pub fn cmd_send_stdin(kw: &BTreeMap<String, Value>) -> Value {
    let pid = kw_i64(kw, "pid").unwrap_or(-1);
    let data = kw_str(kw, "data").unwrap_or_default();
    let eof = kw_bool(kw, "eof").unwrap_or(false);
    let mut p = procs().lock().unwrap();
    let entry = match p.get_mut(&pid) {
        Some(e) => e,
        None => {
            return map_value(vec![(
                "error",
                Value::from(format!("No process with pid {pid}")),
            )])
        }
    };
    match entry.stdin.as_mut() {
        None => map_value(vec![(
            "error",
            Value::from(format!(
                "process {pid} was not started with stdin enabled; start it with stdin=True to use send_stdin"
            )),
        )]),
        Some(stdin) => {
            if !data.is_empty() {
                if let Err(e) = stdin.write_all(data.as_bytes()).and_then(|_| stdin.flush()) {
                    return map_value(vec![("error", Value::from(e.to_string()))]);
                }
            }
            if eof {
                entry.stdin = None; // Dropping closes the write end, so the child reads EOF.
            }
            map_value(vec![("error", nil())])
        }
    }
}
