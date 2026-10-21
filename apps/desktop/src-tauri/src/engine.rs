//! Supervisor for the Python engine sidecar.
//!
//! The engine speaks newline-delimited JSON-RPC 2.0 over stdin/stdout and
//! opens no network port (design.md §2, D-003). This module starts it,
//! performs the protocol-version handshake, correlates responses, forwards
//! notifications, detects crashes, and restarts with exponential backoff.

use std::collections::HashMap;
use std::path::PathBuf;
use std::process::Stdio;
use std::sync::atomic::{AtomicBool, AtomicU32, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use serde::Serialize;
use serde_json::{json, Value};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::process::{Child, ChildStdin, Command};
use tokio::sync::{oneshot, Notify};

pub const PROTOCOL_VERSION: u64 = 1;
const HANDSHAKE_TIMEOUT: Duration = Duration::from_secs(60);
const SHUTDOWN_GRACE: Duration = Duration::from_secs(5);

#[derive(Clone, Debug)]
pub struct LaunchSpec {
    pub program: PathBuf,
    pub args: Vec<String>,
    pub cwd: Option<PathBuf>,
}

#[derive(Clone, Debug)]
pub struct RestartPolicy {
    pub base_delay: Duration,
    pub max_delay: Duration,
    /// Consecutive crashes before giving up and waiting for a manual restart.
    pub max_attempts: u32,
    /// A run longer than this resets the crash counter.
    pub healthy_after: Duration,
}

impl Default for RestartPolicy {
    fn default() -> Self {
        Self {
            base_delay: Duration::from_secs(1),
            max_delay: Duration::from_secs(30),
            max_attempts: 5,
            healthy_after: Duration::from_secs(60),
        }
    }
}

impl RestartPolicy {
    pub fn delay_for(&self, attempt: u32) -> Duration {
        let factor = 2u32.saturating_pow(attempt.saturating_sub(1));
        self.base_delay.saturating_mul(factor).min(self.max_delay)
    }
}

#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum EngineState {
    Starting,
    Running { pid: u32 },
    Restarting { attempt: u32, delay_ms: u64 },
    Failed { code: String },
    Stopped,
}

#[derive(Clone, Debug)]
pub enum EngineEvent {
    State(EngineState),
    Notification(Value),
}

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct RpcError {
    pub code: i64,
    pub message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub data: Option<Value>,
}

impl RpcError {
    pub fn local(code: &str, message: &str) -> Self {
        Self {
            code: -32099,
            message: message.to_string(),
            data: Some(json!({ "code": code })),
        }
    }
}

type Pending = Mutex<HashMap<u64, oneshot::Sender<Result<Value, RpcError>>>>;
type Sink = Box<dyn Fn(EngineEvent) + Send + Sync>;

struct Inner {
    spec: LaunchSpec,
    policy: RestartPolicy,
    sink: Sink,
    state: Mutex<EngineState>,
    stdin: tokio::sync::Mutex<Option<ChildStdin>>,
    pending: Pending,
    next_id: AtomicU64,
    attempts: AtomicU32,
    stopping: AtomicBool,
    manual_restart: AtomicBool,
    wake: Notify,
    kill: Mutex<Option<oneshot::Sender<()>>>,
}

#[derive(Clone)]
pub struct Supervisor {
    inner: Arc<Inner>,
}

impl Supervisor {
    pub fn new(spec: LaunchSpec, policy: RestartPolicy, sink: Sink) -> Self {
        Self {
            inner: Arc::new(Inner {
                spec,
                policy,
                sink,
                state: Mutex::new(EngineState::Stopped),
                stdin: tokio::sync::Mutex::new(None),
                pending: Mutex::new(HashMap::new()),
                next_id: AtomicU64::new(1),
                attempts: AtomicU32::new(0),
                stopping: AtomicBool::new(false),
                manual_restart: AtomicBool::new(false),
                wake: Notify::new(),
                kill: Mutex::new(None),
            }),
        }
    }

    pub fn state(&self) -> EngineState {
        self.inner.state.lock().expect("state lock").clone()
    }

    /// Start the supervision loop on the current tokio runtime.
    pub fn start(&self) {
        let this = self.clone();
        tokio::spawn(async move { this.run().await });
    }

    fn set_state(&self, state: EngineState) {
        {
            let mut guard = self.inner.state.lock().expect("state lock");
            if *guard == state {
                return;
            }
            *guard = state.clone();
        }
        (self.inner.sink)(EngineEvent::State(state));
    }

