use std::{fmt, sync::Arc};

use audiagentic_capability_api_spike::{
    ComponentProbe, ComponentProbeError, Workflow, WorkflowError, WorkflowRequest, WorkflowResult,
};
use audiagentic_core_spike::{
    ApplicationContext, ApplicationId, ApplicationInstanceId, CapabilityId,
};

#[derive(Debug)]
pub enum ApplicationError {
    MissingCapability(CapabilityId),
    Workflow(WorkflowError),
    ComponentProbe(ComponentProbeError),
}

impl fmt::Display for ApplicationError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::MissingCapability(id) => write!(f, "capability is not configured: {id}"),
            Self::Workflow(error) => error.fmt(f),
            Self::ComponentProbe(error) => error.fmt(f),
        }
    }
}

impl std::error::Error for ApplicationError {}

#[derive(Clone)]
pub struct Application {
    context: ApplicationContext,
    workflow: Option<Arc<dyn Workflow>>,
    component_probe: Option<Arc<dyn ComponentProbe>>,
}

impl Application {
    pub fn new(context: ApplicationContext) -> Self {
        Self {
            context,
            workflow: None,
            component_probe: None,
        }
    }

    pub fn minimal() -> Self {
        Self::new(ApplicationContext {
            application: ApplicationId::new("baseline").expect("static application id"),
            instance: ApplicationInstanceId::new("baseline/local").expect("static instance id"),
            correlation: None,
        })
    }

    pub fn context(&self) -> &ApplicationContext {
        &self.context
    }

    pub fn with_workflow(mut self, workflow: Arc<dyn Workflow>) -> Self {
        self.workflow = Some(workflow);
        self
    }

    pub fn with_component_probe(mut self, probe: Arc<dyn ComponentProbe>) -> Self {
        self.component_probe = Some(probe);
        self
    }

    pub fn has_workflow(&self) -> bool {
        self.workflow.is_some()
    }

    pub fn has_component_probe(&self) -> bool {
        self.component_probe.is_some()
    }

    pub async fn run_workflow(
        &self,
        request: WorkflowRequest,
    ) -> Result<WorkflowResult, ApplicationError> {
        let workflow = self.workflow.as_ref().ok_or_else(|| {
            ApplicationError::MissingCapability(
                CapabilityId::new("workflow.execute").expect("static capability id"),
            )
        })?;
        workflow
            .run(request)
            .await
            .map_err(ApplicationError::Workflow)
    }

    pub async fn probe_component(&self) -> Result<String, ApplicationError> {
        let probe = self.component_probe.as_ref().ok_or_else(|| {
            ApplicationError::MissingCapability(
                CapabilityId::new("component.probe").expect("static capability id"),
            )
        })?;
        probe
            .probe()
            .await
            .map_err(ApplicationError::ComponentProbe)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn minimal_application_fails_missing_capability_explicitly() {
        let app = Application::minimal();
        let error = app
            .run_workflow(WorkflowRequest { runs: 1, steps: 1 })
            .await
            .unwrap_err();
        assert!(matches!(error, ApplicationError::MissingCapability(_)));
    }
}
