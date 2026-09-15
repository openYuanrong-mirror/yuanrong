// Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
// Licensed under the Apache License, Version 2.0.
// See the LICENSE file in this repository for the complete license text.

//! Local busy/idle tracking for the HTTP atomic-operation server, tunnel WS,
//! and RuntimeRPC call handling. Activity follows requests and connections;
//! background processes are managed independently by the process table.
//! Traffic activity reports via `KillRequest(signal=23)`: busy is reasserted
//! when work restarts and on direct/tunnel lease renewals, while idle is
//! debounced after the final `1 -> 0` transition. Function-proxy reuses IdleMgr
//! to start or stop the idle timer. Periodic snapshots repair dropped reports.

use std::sync::atomic::{AtomicI64, AtomicU64, Ordering};
use std::sync::{Mutex, OnceLock, RwLock};
use std::time::Instant;

use tokio::runtime::Handle;
use tokio::sync::mpsc;

use crate::posix::runtime_rpc::StreamingMessage;

static ACTIVE: AtomicI64 = AtomicI64::new(0);
static IDLE_EPOCH: AtomicU64 = AtomicU64::new(0);
static REPORTER: OnceLock<ActivityReporter> = OnceLock::new();
const IDLE_REPORT_DEBOUNCE: std::time::Duration = std::time::Duration::from_millis(800);
const ACTIVITY_REPORT_INTERVAL: std::time::Duration = std::time::Duration::from_secs(10);
// Serialize count transitions and report enqueueing so a snapshot cannot
// enqueue stale idle after a newer busy report. The timestamp preserves the
// idle debounce for periodic snapshots as well as edge-triggered reports.
static IDLE_SINCE: Mutex<Option<Instant>> = Mutex::new(None);

struct ActivityReporter {
    instance_id: RwLock<String>,
    tx: mpsc::Sender<StreamingMessage>,
    runtime: Handle,
}

impl ActivityReporter {
    fn new(instance_id: String, tx: mpsc::Sender<StreamingMessage>, runtime: Handle) -> Self {
        Self {
            instance_id: RwLock::new(instance_id),
            tx,
            runtime,
        }
    }

    fn rebind_instance_id(&self, instance_id: &str) {
        *self
            .instance_id
            .write()
            .unwrap_or_else(std::sync::PoisonError::into_inner) = instance_id.to_string();
    }

    fn instance_id(&self) -> String {
        self.instance_id
            .read()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .clone()
    }
}

/// Initialize the activity counter. This is a reserved init hook; the global counter naturally maintains the initial value.
pub fn init() {}

/// Initialize the activity reporter before starting HTTP/tunnel servers so the first direct request can report busy.
pub fn init_reporter(instance_id: String, tx: mpsc::Sender<StreamingMessage>) {
    init_reporter_with_interval(instance_id, tx, ACTIVITY_REPORT_INTERVAL);
}

fn init_reporter_with_interval(
    instance_id: String,
    tx: mpsc::Sender<StreamingMessage>,
    interval: std::time::Duration,
) {
    // Initialization runs on the runtime before any activity-producing server
    // starts. Keep this handle for guards dropped outside Tokio worker threads.
    let runtime = Handle::current();
    if REPORTER
        .set(ActivityReporter::new(instance_id, tx, runtime.clone()))
        .is_ok()
    {
        runtime.spawn(report_periodically(interval));
    }
}

async fn report_periodically(interval: std::time::Duration) {
    let reporter = REPORTER.get().expect("activity reporter initialized");
    loop {
        tokio::select! {
            _ = reporter.tx.closed() => return,
            _ = tokio::time::sleep(interval) => report_current_activity(),
        }
    }
}

fn report_current_activity() {
    let idle_since = IDLE_SINCE
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    let busy = active_count() > 0;
    if !busy && idle_since.is_some_and(|since| since.elapsed() < IDLE_REPORT_DEBOUNCE) {
        return;
    }
    report_state_transition(busy, "periodic");
}

/// Adopt the target logical identity after the restore environment has been
/// validated. Direct HTTP/tunnel activity survives checkpoint/restore, so its
/// reports must follow the same identity as the reconnected RuntimeRPC stream.
pub fn rebind_reporter_instance_id(instance_id: &str) {
    if let Some(reporter) = REPORTER.get() {
        reporter.rebind_instance_id(instance_id);
    }
}

