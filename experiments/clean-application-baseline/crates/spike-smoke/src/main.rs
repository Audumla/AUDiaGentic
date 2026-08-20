use std::{env, error::Error, time::Duration};

use audiagentic_application_spike::{Application, DynApplication};
use audiagentic_capability_api_spike::{CapabilityErrorKind, WorkflowRequest};
use audiagentic_component_host_spike::WasmComponentProbe;
use audiagentic_mcp_adapter_spike::McpApplication;
use audiagentic_runtime_bevy_spike::BevyWorkflow;
use rmcp::{ServiceExt, model::CallToolRequestParams, object};

async fn exercise_mcp(app: DynApplication) -> Result<(), Box<dyn Error>> {
    let (server_transport, client_transport) = tokio::io::duplex(16 * 1024);
    let server_task = tokio::spawn(async move {
        let service = McpApplication::new(app)
            .serve(server_transport)
            .await
            .expect("start in-memory MCP server");
        service
            .waiting()
            .await
            .expect("wait for in-memory MCP server");
    });
    let client = ().serve(client_transport).await?;

    let tools = client.list_all_tools().await?;
    if !tools.iter().any(|tool| tool.name == "workflow")
        || !tools.iter().any(|tool| tool.name == "component_probe")
    {
        return Err("MCP projection did not expose expected tools".into());
    }

    let workflow = client
        .call_tool(
            CallToolRequestParams::new("workflow")
                .with_arguments(object!({ "runs": 128, "steps": 12 })),
        )
        .await?;
    if workflow.is_error == Some(true) {
        return Err(format!("MCP workflow call failed: {workflow:?}").into());
    }

    let component = client
        .call_tool(CallToolRequestParams::new("component_probe"))
        .await?;
    if component.is_error == Some(true) {
        return Err(format!("MCP component probe failed: {component:?}").into());
    }

    client.cancel().await?;
    tokio::time::timeout(Duration::from_secs(2), server_task).await??;
    println!("MCP_E2E_OK");
    Ok(())
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn Error>> {
    let minimal = Application::minimal();
    let unavailable = minimal
        .run_workflow(WorkflowRequest { runs: 1, steps: 1 })
        .await
        .unwrap_err();
    if unavailable.kind() != CapabilityErrorKind::Unavailable {
        return Err(format!("unexpected minimal workflow error: {unavailable}").into());
    }

    let wasm_smoke = env::var("AUDIAGENTIC_WASM_SMOKE_BIN")?;
    let workflow = BevyWorkflow::spawn()?;
    let shutdown = workflow.clone();
    let app = Application::minimal()
        .with_workflow(workflow)
        .with_component_probe(WasmComponentProbe::new(wasm_smoke));

    let result = app
        .run_workflow(WorkflowRequest {
            runs: 5_000,
            steps: 12,
        })
        .await?;
    if result.runs != 5_000 || result.completed + result.cancelled != 5_000 {
        return Err(format!("workflow result did not converge: {result:?}").into());
    }

    let component = app.probe_component().await?;
    if component != "workflow-default:smoke" {
        return Err(format!("unexpected component provider: {component}").into());
    }

    exercise_mcp(app.into_dyn()).await?;
    shutdown.shutdown().await?;

    println!("APPLICATION_MINIMAL_OK");
    println!("WORKFLOW_RUNS={}", result.runs);
    println!("WORKFLOW_COMPLETED={}", result.completed);
    println!("WORKFLOW_CANCELLED={}", result.cancelled);
    println!("WASM_COMPONENT={component}");
    println!("CLEAN_BASELINE_OK");
    Ok(())
}
