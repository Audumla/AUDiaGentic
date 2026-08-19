use audiagentic_application_spike::Application;
use audiagentic_capability_api_spike::WorkflowRequest;
use rmcp::{handler::server::wrapper::Parameters, tool, tool_router};
use schemars::JsonSchema;
use serde::Deserialize;

#[derive(Debug, Deserialize, JsonSchema)]
pub struct WorkflowParams {
    pub runs: u32,
    pub steps: u16,
}

#[derive(Clone)]
pub struct McpApplication {
    app: Application,
}

impl McpApplication {
    pub fn new(app: Application) -> Self {
        Self { app }
    }
}

#[tool_router(server_handler)]
impl McpApplication {
    #[tool(description = "Run the configured workflow capability.")]
    async fn workflow(&self, Parameters(params): Parameters<WorkflowParams>) -> String {
        match self.app.run_workflow(WorkflowRequest { runs: params.runs, steps: params.steps }).await {
            Ok(result) => serde_json::to_string(&result)
                .unwrap_or_else(|error| format!("serialization error: {error}")),
            Err(error) => format!("workflow error: {error}"),
        }
    }

    #[tool(description = "Probe the configured runtime-loaded component capability.")]
    async fn component_probe(&self) -> String {
        self.app.probe_component().await.unwrap_or_else(|error| format!("component error: {error}"))
    }
}
