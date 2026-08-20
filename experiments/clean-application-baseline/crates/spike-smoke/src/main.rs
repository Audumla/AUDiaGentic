use std::{collections::BTreeMap, env, fs, sync::Arc};

use audiagentic_application_spike::Application;
use audiagentic_component_host_spike::WasmComponentProbe;
use audiagentic_component_probe_api_spike::ComponentProbe;
use audiagentic_filesystem_api_spike::{FileSystem, RelativePath};
use audiagentic_filesystem_native_spike::NativeFileSystem;
use audiagentic_kernel_core_spike::{ApplicationContext, ApplicationId};
use audiagentic_managed_config_api_spike::{ManagedConfig, ReconcileOutcome};
use audiagentic_managed_config_json_spike::JsonManagedConfig;
use audiagentic_mcp_adapter_spike::McpApplication;
use audiagentic_process_api_spike::{ProcessError, ProcessRequest, ProcessRunner};
use audiagentic_process_native_spike::NativeProcessRunner;
use audiagentic_runtime_bevy_spike::BevyWorkflow;
use audiagentic_secrets_api_spike::{SecretRef, SecretStore};
use audiagentic_secrets_memory_spike::MemorySecretStore;
use audiagentic_workflow_api_spike::{Workflow, WorkflowRequest};
use serde_json::{Value, json};

#[derive(Clone)]
struct SpikeCapabilities {
    workflow: Arc<dyn Workflow>,
    component_probe: Arc<dyn ComponentProbe>,
    filesystem: Arc<dyn FileSystem>,
    process: Arc<dyn ProcessRunner>,
    secrets: Arc<dyn SecretStore>,
    managed_config: Arc<dyn ManagedConfig>,
}

#[tokio::main]
async fn main() -> Result<(), String> {
    let minimal = Application::new(
        ApplicationContext::new(ApplicationId::new("minimal.app").map_err(|e| e.to_string())?),
        (),
    );
    assert_eq!(minimal.context().application.as_str(), "minimal.app");

    let wasm_smoke = env::var("AUDIAGENTIC_WASM_SMOKE_BIN")
        .map_err(|_| "AUDIAGENTIC_WASM_SMOKE_BIN is required".to_owned())?;

    let workflow: Arc<dyn Workflow> = Arc::new(BevyWorkflow::spawn()?);
    let component_probe: Arc<dyn ComponentProbe> = Arc::new(WasmComponentProbe::new(wasm_smoke));

    let root = env::temp_dir().join(format!("audiagentic-baseline-{}", std::process::id()));
    let _ = fs::remove_dir_all(&root);
    fs::create_dir_all(&root).map_err(|e| e.to_string())?;
    let filesystem: Arc<dyn FileSystem> =
        Arc::new(NativeFileSystem::open(&root).map_err(|e| e.to_string())?);
    let process: Arc<dyn ProcessRunner> = Arc::new(NativeProcessRunner::new(Vec::new()));
    let secrets: Arc<dyn SecretStore> = Arc::new(MemorySecretStore::new([(
        "example/default".to_owned(),
        "do-not-log-me".to_owned(),
    )]));
    let managed_config: Arc<dyn ManagedConfig> = Arc::new(JsonManagedConfig::new(filesystem.clone()));

    let app = Application::new(
        ApplicationContext::new(ApplicationId::new("composed.app").map_err(|e| e.to_string())?),
        SpikeCapabilities {
            workflow: workflow.clone(),
            component_probe: component_probe.clone(),
            filesystem: filesystem.clone(),
            process,
            secrets,
            managed_config,
        },
    );

    let workflow_result = app
        .capabilities()
        .workflow
        .run(WorkflowRequest {
            runs: 5_000,
            steps: 12,
        })
        .await?;
    if workflow_result.runs != 5_000
        || workflow_result.completed + workflow_result.cancelled != 5_000
    {
        return Err(format!(
            "workflow result did not converge: {workflow_result:?}"
        ));
    }

    let component = app.capabilities().component_probe.probe().await?;
    if component != "workflow-default:smoke" {
        return Err(format!("unexpected component provider: {component}"));
    }

    let config_path = RelativePath::new("config/example.txt").map_err(|e| e.to_string())?;
    app.capabilities()
        .filesystem
        .write_text_atomic(&config_path, "baseline".to_owned())
        .await
        .map_err(|e| e.to_string())?;
    let persisted = app
        .capabilities()
        .filesystem
        .read_text(&config_path)
        .await
        .map_err(|e| e.to_string())?;
    if persisted.as_deref() != Some("baseline") {
        return Err(format!("filesystem capability mismatch: {persisted:?}"));
    }

    let denied = app
        .capabilities()
        .process
        .run(ProcessRequest {
            program: "not-granted".into(),
            args: Vec::new(),
            environment: BTreeMap::new(),
        })
        .await;
    if denied != Err(ProcessError::Denied("not-granted".into())) {
        return Err(format!("process authority was not enforced: {denied:?}"));
    }

    let secret = app
        .capabilities()
        .secrets
        .resolve(&SecretRef::new("example/default").map_err(|e| e.to_string())?)
        .await
        .map_err(|e| e.to_string())?;
    if secret.expose() != "do-not-log-me"
        || format!("{secret}") != "[REDACTED]"
        || format!("{secret:?}") != "Secret([REDACTED])"
    {
        return Err("secret capability failed redaction boundary".to_owned());
    }

    let managed_path = RelativePath::new("config/settings.json").map_err(|e| e.to_string())?;
    app.capabilities()
        .filesystem
        .write_text_atomic(&managed_path, json!({"user_key":"keep"}).to_string())
        .await
        .map_err(|e| e.to_string())?;
    let created = app
        .capabilities()
        .managed_config
        .ensure_value(
            "config/settings.json",
            "managed_key",
            "baseline-app",
            Value::Bool(true),
        )
        .await
        .map_err(|e| e.to_string())?;
    if created != ReconcileOutcome::Created {
        return Err(format!("managed config did not create value: {created:?}"));
    }
    let managed_text = app
        .capabilities()
        .filesystem
        .read_text(&managed_path)
        .await
        .map_err(|e| e.to_string())?
        .ok_or_else(|| "managed config document disappeared".to_owned())?;
    let managed_value: Value = serde_json::from_str(&managed_text).map_err(|e| e.to_string())?;
    if managed_value["user_key"] != "keep" || managed_value["managed_key"] != true {
        return Err(format!(
            "managed config did not preserve/merge values: {managed_value}"
        ));
    }

    let _mcp_projection = McpApplication::new(workflow, component_probe);

    let _ = fs::remove_dir_all(&root);
    println!("APPLICATION_GENERIC_CORE_OK");
    println!("WORKFLOW_RUNS={}", workflow_result.runs);
    println!("WORKFLOW_COMPLETED={}", workflow_result.completed);
    println!("WORKFLOW_CANCELLED={}", workflow_result.cancelled);
    println!("WASM_COMPONENT={component}");
    println!("FILESYSTEM_CAPABILITY_OK=1");
    println!("PROCESS_AUTHORITY_OK=1");
    println!("SECRETS_CAPABILITY_OK=1");
    println!("MANAGED_CONFIG_OK=1");
    println!("MCP_PROJECTION_CONSTRUCTED=1");
    println!("CLEAN_BASELINE_OK");
    Ok(())
}
