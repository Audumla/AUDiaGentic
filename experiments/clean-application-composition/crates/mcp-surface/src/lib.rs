use std::sync::Arc;

use audiagentic_clean_capabilities::{BatchSpec, Greeting, Workflow};
use rmcp::{handler::server::wrapper::Parameters, tool, tool_router};
use schemars::JsonSchema;
use serde::Deserialize;

#[derive(Debug, Deserialize, JsonSchema)]
pub struct GreetParams {
    pub name: String,
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
pub struct GreetingMcpServer {
    greeting: Arc<dyn Greeting>,
}

impl GreetingMcpServer {
    pub fn new(greeting: Arc<dyn Greeting>) -> Self {
        Self { greeting }
    }
}

#[tool_router(server_handler)]
impl GreetingMcpServer {
    #[tool(description = "Return a greeting through the selected greeting capability.")]
    async fn greet(&self, Parameters(params): Parameters<GreetParams>) -> String {
        self.greeting
            .greet(&params.name)
            .await
            .unwrap_or_else(|error| format!("capability error: {error}"))
    }
}

#[derive(Clone)]
pub struct MixedMcpServer {
    greeting: Arc<dyn Greeting>,
    workflow: Arc<dyn Workflow>,
}

impl MixedMcpServer {
    pub fn new(greeting: Arc<dyn Greeting>, workflow: Arc<dyn Workflow>) -> Self {
        Self { greeting, workflow }
    }
}

#[tool_router(server_handler)]
impl MixedMcpServer {
    #[tool(description = "Return a greeting through the selected greeting capability.")]
    async fn greet(&self, Parameters(params): Parameters<GreetParams>) -> String {
        self.greeting
            .greet(&params.name)
            .await
            .unwrap_or_else(|error| format!("capability error: {error}"))
    }

    #[tool(description = "Execute a synthetic workflow batch through the selected workflow capability.")]
    async fn workflow_batch(&self, Parameters(params): Parameters<WorkflowBatchParams>) -> String {
        let result = self
            .workflow
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
            Err(error) => format!("capability error: {error}"),
        }
    }
}
