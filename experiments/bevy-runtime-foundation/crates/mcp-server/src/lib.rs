use audiagentic_bevy_runtime_spike::{BatchSpec, WorkflowRuntimeHandle};
use rmcp::{handler::server::wrapper::Parameters, tool, tool_router};
use schemars::JsonSchema;
use serde::Deserialize;

#[derive(Debug, Deserialize, JsonSchema)]
pub struct AddParams {
    pub a: i64,
    pub b: i64,
}

#[derive(Debug, Deserialize, JsonSchema)]
pub struct WorkflowBatchParams {
    pub runs: u32,
    pub steps: u16,
    #[serde(default)]
    pub retry_every: Option<u32>,
    #[serde(default)]
    pub cancel_every: Option<u32>,
}

#[derive(Clone)]
pub struct AudiagenticMcpServer {
    runtime: WorkflowRuntimeHandle,
}

impl AudiagenticMcpServer {
    pub fn new(runtime: WorkflowRuntimeHandle) -> Self {
        Self { runtime }
    }
}

#[tool_router(server_handler)]
impl AudiagenticMcpServer {
    #[tool(description = "Add two integers. This is intentionally a simple tool that does not use Bevy.")]
    fn add(&self, Parameters(AddParams { a, b }): Parameters<AddParams>) -> String {
        (a + b).to_string()
    }

    #[tool(description = "Run a batch of workflow instances through the Bevy ECS runtime and return execution metrics.")]
    async fn workflow_batch(
        &self,
        Parameters(params): Parameters<WorkflowBatchParams>,
    ) -> String {
        let result = self
            .runtime
            .run_batch(BatchSpec {
                runs: params.runs,
                steps: params.steps,
                retry_every: params.retry_every.unwrap_or(17),
                cancel_every: params.cancel_every.unwrap_or(0),
            })
            .await;

        match result {
            Ok(result) => serde_json::to_string(&result)
                .unwrap_or_else(|error| format!("serialization error: {error}")),
            Err(error) => format!("runtime error: {error:#}"),
        }
    }
}