    async fn run(&self) {
        loop {
            if self.inner.stopping.load(Ordering::SeqCst) {
                break;
            }
            self.set_state(EngineState::Starting);
            let started = Instant::now();
            match self.spawn_child() {
                Ok(child) => self.supervise(child).await,
                Err(_) => {
                    // Spawn failure is handled like a crash; the reason is not
                    // logged with paths to keep diagnostics sanitized.
                }
            }
            *self.inner.stdin.lock().await = None;
            self.fail_pending("engine_unavailable", "The engine stopped unexpectedly");

            if self.inner.stopping.load(Ordering::SeqCst) {
                break;
            }
            let manual = self.inner.manual_restart.swap(false, Ordering::SeqCst);
            if manual || started.elapsed() >= self.inner.policy.healthy_after {
                self.inner.attempts.store(0, Ordering::SeqCst);
            }
            if manual {
                continue; // User-requested restart: no backoff.
            }
            let attempt = self.inner.attempts.fetch_add(1, Ordering::SeqCst) + 1;
            if attempt > self.inner.policy.max_attempts {
                self.set_state(EngineState::Failed {
                    code: "crash_loop".into(),
                });
                // Wait for restart() or stop().
                self.inner.wake.notified().await;
                self.inner.attempts.store(0, Ordering::SeqCst);
                self.inner.manual_restart.store(false, Ordering::SeqCst);
                continue;
            }
            let delay = self.inner.policy.delay_for(attempt);
            self.set_state(EngineState::Restarting {
                attempt,
                delay_ms: delay.as_millis() as u64,
            });
            tokio::select! {
                _ = tokio::time::sleep(delay) => {}
                _ = self.inner.wake.notified() => {}
            }
        }
        if !matches!(self.state(), EngineState::Failed { .. }) {
            self.set_state(EngineState::Stopped);
        }
    }

