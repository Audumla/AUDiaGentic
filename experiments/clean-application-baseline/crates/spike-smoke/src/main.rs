use std::{env, fs, sync::Arc};

use audiagentic_application_spike::Application;
use audiagentic_capability_api_spike::{ComponentProbe, Workflow, WorkflowRequest};
use audiagentic_component_host_spike::WasmComponentProbe;
use audiagentic_filesystem_api_spike::{FileSystem, RelativePath};
use audiagentic_filesystem_native_spike::NativeFileSystem;
use audiagentic_kernel_core_spike::{ApplicationContext, ApplicationId};
use audiagentic_mcp_adapter_spike::McpApplication;
use audiagentic_runtime_bevy_spike::BevyWorkflow;

#[derive(Clone)]
struct SpikeCapabilities {
    workflow: Arc<dyn Workflow>,
    component_probe: Arc<dyn ComponentProbe>,
    filesystem: Arc<dyn FileSystem>,
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

    let app = Application::new(
        ApplicationContext::new(ApplicationId::new("composed.app").map_err(|e| e.to_string())?),
        SpikeCapabilities {
            workflow: workflow.clone(),
            component_probe: component_probe.clone(),
            filesystem: filesystem.clone(),
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

    let _mcp_projection = McpApplication::new(workflow, component_probe);

    let _ = fs::remove_dir_all(&root);
    println!("APPLICATION_GENERIC_CORE_OK");
    println!("WORKFLOW_RUNS={}", workflow_result.runs);
    println!("WORKFLOW_COMPLETED={}", workflow_result.completed);
    println!("WORKFLOW_CANCELLED={}", workflow_result.cancelled);
    println!("WASM_COMPONENT={component}");
    println!("FILESYSTEM_CAPABILITY_OK=1");
    println!("MCP_PROJECTION_CONSTRUCTED=1");
    println!("CLEAN_BASELINE_OK");
    Ok(())
}
