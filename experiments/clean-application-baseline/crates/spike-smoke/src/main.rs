use std::{env, sync::Arc};

use audiagentic_application_spike::Application;
use audiagentic_capability_api_spike::WorkflowRequest;
use audiagentic_component_host_spike::WasmComponentProbe;
use audiagentic_mcp_adapter_spike::McpApplication;
use audiagentic_runtime_bevy_spike::BevyWorkflow;

#[tokio::main]
async fn main() -> Result<(), String> {
    let minimal = Application::minimal();
    assert!(!minimal.has_workflow());
    assert!(!minimal.has_component_probe());
    assert!(minimal.run_workflow(WorkflowRequest { runs: 1, steps: 1 }).await.is_err());

    let wasm_smoke = env::var("AUDIAGENTIC_WASM_SMOKE_BIN")
        .map_err(|_| "AUDIAGENTIC_WASM_SMOKE_BIN is required".to_owned())?;

    let app = Application::minimal()
        .with_workflow(Arc::new(BevyWorkflow::spawn()?))
        .with_component_probe(Arc::new(WasmComponentProbe::new(wasm_smoke)));

    let workflow = app.run_workflow(WorkflowRequest { runs: 5_000, steps: 12 }).await?;
    if workflow.runs != 5_000 || workflow.completed + workflow.cancelled != 5_000 {
        return Err(format!("workflow result did not converge: {workflow:?}"));
    }

    let component = app.probe_component().await?;
    if component != "workflow-default:smoke" {
        return Err(format!("unexpected component provider: {component}"));
    }

    let _mcp_projection = McpApplication::new(app);

    println!("APPLICATION_MINIMAL_OK");
    println!("WORKFLOW_RUNS={}", workflow.runs);
    println!("WORKFLOW_COMPLETED={}", workflow.completed);
    println!("WORKFLOW_CANCELLED={}", workflow.cancelled);
    println!("WASM_COMPONENT={component}");
    println!("MCP_PROJECTION_CONSTRUCTED=1");
    println!("CLEAN_BASELINE_OK");
    Ok(())
}
