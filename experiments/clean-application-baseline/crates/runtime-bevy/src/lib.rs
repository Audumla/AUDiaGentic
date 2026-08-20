use async_trait::async_trait;
use audiagentic_bevy_runtime_spike::{BatchSpec, WorkflowRuntimeHandle};
use audiagentic_capability_api_spike::{
    CapabilityError, CapabilityResult, Workflow, WorkflowRequest, WorkflowResult,
};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct WorkflowLimits {
    pub max_runs: u32,
    pub max_steps: u16,
}

impl Default for WorkflowLimits {
    fn default() -> Self {
        Self {
            max_runs: 100_000,
            max_steps: 10_000,
        }
    }
}

#[derive(Clone)]
pub struct BevyWorkflow {
    runtime: WorkflowRuntimeHandle,
    limits: WorkflowLimits,
}

impl BevyWorkflow {
    pub fn spawn() -> CapabilityResult<Self> {
        Self::spawn_with_limits(WorkflowLimits::default())
    }

    pub fn spawn_with_limits(limits: WorkflowLimits) -> CapabilityResult<Self> {
        Ok(Self {
            runtime: WorkflowRuntimeHandle::spawn().map_err(|error| {
                CapabilityError::execution("workflow", format!("spawn Bevy runtime: {error:#}"))
            })?,
            limits,
        })
    }

    pub async fn shutdown(&self) -> CapabilityResult<()> {
        self.runtime.shutdown().await.map_err(|error| {
            CapabilityError::execution("workflow", format!("shutdown Bevy runtime: {error:#}"))
        })
    }

    fn validate_limits(&self, request: WorkflowRequest) -> CapabilityResult<()> {
        request.validate()?;
        if request.runs > self.limits.max_runs {
            return Err(CapabilityError::invalid_request(
                "workflow",
                format!(
                    "runs {} exceeds configured maximum {}",
                    request.runs, self.limits.max_runs
                ),
            ));
        }
        if request.steps > self.limits.max_steps {
            return Err(CapabilityError::invalid_request(
                "workflow",
                format!(
                    "steps {} exceeds configured maximum {}",
                    request.steps, self.limits.max_steps
                ),
            ));
        }
        Ok(())
    }
}

#[async_trait]
impl Workflow for BevyWorkflow {
    async fn run(&self, request: WorkflowRequest) -> CapabilityResult<WorkflowResult> {
        self.validate_limits(request)?;
        let result = self
            .runtime
            .run_batch(BatchSpec {
                runs: request.runs,
                steps: request.steps,
                retry_every: 17,
                cancel_every: 211,
            })
            .await
            .map_err(|error| {
                CapabilityError::execution("workflow", format!("Bevy batch failed: {error:#}"))
            })?;

        Ok(WorkflowResult {
            runs: result.runs,
            completed: result.completed,
            cancelled: result.cancelled,
            retried: result.retried,
            ticks: result.ticks,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use audiagentic_capability_api_spike::CapabilityErrorKind;

    #[tokio::test]
    async fn rejects_requests_outside_configured_budget() {
        let workflow = BevyWorkflow::spawn_with_limits(WorkflowLimits {
            max_runs: 10,
            max_steps: 20,
        })
        .unwrap();

        let too_many_runs = workflow
            .run(WorkflowRequest { runs: 11, steps: 1 })
            .await
            .unwrap_err();
        assert_eq!(too_many_runs.kind(), CapabilityErrorKind::InvalidRequest);

        let too_many_steps = workflow
            .run(WorkflowRequest { runs: 1, steps: 21 })
            .await
            .unwrap_err();
        assert_eq!(too_many_steps.kind(), CapabilityErrorKind::InvalidRequest);

        workflow.shutdown().await.unwrap();
    }

    #[tokio::test]
    async fn executes_and_shuts_down_cleanly() {
        let workflow = BevyWorkflow::spawn().unwrap();
        let result = workflow
            .run(WorkflowRequest {
                runs: 1_000,
                steps: 12,
            })
            .await
            .unwrap();
        assert_eq!(result.completed + result.cancelled, 1_000);
        workflow.shutdown().await.unwrap();
    }
}
