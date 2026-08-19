use async_trait::async_trait;
use audiagentic_bevy_runtime_spike::{BatchSpec, WorkflowRuntimeHandle};
use audiagentic_capability_api_spike::{Workflow, WorkflowRequest, WorkflowResult};

pub struct BevyWorkflow {
    runtime: WorkflowRuntimeHandle,
}

impl BevyWorkflow {
    pub fn spawn() -> Result<Self, String> {
        Ok(Self { runtime: WorkflowRuntimeHandle::spawn().map_err(|e| e.to_string())? })
    }
}

#[async_trait]
impl Workflow for BevyWorkflow {
    async fn run(&self, request: WorkflowRequest) -> Result<WorkflowResult, String> {
        let result = self.runtime.run_batch(BatchSpec {
            runs: request.runs,
            steps: request.steps,
            retry_every: 17,
            cancel_every: 211,
        }).await.map_err(|e| e.to_string())?;

        Ok(WorkflowResult {
            runs: result.runs,
            completed: result.completed,
            cancelled: result.cancelled,
            retried: result.retried,
            ticks: result.ticks,
        })
    }
}
