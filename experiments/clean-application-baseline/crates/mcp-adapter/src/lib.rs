use audiagentic_application_spike::DynApplication;
use audiagentic_capability_api_spike::{CapabilityError, CapabilityErrorKind, WorkflowRequest};
use rmcp::{ErrorData, handler::server::wrapper::Parameters, tool, tool_router};
use schemars::JsonSchema;
use serde::Deserialize;

#[derive(Debug, Deserialize, JsonSchema)]
pub struct WorkflowParams {
    pub runs: u32,
    pub steps: u16,
}

#[derive(Clone)]
pub struct McpApplication {
    app: DynApplication,
}

impl McpApplication {
    pub fn new(app: DynApplication) -> Self {
        Self { app }
    }
}

fn map_capability_error(error: CapabilityError) -> ErrorData {
    match error.kind() {
        CapabilityErrorKind::InvalidRequest => ErrorData::invalid_params(error.to_string(), None),
        CapabilityErrorKind::Unavailable
        | CapabilityErrorKind::Execution
        | CapabilityErrorKind::Timeout => ErrorData::internal_error(error.to_string(), None),
    }
}

#[tool_router(server_handler)]
impl McpApplication {
    #[tool(description = "Run the configured workflow capability.")]
    async fn workflow(
        &self,
        Parameters(params): Parameters<WorkflowParams>,
    ) -> Result<String, ErrorData> {
        let result = self
            .app
            .run_workflow(WorkflowRequest {
                runs: params.runs,
                steps: params.steps,
            })
            .await
            .map_err(map_capability_error)?;
        serde_json::to_string(&result)
            .map_err(|error| ErrorData::internal_error(error.to_string(), None))
    }

    #[tool(description = "Probe the configured runtime-loaded component capability.")]
    async fn component_probe(&self) -> Result<String, ErrorData> {
        self.app
            .probe_component()
            .await
            .map_err(map_capability_error)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use async_trait::async_trait;
    use audiagentic_application_spike::Application;
    use audiagentic_capability_api_spike::{
        CapabilityError, CapabilityResult, ComponentProbe, Workflow, WorkflowResult,
    };
    use rmcp::{ServiceExt, model::CallToolRequestParams, object};
    use std::time::Duration;

    #[derive(Clone)]
    struct FakeWorkflow;

    #[async_trait]
    impl Workflow for FakeWorkflow {
        async fn run(&self, request: WorkflowRequest) -> CapabilityResult<WorkflowResult> {
            request.validate()?;
            Ok(WorkflowResult {
                runs: request.runs,
                completed: request.runs,
                cancelled: 0,
                retried: 0,
                ticks: 1,
            })
        }
    }

    #[derive(Clone)]
    struct FakeProbe;

    #[async_trait]
    impl ComponentProbe for FakeProbe {
        async fn probe(&self) -> CapabilityResult<String> {
            Ok("fake:probe".to_owned())
        }
    }

    #[test]
    fn invalid_requests_map_to_protocol_invalid_params() {
        let error =
            map_capability_error(CapabilityError::invalid_request("workflow", "bad request"));
        assert_eq!(error.code, rmcp::model::ErrorCode::INVALID_PARAMS);
    }

    #[tokio::test]
    async fn serves_real_mcp_calls_over_in_memory_transport() {
        let app = Application::minimal()
            .with_workflow(FakeWorkflow)
            .with_component_probe(FakeProbe)
            .into_dyn();
        let server = McpApplication::new(app);
        let (server_transport, client_transport) = tokio::io::duplex(8 * 1024);

        let server_task = tokio::spawn(async move {
            let service = server.serve(server_transport).await.unwrap();
            service.waiting().await.unwrap();
        });
        let client = ().serve(client_transport).await.unwrap();

        let tools = client.list_all_tools().await.unwrap();
        assert!(tools.iter().any(|tool| tool.name == "workflow"));
        assert!(tools.iter().any(|tool| tool.name == "component_probe"));

        let workflow = client
            .call_tool(
                CallToolRequestParams::new("workflow")
                    .with_arguments(object!({ "runs": 8, "steps": 2 })),
            )
            .await
            .unwrap();
        assert_ne!(workflow.is_error, Some(true));

        let component = client
            .call_tool(CallToolRequestParams::new("component_probe"))
            .await
            .unwrap();
        assert_ne!(component.is_error, Some(true));

        client.cancel().await.unwrap();
        tokio::time::timeout(Duration::from_secs(2), server_task)
            .await
            .unwrap()
            .unwrap();
    }
}
