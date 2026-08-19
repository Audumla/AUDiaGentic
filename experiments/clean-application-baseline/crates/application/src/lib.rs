use std::sync::Arc;

use audiagentic_capability_api_spike::{ComponentProbe, Workflow, WorkflowRequest, WorkflowResult};

#[derive(Clone)]
pub struct Application {
    workflow: Option<Arc<dyn Workflow>>,
    component_probe: Option<Arc<dyn ComponentProbe>>,
}

impl Application {
    pub fn minimal() -> Self {
        Self { workflow: None, component_probe: None }
    }

    pub fn with_workflow(mut self, workflow: Arc<dyn Workflow>) -> Self {
        self.workflow = Some(workflow);
        self
    }

    pub fn with_component_probe(mut self, probe: Arc<dyn ComponentProbe>) -> Self {
        self.component_probe = Some(probe);
        self
    }

    pub fn has_workflow(&self) -> bool { self.workflow.is_some() }
    pub fn has_component_probe(&self) -> bool { self.component_probe.is_some() }

    pub async fn run_workflow(&self, request: WorkflowRequest) -> Result<WorkflowResult, String> {
        let workflow = self.workflow.as_ref().ok_or_else(|| "workflow capability is not configured".to_owned())?;
        workflow.run(request).await
    }

    pub async fn probe_component(&self) -> Result<String, String> {
        let probe = self.component_probe.as_ref().ok_or_else(|| "component probe capability is not configured".to_owned())?;
        probe.probe().await
    }
}
