mod audit;

use std::{collections::HashMap, sync::Arc, time::Duration};

use anyhow::{Context, Result, ensure};
use audit::AuditHostPlugin;
use bytes::Bytes;
use semver::Version;
use tokio::time::timeout;
use wash_runtime::{
    engine::Engine,
    host::{
        HostApi, HostBuilder,
        http::{DevRouter, Ingress},
    },
    types::{
        Component, LocalResources, Workload, WorkloadStartRequest, WorkloadState,
        WorkloadStopRequest,
    },
    wit::WitInterface,
};

const PROCESS_WASM: &[u8] = include_bytes!(
    "../../components/process/target/wasm32-wasip2/release/audiagentic_process.wasm"
);
const WORKFLOW_DEFAULT_WASM: &[u8] = include_bytes!(
    "../../components/workflow-default/target/wasm32-wasip2/release/audiagentic_workflow_default.wasm"
);
const WORKFLOW_ALT_WASM: &[u8] = include_bytes!(
    "../../components/workflow-alt/target/wasm32-wasip2/release/audiagentic_workflow_alt.wasm"
);

fn resources() -> LocalResources {
    LocalResources {
        memory_limit_mb: 128,
        cpu_limit: 1,
        config: HashMap::new(),
        environment: HashMap::new(),
        volume_mounts: vec![],
        // The smoke deliberately grants no network or host-loopback authority.
        allowed_hosts: Default::default(),
        allowed_ip_name_lookups: Default::default(),
        allowed_host_loopback_ports: Default::default(),
    }
}

fn component(name: &str, bytes: &'static [u8]) -> Component {
    Component {
        name: name.to_owned(),
        bytes: Bytes::from_static(bytes),
        digest: None,
        local_resources: resources(),
        pool_size: 1,
        max_invocations: 32,
        max_concurrency: 1,
    }
}

fn host_interfaces(hostname: &str) -> Vec<WitInterface> {
    vec![
        WitInterface {
            namespace: "wasi".to_owned(),
            package: "http".to_owned(),
            interfaces: ["incoming-handler".to_owned()].into_iter().collect(),
            version: Some(Version::parse("0.2.2").expect("constant semver")),
            config: HashMap::from([("host".to_owned(), hostname.to_owned())]),
            name: None,
        },
        WitInterface {
            namespace: "audiagentic".to_owned(),
            package: "host".to_owned(),
            interfaces: ["audit".to_owned()].into_iter().collect(),
            version: Some(Version::parse("0.1.0").expect("constant semver")),
            config: HashMap::new(),
            name: None,
        },
    ]
}