/// RAII guard: increments activity on creation and decrements on drop, including connection/call end and panic unwinding.
#[must_use]
pub struct ActiveGuard {
    source: ActivitySource,
}

/// Identifies which runtime surface produced an activity report.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum ActivitySource {
    Checkpoint,
    DirectHttp,
    RuntimeRpc,
    Tunnel,
}

impl ActivitySource {
    pub(crate) const fn as_str(self) -> &'static str {
        match self {
            Self::Checkpoint => "checkpoint",
            Self::DirectHttp => "direct-http",
            Self::RuntimeRpc => "runtime-rpc",
            Self::Tunnel => "tunnel",
        }
    }

    const fn reasserts_busy(self) -> bool {
        matches!(self, Self::DirectHttp | Self::Tunnel)
    }
}

/// Mark a connection/call active and return a guard; dropping the guard ends the activity.
pub(crate) fn enter(source: ActivitySource) -> ActiveGuard {
    let mut idle_since = IDLE_SINCE
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    let previous = ACTIVE.fetch_add(1, Ordering::SeqCst);
    let crossed_from_idle = state_transition(previous, true).is_some();
    if crossed_from_idle {
        *idle_since = None;
        // A new activity invalidates any pending debounced idle report. Always
        // reassert busy after crossing from zero: the proxy may have armed its
        // timer through another traffic source since the previous report.
        IDLE_EPOCH.fetch_add(1, Ordering::SeqCst);
    }

    // Direct requests are lease renewals, and a tunnel connection is a
    // long-lived activity owner. Reassert both even when another request is
    // active so polling and overlapping init/tunnel startup cannot leave the
    // proxy with an armed idle timer.
    if crossed_from_idle || source.reasserts_busy() {
        report_state_transition(true, source.as_str());
    }
    ActiveGuard { source }
}

impl Drop for ActiveGuard {
    fn drop(&mut self) {
        let mut idle_since = IDLE_SINCE
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let previous = ACTIVE.fetch_sub(1, Ordering::SeqCst);
        if state_transition(previous, false).is_some() {
            *idle_since = Some(Instant::now());
            schedule_idle_report(self.source);
        }
    }
}

fn schedule_idle_report(source: ActivitySource) {
    let epoch = IDLE_EPOCH.fetch_add(1, Ordering::SeqCst) + 1;
    let idle_task = async move {
        tokio::time::sleep(IDLE_REPORT_DEBOUNCE).await;
        let _idle_since = IDLE_SINCE
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let current_epoch = IDLE_EPOCH.load(Ordering::SeqCst);
        let idle_count = active_count();
        if current_epoch != epoch || idle_count != 0 {
            rrt_info!(
                "[rrt-runtime] activity idle report cancelled source={} scheduled_epoch={} current_epoch={} active_count={}",
                source.as_str(),
                epoch,
                current_epoch,
                idle_count
            );
            return;
        }
        report_state_transition(false, source.as_str());
    };
    if let Some(reporter) = REPORTER.get() {
        reporter.runtime.spawn(idle_task);
    }
}

fn report_state_transition(busy: bool, source: &str) {
    let Some(reporter) = REPORTER.get() else {
        return;
    };
    let instance_id = reporter.instance_id();
    let state = if busy { "busy" } else { "idle" };
    let msg = super::activity_report_msg(&instance_id, state.as_bytes().to_vec());
    match reporter.tx.try_send(msg) {
        Ok(()) => {
            rrt_info!(
                "[rrt-runtime] activity state={} source={} report_signal={} instance={} active_count={}",
                state,
                source,
                super::IDLE_REPORT_SIGNAL,
                instance_id,
                active_count()
            );
        }
        Err(e) => {
            rrt_error!(
                "[rrt-runtime] activity report failed state={} source={} instance={} error={}",
                state,
                source,
                instance_id,
                e
            );
        }
    }
}

/// Current activity state text. Used to resynchronize state with function-proxy after MessageStream reconnects.
pub fn current_state() -> &'static str {
    if active_count() > 0 {
        "busy"
    } else {
        "idle"
    }
}

/// Current number of active connections, calls, and checkpoint operations.
pub fn active_count() -> i64 {
    ACTIVE.load(Ordering::SeqCst)
}