    fn spawn_child(&self) -> std::io::Result<Child> {
        let spec = &self.inner.spec;
        let mut command = Command::new(&spec.program);
        command
            .args(&spec.args)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true);
        if let Some(cwd) = &spec.cwd {
            command.current_dir(cwd);
        }
        #[cfg(windows)]
        {
            // CREATE_NO_WINDOW: no console window for the sidecar.
            command.creation_flags(0x0800_0000);
        }
        command.spawn()
    }

    async fn supervise(&self, mut child: Child) {
        let pid = child.id().unwrap_or_default();
        let stdout = child.stdout.take();
        let stderr = child.stderr.take();
        *self.inner.stdin.lock().await = child.stdin.take();

        if let Some(stdout) = stdout {
            let this = self.clone();
            tokio::spawn(async move {
                let mut lines = BufReader::new(stdout).lines();
                while let Ok(Some(line)) = lines.next_line().await {
                    this.handle_line(&line);
                }
            });
        }
        if let Some(stderr) = stderr {
            // Drain stderr so the engine never blocks on a full pipe. The
            // engine writes its own sanitized log file; nothing is re-logged.
            tokio::spawn(async move {
                let mut lines = BufReader::new(stderr).lines();
                while let Ok(Some(_line)) = lines.next_line().await {}
            });
        }

        let this = self.clone();
        tokio::spawn(async move {
            match this
                .request_with_timeout(
                    "health",
                    json!({ "protocol_version": PROTOCOL_VERSION }),
                    HANDSHAKE_TIMEOUT,
                )
                .await
            {
                Ok(_) => this.set_state(EngineState::Running { pid }),
                Err(err) => {
                    let code = err
                        .data
                        .as_ref()
                        .and_then(|d| d.get("code"))
                        .and_then(Value::as_str)
                        .unwrap_or("handshake_failed")
                        .to_string();
                    if code == "protocol_mismatch" {
                        this.inner.stopping.store(true, Ordering::SeqCst);
                        this.set_state(EngineState::Failed { code });
                    }
                    this.kill_current();
                }
            }
        });

        let (kill_tx, kill_rx) = oneshot::channel();
        *self.inner.kill.lock().expect("kill lock") = Some(kill_tx);
        tokio::select! {
            _ = child.wait() => {}
            _ = kill_rx => {
                let _ = child.start_kill();
                let _ = child.wait().await;
            }
        }
        *self.inner.kill.lock().expect("kill lock") = None;
    }

    fn kill_current(&self) {
        if let Some(tx) = self.inner.kill.lock().expect("kill lock").take() {
            let _ = tx.send(());
        }
    }

    fn handle_line(&self, line: &str) {
        let Ok(message) = serde_json::from_str::<Value>(line) else {
            return; // Non-JSON on stdout is a protocol violation; ignore it.
        };
        match message.get("id").and_then(Value::as_u64) {
            Some(id) if message.get("method").is_none() => {
                let sender = self.inner.pending.lock().expect("pending lock").remove(&id);
                if let Some(sender) = sender {
                    let outcome = if let Some(error) = message.get("error") {
                        Err(RpcError {
                            code: error.get("code").and_then(Value::as_i64).unwrap_or(-32603),
                            message: error
                                .get("message")
                                .and_then(Value::as_str)
                                .unwrap_or("Engine error")
                                .to_string(),
                            data: error.get("data").cloned(),
                        })
                    } else {
                        Ok(message.get("result").cloned().unwrap_or(Value::Null))
                    };
                    let _ = sender.send(outcome);
                }
            }
            _ => {
                if message.get("method").is_some() {
                    (self.inner.sink)(EngineEvent::Notification(message));
                }
            }
        }
    }

    fn fail_pending(&self, code: &str, message: &str) {
        let drained: Vec<_> = self
            .inner
            .pending
            .lock()
            .expect("pending lock")
            .drain()
            .collect();
        for (_, sender) in drained {
            let _ = sender.send(Err(RpcError::local(code, message)));
        }
    }

    pub async fn request(&self, method: &str, params: Value) -> Result<Value, RpcError> {
        self.request_with_timeout(method, params, Duration::from_secs(120))
            .await
    }

    pub async fn request_with_timeout(
        &self,
        method: &str,
        params: Value,
        timeout: Duration,
    ) -> Result<Value, RpcError> {
        let id = self.inner.next_id.fetch_add(1, Ordering::SeqCst);
        let (tx, rx) = oneshot::channel();
        self.inner
            .pending
            .lock()
            .expect("pending lock")
            .insert(id, tx);
        let mut payload = serde_json::to_vec(&json!({
            "jsonrpc": "2.0", "id": id, "method": method, "params": params
        }))
        .map_err(|_| RpcError::local("encode_failed", "Could not encode request"))?;
        payload.push(b'\n');
        {
            let mut stdin = self.inner.stdin.lock().await;
            let written = match stdin.as_mut() {
                Some(pipe) => pipe
                    .write_all(&payload)
                    .await
                    .and(pipe.flush().await)
                    .is_ok(),
                None => false,
            };
            if !written {
                self.inner.pending.lock().expect("pending lock").remove(&id);
                return Err(RpcError::local(
                    "engine_unavailable",
                    "The engine is not running",
                ));
            }
        }
        match tokio::time::timeout(timeout, rx).await {
            Ok(Ok(outcome)) => outcome,
            Ok(Err(_)) => Err(RpcError::local(
                "engine_unavailable",
                "The engine stopped unexpectedly",
            )),
            Err(_) => {
                self.inner.pending.lock().expect("pending lock").remove(&id);
                Err(RpcError::local(
                    "timeout",
                    "The engine did not respond in time",
                ))
            }
        }
    }

    /// Restart now: resets the crash counter and kills the current process.
    pub fn restart(&self) {
        self.inner.manual_restart.store(true, Ordering::SeqCst);
        self.inner.attempts.store(0, Ordering::SeqCst);
        self.kill_current();
        self.inner.wake.notify_one();
    }

    /// Graceful stop: ask the engine to shut down, close stdin, then kill
    /// after a grace period.
    pub async fn stop(&self) {
        self.inner.stopping.store(true, Ordering::SeqCst);
        let _ = self
            .request_with_timeout("shutdown", json!({}), Duration::from_secs(2))
            .await;
        *self.inner.stdin.lock().await = None;
        let deadline = Instant::now() + SHUTDOWN_GRACE;
        while Instant::now() < deadline {
            if self.inner.kill.lock().expect("kill lock").is_none() {
                break;
            }
            tokio::time::sleep(Duration::from_millis(50)).await;
        }
        self.kill_current();
        self.inner.wake.notify_one();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::mpsc;

    /// A tiny stand-in engine written in Python: answers `health`, echoes
    /// `echo`, exits on `crash`, and stops on `shutdown` or EOF.
    const FAKE_ENGINE: &str = r#"
import json, sys
print(json.dumps({"jsonrpc":"2.0","method":"engine.ready","params":{"protocol_version":1}}), flush=True)
for line in sys.stdin:
    req = json.loads(line)
    m = req["method"]
    if m == "crash":
        sys.exit(3)
    if m == "health":
        v = req["params"].get("protocol_version")
        if v != int(sys.argv[1]):
            print(json.dumps({"jsonrpc":"2.0","id":req["id"],"error":{"code":-32001,"message":"mismatch","data":{"code":"protocol_mismatch"}}}), flush=True)
            continue
        res = {"ok": True}
    elif m == "echo":
        res = req["params"]
    elif m == "shutdown":
        print(json.dumps({"jsonrpc":"2.0","id":req["id"],"result":{"stopping":True}}), flush=True)
        break
    else:
        print(json.dumps({"jsonrpc":"2.0","id":req["id"],"error":{"code":-32601,"message":"Method not found"}}), flush=True)
        continue
    print(json.dumps({"jsonrpc":"2.0","id":req["id"],"result":res}), flush=True)
"#;

    fn spec(version: u64) -> LaunchSpec {
        LaunchSpec {
            program: PathBuf::from(if cfg!(windows) { "python" } else { "python3" }),
            args: vec!["-c".into(), FAKE_ENGINE.into(), version.to_string()],
            cwd: None,
        }
    }

    fn fast_policy() -> RestartPolicy {
        RestartPolicy {
            base_delay: Duration::from_millis(50),
            max_delay: Duration::from_millis(200),
            max_attempts: 3,
            healthy_after: Duration::from_secs(60),
        }
    }

    fn supervisor(version: u64) -> (Supervisor, mpsc::Receiver<EngineEvent>) {
        let (tx, rx) = mpsc::channel();
        let tx = Mutex::new(tx);
        let sup = Supervisor::new(
            spec(version),
            fast_policy(),
            Box::new(move |event| {
                let _ = tx.lock().unwrap().send(event);
            }),
        );
        (sup, rx)
    }

    async fn wait_for<F: Fn(&EngineState) -> bool>(sup: &Supervisor, pred: F) {
        for _ in 0..200 {
            if pred(&sup.state()) {
                return;
            }
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
        panic!("state never matched; last = {:?}", sup.state());
    }

    #[test]
    fn backoff_grows_and_caps() {
        let policy = RestartPolicy::default();
        assert_eq!(policy.delay_for(1), Duration::from_secs(1));
        assert_eq!(policy.delay_for(2), Duration::from_secs(2));
        assert_eq!(policy.delay_for(4), Duration::from_secs(8));
        assert_eq!(policy.delay_for(10), Duration::from_secs(30));
    }

    #[tokio::test]
    async fn round_trip_and_notifications() {
        let (sup, rx) = supervisor(PROTOCOL_VERSION);
        sup.start();
        wait_for(&sup, |s| matches!(s, EngineState::Running { .. })).await;
        let result = sup.request("echo", json!({"x": 1})).await.unwrap();
        assert_eq!(result, json!({"x": 1}));
        let err = sup.request("missing", json!({})).await.unwrap_err();
        assert_eq!(err.code, -32601);
        let saw_ready = rx.try_iter().any(
            |e| matches!(e, EngineEvent::Notification(ref v) if v["method"] == "engine.ready"),
        );
        assert!(saw_ready);
        sup.stop().await;
        wait_for(&sup, |s| *s == EngineState::Stopped).await;
    }

    #[tokio::test]
    async fn crash_is_detected_and_restarted() {
        let (sup, _rx) = supervisor(PROTOCOL_VERSION);
        sup.start();
        wait_for(&sup, |s| matches!(s, EngineState::Running { .. })).await;
        let EngineState::Running { pid: first } = sup.state() else {
            unreachable!()
        };
        let err = sup.request("crash", json!({})).await.unwrap_err();
        assert_eq!(err.data.unwrap()["code"], "engine_unavailable");
        wait_for(
            &sup,
            |s| matches!(s, EngineState::Running { pid } if *pid != first),
        )
        .await;
        assert_eq!(
            sup.request("echo", json!({"ok": true})).await.unwrap(),
            json!({"ok": true})
        );
        sup.stop().await;
    }

    #[tokio::test]
    async fn crash_loop_gives_up_until_manual_restart() {
        let (sup, _rx) = supervisor(PROTOCOL_VERSION);
        sup.start();
        for _ in 0..4 {
            wait_for(&sup, |s| {
                matches!(s, EngineState::Running { .. } | EngineState::Failed { .. })
            })
            .await;
            if matches!(sup.state(), EngineState::Failed { .. }) {
                break;
            }
            let _ = sup.request("crash", json!({})).await;
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
        wait_for(&sup, |s| matches!(s, EngineState::Failed { .. })).await;
        sup.restart();
        wait_for(&sup, |s| matches!(s, EngineState::Running { .. })).await;
        sup.stop().await;
    }

    #[tokio::test]
    async fn protocol_mismatch_fails_without_restart() {
        let (sup, _rx) = supervisor(PROTOCOL_VERSION + 1);
        sup.start();
        wait_for(
            &sup,
            |s| matches!(s, EngineState::Failed { code } if code == "protocol_mismatch"),
        )
        .await;
    }

    #[tokio::test]
    async fn request_when_stopped_is_unavailable() {
        let (sup, _rx) = supervisor(PROTOCOL_VERSION);
        let err = sup.request("echo", json!({})).await.unwrap_err();
        assert_eq!(err.data.unwrap()["code"], "engine_unavailable");
    }
}