fn workload(name: &str, providers: Vec<(&str, &'static [u8])>) -> Workload {
    let hostname = format!("{name}.smoke");
    let mut components = Vec::with_capacity(1 + providers.len());
    components.push(component("process", PROCESS_WASM));
    components.extend(providers.into_iter().map(|(n, b)| component(n, b)));

    Workload {
        namespace: "audiagentic-smoke".to_owned(),
        name: name.to_owned(),
        annotations: HashMap::new(),
        service: None,
        components,
        host_interfaces: host_interfaces(&hostname),
        volumes: vec![],
    }
}

async fn start_case(
    host: &impl HostApi,
    base_url: &str,
    name: &str,
    providers: Vec<(&str, &'static [u8])>,
    expected: &str,
) -> Result<String> {
    let workload_id = format!("{name}-{}", uuid::Uuid::new_v4());
    let response = host
        .workload_start(WorkloadStartRequest {
            workload_id: workload_id.clone(),
            workload: workload(name, providers),
        })
        .await
        .with_context(|| format!("start {name}"))?;

    ensure!(
        response.workload_status.workload_state == WorkloadState::Running,
        "{name} did not reach running: {:?}: {}",
        response.workload_status.workload_state,
        response.workload_status.message
    );

    let http = reqwest::Client::new();
    let reply = timeout(
        Duration::from_secs(15),
        http.get(base_url)
            .header("HOST", format!("{name}.smoke"))
            .send(),
    )
    .await
    .with_context(|| format!("HTTP timeout for {name}"))??;
    ensure!(
        reply.status().is_success(),
        "{name} returned {}",
        reply.status()
    );
    let body = reply.text().await?;
    ensure!(
        body == expected,
        "{name}: expected {expected:?}, got {body:?}"
    );

    let stopped = host
        .workload_stop(WorkloadStopRequest {
            workload_id: workload_id.clone(),
        })
        .await?;
    ensure!(
        matches!(
            stopped.workload_status.workload_state,
            WorkloadState::Stopping | WorkloadState::Completed | WorkloadState::NotFound
        ),
        "{name} stop failed: {:?}: {}",
        stopped.workload_status.workload_state,
        stopped.workload_status.message
    );

    Ok(body)
}

async fn expect_start_failure(
    host: &impl HostApi,
    name: &str,
    providers: Vec<(&str, &'static [u8])>,
) -> Result<String> {
    let workload_id = format!("{name}-{}", uuid::Uuid::new_v4());
    let response = host
        .workload_start(WorkloadStartRequest {
            workload_id: workload_id.clone(),
            workload: workload(name, providers),
        })
        .await?;

    ensure!(
        response.workload_status.workload_state == WorkloadState::Error,
        "{name} unexpectedly started: {:?}: {}",
        response.workload_status.workload_state,
        response.workload_status.message
    );

    let _ = host
        .workload_stop(WorkloadStopRequest { workload_id })
        .await;
    Ok(response.workload_status.message)
}

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into()),
        )
        .init();

    let engine = Engine::builder().build()?;
    let ingress = Ingress::new(DevRouter::default(), "127.0.0.1:0".parse()?).await?;
    let addr = ingress.addr();
    let audit = Arc::new(AuditHostPlugin::default());

    let host = HostBuilder::new()
        .with_engine(engine)
        .with_http_handler(Arc::new(ingress))
        .with_plugin(audit.clone())?
        .build()?
        .start()
        .await
        .context("start host")?;

    let base_url = format!("http://{addr}/");

    let default = start_case(
        &host,
        &base_url,
        "default-provider",
        vec![("workflow-default", WORKFLOW_DEFAULT_WASM)],
        "workflow-default:smoke",
    )
    .await?;
    println!("DEFAULT_PROVIDER={default}");

    let alternate = start_case(
        &host,
        &base_url,
        "alternate-provider",
        vec![("workflow-alt", WORKFLOW_ALT_WASM)],
        "workflow-alt:smoke",
    )
    .await?;
    println!("ALTERNATE_PROVIDER={alternate}");

    let missing = expect_start_failure(&host, "missing-provider", vec![]).await?;
    println!("MISSING_PROVIDER_REJECTED={missing}");

    let duplicate = expect_start_failure(
        &host,
        "duplicate-provider",
        vec![
            ("workflow-default", WORKFLOW_DEFAULT_WASM),
            ("workflow-alt", WORKFLOW_ALT_WASM),
        ],
    )
    .await?;
    println!("DUPLICATE_PROVIDER_REJECTED={duplicate}");

    let snapshot = audit.snapshot().await;
    ensure!(
        snapshot.calls == 2,
        "expected 2 audit calls, got {}",
        snapshot.calls
    );
    ensure!(
        snapshot.binds >= 2,
        "expected audit bind lifecycle callbacks"
    );
    ensure!(
        snapshot.unbinds >= 2,
        "expected audit unbind lifecycle callbacks"
    );
    println!("AUDIT_CALLS={}", snapshot.calls);
    println!("AUDIT_BINDS={}", snapshot.binds);
    println!("AUDIT_RESOLVED={}", snapshot.resolved);
    println!("AUDIT_UNBINDS={}", snapshot.unbinds);
    println!("AUDIT_ENTRIES={:?}", snapshot.entries);

    host.stop().await.context("stop host")?;
    println!("SMOKE_OK");
    Ok(())
}