/// Wait until in-flight RuntimeRPC/HTTP/tunnel requests and checkpoint
/// operations finish. Background processes are managed by sandbox shutdown.
pub async fn wait_until_idle(timeout: std::time::Duration) -> bool {
    let deadline = tokio::time::Instant::now() + timeout;
    loop {
        if active_count() <= 0 {
            return true;
        }
        if tokio::time::Instant::now() >= deadline {
            return false;
        }
        tokio::time::sleep(std::time::Duration::from_millis(50)).await;
    }
}

/// Report only when the global active counter crosses the zero boundary.
fn state_transition(previous: i64, entering: bool) -> Option<&'static str> {
    match (previous, entering) {
        (0, true) => Some("busy"),
        (1, false) => Some("idle"),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::process::Command;
    use tokio::sync::mpsc::error::TryRecvError;

    fn run_in_isolated_process(env_name: &str, test_name: &str) -> bool {
        if std::env::var_os(env_name).is_some() {
            return true;
        }
        let status = Command::new(std::env::current_exe().expect("current test executable"))
            .arg(test_name)
            .arg("--exact")
            .arg("--test-threads=1")
            .env(env_name, "1")
            .status()
            .expect("run isolated activity test");
        assert!(status.success(), "isolated activity test failed");
        false
    }

    async fn recv_report(rx: &mut mpsc::Receiver<StreamingMessage>, expected_state: &str) {
        let msg = tokio::time::timeout(std::time::Duration::from_secs(2), rx.recv())
            .await
            .expect("activity report timed out")
            .expect("activity reporter closed");
        let Some(crate::posix::runtime_rpc::streaming_message::Body::KillReq(kill)) = msg.body
        else {
            panic!("expected activity KillReq");
        };
        assert_eq!(kill.payload, expected_state.as_bytes());
    }

    #[test]
    fn state_transition_only_on_zero_boundary() {
        assert_eq!(state_transition(0, true), Some("busy"));
        assert_eq!(state_transition(1, true), None);
        assert_eq!(state_transition(2, false), None);
        assert_eq!(state_transition(1, false), Some("idle"));
        assert_eq!(state_transition(0, false), None);
    }

    #[test]
    fn guard_increments_then_decrements() {
        let base = active_count();
        {
            let _g = enter(ActivitySource::DirectHttp);
            assert_eq!(active_count(), base + 1);
        }
        assert_eq!(active_count(), base);
    }

    #[tokio::test]
    async fn reporter_uses_rebound_target_logical_identity() {
        let (tx, _rx) = mpsc::channel(1);
        let reporter = ActivityReporter::new("source-sandbox".to_string(), tx, Handle::current());

        reporter.rebind_instance_id("clone-sandbox");

        assert_eq!(reporter.instance_id(), "clone-sandbox");
    }

    #[tokio::test]
    async fn background_process_allows_idle_and_shutdown() {
        const ENV: &str = "YR_RRT_BACKGROUND_IDLE_DRAIN_ISOLATED";
        const TEST: &str = "runtime::activity::tests::background_process_allows_idle_and_shutdown";
        if !run_in_isolated_process(ENV, TEST) {
            return;
        }

        let (tx, mut rx) = mpsc::channel(8);
        init_reporter("sandbox-under-test".to_string(), tx);
        let request = enter(ActivitySource::RuntimeRpc);
        recv_report(&mut rx, "busy").await;
        let args = std::collections::BTreeMap::from([
            ("cmd".to_string(), rmpv::Value::from("cat")),
            ("want_stdin".to_string(), rmpv::Value::from(true)),
        ]);
        let started = super::super::cmd::cmd_start(&args);
        let pid = started
            .as_map()
            .unwrap()
            .iter()
            .find_map(|(key, value)| {
                (key.as_str() == Some("pid"))
                    .then(|| value.as_i64())
                    .flatten()
            })
            .expect("started process pid");
        assert!(pid > 0);
        drop(request);
        assert_eq!(current_state(), "idle");
        recv_report(&mut rx, "idle").await;
        assert_eq!(active_count(), 0);
        assert!(wait_until_idle(std::time::Duration::from_millis(30)).await);
        let (shutdown_tx, mut shutdown_rx) = mpsc::channel(1);
        let (_ready_tx, ready_rx) =
            tokio::sync::watch::channel(super::super::RuntimeReadyState::Ready);
        let shutdown = StreamingMessage {
            message_id: "shutdown-with-background-child".to_string(),
            body: Some(
                crate::posix::runtime_rpc::streaming_message::Body::ShutdownReq(
                    crate::posix::runtime_service::ShutdownRequest {
                        grace_period_second: 0,
                    },
                ),
            ),
            ..Default::default()
        };
        let ctx = std::sync::Arc::new(super::super::dispatch::Ctx::new(
            super::super::Args::default(),
        ));
        assert!(
            super::super::handle_inbound_message(
                shutdown,
                "sandbox-under-test",
                ctx,
                shutdown_tx,
                ready_rx,
            )
            .await
        );
        let response = tokio::time::timeout(std::time::Duration::from_secs(2), shutdown_rx.recv())
            .await
            .expect("shutdown response")
            .expect("shutdown channel open");
        let Some(crate::posix::runtime_rpc::streaming_message::Body::ShutdownRsp(response)) =
            response.body
        else {
            panic!("expected ShutdownRsp");
        };
        assert_eq!(
            response.code,
            crate::posix::common::ErrorCode::ErrNone as i32
        );
        let poll_args = std::collections::BTreeMap::from([
            ("pid".to_string(), rmpv::Value::from(pid)),
            ("wait_timeout".to_string(), rmpv::Value::from(0)),
        ]);
        let polled = super::super::cmd::cmd_poll(&poll_args);
        assert!(polled.as_map().unwrap().iter().any(|(key, value)| {
            key.as_str() == Some("status") && value.as_str() == Some("running")
        }));
        report_current_activity();
        recv_report(&mut rx, "idle").await;

        // Interacting with the background process keeps the sandbox busy.
        let request = enter(ActivitySource::DirectHttp);
        recv_report(&mut rx, "busy").await;
        assert_eq!(current_state(), "busy");
        assert!(!wait_until_idle(std::time::Duration::ZERO).await);
        drop(request);
        recv_report(&mut rx, "idle").await;
        assert_eq!(active_count(), 0);

        let args = std::collections::BTreeMap::from([
            ("pid".to_string(), rmpv::Value::from(pid)),
            ("eof".to_string(), rmpv::Value::from(true)),
        ]);
        super::super::cmd::cmd_send_stdin(&args);
        let wait_args = std::collections::BTreeMap::from([
            ("pid".to_string(), rmpv::Value::from(pid)),
            ("timeout".to_string(), rmpv::Value::from(2.0)),
        ]);
        let result = tokio::task::spawn_blocking(move || super::super::cmd::cmd_wait(&wait_args))
            .await
            .expect("wait for test child");
        assert!(result.as_map().unwrap().iter().any(|(key, value)| {
            key.as_str() == Some("exit_code") && value.as_i64() == Some(0)
        }));
        assert!(wait_until_idle(std::time::Duration::from_secs(2)).await);
        assert_eq!(active_count(), 0);
        assert_eq!(current_state(), "idle");
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn last_request_guard_on_plain_thread_reports_idle() {
        const ENV: &str = "YR_RRT_ACTIVITY_PLAIN_THREAD_IDLE_ISOLATED";
        const TEST: &str =
            "runtime::activity::tests::last_request_guard_on_plain_thread_reports_idle";
        if !run_in_isolated_process(ENV, TEST) {
            return;
        }

        let (tx, mut rx) = mpsc::channel(8);
        init_reporter("sandbox-under-test".to_string(), tx);
        let request = enter(ActivitySource::RuntimeRpc);
        recv_report(&mut rx, "busy").await;

        std::thread::spawn(move || {
            assert!(tokio::runtime::Handle::try_current().is_err());
            drop(request);
        })
        .join()
        .expect("plain activity thread");
        assert_eq!(active_count(), 0);
        recv_report(&mut rx, "idle").await;
    }

    #[tokio::test]
    async fn process_exit_reports_idle_on_current_thread_runtime() {
        const ENV: &str = "YR_RRT_ACTIVITY_PROCESS_EXIT_ISOLATED";
        const TEST: &str =
            "runtime::activity::tests::process_exit_reports_idle_on_current_thread_runtime";
        if !run_in_isolated_process(ENV, TEST) {
            return;
        }

        let (tx, mut rx) = mpsc::channel(8);
        init_reporter("sandbox-under-test".to_string(), tx);
        let request = enter(ActivitySource::RuntimeRpc);
        let args =
            std::collections::BTreeMap::from([("cmd".to_string(), rmpv::Value::from("exit 0"))]);
        // Exercise cmd_start's real Child::wait + plain waiter thread, using
        // the same current-thread runtime flavor as the production binary.
        let started = super::super::cmd::cmd_start(&args);
        let pid = started
            .as_map()
            .unwrap()
            .iter()
            .find_map(|(key, value)| {
                (key.as_str() == Some("pid"))
                    .then(|| value.as_i64())
                    .flatten()
            })
            .expect("started process pid");
        assert!(pid > 0);
        drop(request);
        recv_report(&mut rx, "busy").await;
        recv_report(&mut rx, "idle").await;
        assert_eq!(active_count(), 0);
    }

    #[tokio::test]
    async fn cancelled_debounce_then_plain_thread_exit_reports_idle() {
        const ENV: &str = "YR_RRT_ACTIVITY_CANCELLED_THEN_THREAD_EXIT_ISOLATED";
        const TEST: &str =
            "runtime::activity::tests::cancelled_debounce_then_plain_thread_exit_reports_idle";
        if !run_in_isolated_process(ENV, TEST) {
            return;
        }

        let (tx, mut rx) = mpsc::channel(8);
        init_reporter("sandbox-under-test".to_string(), tx);
        let call = enter(ActivitySource::RuntimeRpc);
        recv_report(&mut rx, "busy").await;
        drop(call);
        let request = enter(ActivitySource::RuntimeRpc);
        recv_report(&mut rx, "busy").await;
        tokio::time::sleep(IDLE_REPORT_DEBOUNCE + std::time::Duration::from_millis(100)).await;
        assert!(matches!(rx.try_recv(), Err(TryRecvError::Empty)));

        std::thread::spawn(move || drop(request))
            .join()
            .expect("plain activity thread");
        recv_report(&mut rx, "idle").await;
    }

    #[tokio::test]
    async fn periodic_snapshot_repairs_idle_dropped_by_full_queue() {
        const ENV: &str = "YR_RRT_ACTIVITY_PERIODIC_QUEUE_REPAIR_ISOLATED";
        const TEST: &str =
            "runtime::activity::tests::periodic_snapshot_repairs_idle_dropped_by_full_queue";
        if !run_in_isolated_process(ENV, TEST) {
            return;
        }

        let (tx, mut rx) = mpsc::channel(1);
        init_reporter_with_interval(
            "sandbox-under-test".to_string(),
            tx,
            std::time::Duration::from_millis(100),
        );
        // Leave busy in the single-slot queue until the final idle edge has
        // attempted delivery. No new activity follows to trigger another edge.
        let request = enter(ActivitySource::RuntimeRpc);
        std::thread::spawn(move || drop(request))
            .join()
            .expect("plain activity thread");
        tokio::time::sleep(IDLE_REPORT_DEBOUNCE + std::time::Duration::from_millis(300)).await;
        recv_report(&mut rx, "busy").await;
        recv_report(&mut rx, "idle").await;
        // Snapshots continue even without any further work or reconnect.
        recv_report(&mut rx, "idle").await;
    }

    #[tokio::test]
    async fn periodic_snapshot_preserves_busy_debounce_and_rebound_identity() {
        const ENV: &str = "YR_RRT_ACTIVITY_PERIODIC_STATE_ISOLATED";
        const TEST: &str =
            "runtime::activity::tests::periodic_snapshot_preserves_busy_debounce_and_rebound_identity";
        if !run_in_isolated_process(ENV, TEST) {
            return;
        }

        let (tx, mut rx) = mpsc::channel(8);
        init_reporter_with_interval(
            "source-sandbox".to_string(),
            tx,
            std::time::Duration::from_millis(100),
        );
        let request = enter(ActivitySource::RuntimeRpc);
        recv_report(&mut rx, "busy").await;
        recv_report(&mut rx, "busy").await;
        drop(request);
        assert!(
            tokio::time::timeout(std::time::Duration::from_millis(400), rx.recv())
                .await
                .is_err()
        );
        recv_report(&mut rx, "idle").await;
        while rx.try_recv().is_ok() {}

        rebind_reporter_instance_id("clone-sandbox");
        let msg = tokio::time::timeout(std::time::Duration::from_secs(2), rx.recv())
            .await
            .expect("periodic snapshot")
            .expect("reporter open");
        let Some(crate::posix::runtime_rpc::streaming_message::Body::KillReq(kill)) = msg.body
        else {
            panic!("expected activity KillReq");
        };
        assert_eq!(kill.instance_id, "clone-sandbox");
        assert_eq!(kill.payload, b"idle");
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn tunnel_within_idle_debounce_reasserts_busy_then_reports_idle_on_disconnect() {
        const ENV: &str = "YR_RRT_ACTIVITY_TUNNEL_WITHIN_DEBOUNCE_ISOLATED";
        const TEST: &str = "runtime::activity::tests::tunnel_within_idle_debounce_reasserts_busy_then_reports_idle_on_disconnect";
        if !run_in_isolated_process(ENV, TEST) {
            return;
        }

        let (tx, mut rx) = mpsc::channel(8);
        init_reporter("sandbox-under-test".to_string(), tx);

        let init_call = enter(ActivitySource::RuntimeRpc);
        recv_report(&mut rx, "busy").await;
        drop(init_call);

        tokio::time::sleep(std::time::Duration::from_millis(100)).await;
        let tunnel = enter(ActivitySource::Tunnel);
        recv_report(&mut rx, "busy").await;

        tokio::time::sleep(IDLE_REPORT_DEBOUNCE + std::time::Duration::from_millis(100)).await;
        assert!(matches!(rx.try_recv(), Err(TryRecvError::Empty)));

        drop(tunnel);
        recv_report(&mut rx, "idle").await;
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn tunnel_after_idle_debounce_reports_idle_then_busy() {
        const ENV: &str = "YR_RRT_ACTIVITY_TUNNEL_AFTER_DEBOUNCE_ISOLATED";
        const TEST: &str =
            "runtime::activity::tests::tunnel_after_idle_debounce_reports_idle_then_busy";
        if !run_in_isolated_process(ENV, TEST) {
            return;
        }

        let (tx, mut rx) = mpsc::channel(8);
        init_reporter("sandbox-under-test".to_string(), tx);

        let init_call = enter(ActivitySource::RuntimeRpc);
        recv_report(&mut rx, "busy").await;
        drop(init_call);
        recv_report(&mut rx, "idle").await;

        let tunnel = enter(ActivitySource::Tunnel);
        recv_report(&mut rx, "busy").await;
        drop(tunnel);
        recv_report(&mut rx, "idle").await;
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn overlapping_init_call_and_tunnel_each_report_busy() {
        const ENV: &str = "YR_RRT_ACTIVITY_OVERLAPPING_TUNNEL_ISOLATED";
        const TEST: &str =
            "runtime::activity::tests::overlapping_init_call_and_tunnel_each_report_busy";
        if !run_in_isolated_process(ENV, TEST) {
            return;
        }

        let (tx, mut rx) = mpsc::channel(8);
        init_reporter("sandbox-under-test".to_string(), tx);

        let init_call = enter(ActivitySource::RuntimeRpc);
        recv_report(&mut rx, "busy").await;
        let tunnel = enter(ActivitySource::Tunnel);
        recv_report(&mut rx, "busy").await;

        let poll = enter(ActivitySource::DirectHttp);
        recv_report(&mut rx, "busy").await;
        drop(poll);

        drop(init_call);
        tokio::time::sleep(IDLE_REPORT_DEBOUNCE + std::time::Duration::from_millis(100)).await;
        assert!(matches!(rx.try_recv(), Err(TryRecvError::Empty)));

        drop(tunnel);
        recv_report(&mut rx, "idle").await;
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn repeated_direct_polling_reasserts_busy_before_debounced_idle() {
        const ENV: &str = "YR_RRT_ACTIVITY_REPEATED_POLL_ISOLATED";
        const TEST: &str =
            "runtime::activity::tests::repeated_direct_polling_reasserts_busy_before_debounced_idle";
        if !run_in_isolated_process(ENV, TEST) {
            return;
        }

        let (tx, mut rx) = mpsc::channel(8);
        init_reporter("sandbox-under-test".to_string(), tx);

        for _ in 0..3 {
            let poll = enter(ActivitySource::DirectHttp);
            recv_report(&mut rx, "busy").await;
            drop(poll);
            tokio::time::sleep(std::time::Duration::from_millis(100)).await;
        }
        recv_report(&mut rx, "idle").await;
    }
}
