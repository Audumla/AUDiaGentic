use std::sync::Arc;

use async_trait::async_trait;
use audiagentic_capability_api_spike::{
    CapabilityError, CapabilityResult, ComponentProbe, Workflow, WorkflowRequest, WorkflowResult,
};

#[derive(Debug, Clone, Copy, Default)]
pub struct NoWorkflow;

#[async_trait]
impl Workflow for NoWorkflow {
    async fn run(&self, _request: WorkflowRequest) -> CapabilityResult<WorkflowResult> {
        Err(CapabilityError::unavailable("workflow"))
    }
}

#[derive(Debug, Clone, Copy, Default)]
pub struct NoComponentProbe;

#[async_trait]
impl ComponentProbe for NoComponentProbe {
    async fn probe(&self) -> CapabilityResult<String> {
        Err(CapabilityError::unavailable("component_probe"))
    }
}

#[derive(Clone)]
pub struct Application<W = NoWorkflow, C = NoComponentProbe> {
    workflow: W,
    component_probe: C,
}

pub type DynApplication = Application<Arc<dyn Workflow>, Arc<dyn ComponentProbe>>;

impl Default for Application<NoWorkflow, NoComponentProbe> {
    fn default() -> Self {
        Self::minimal()
    }
}

impl Application<NoWorkflow, NoComponentProbe> {
    pub fn minimal() -> Self {
        Self {
            workflow: NoWorkflow,
            component_probe: NoComponentProbe,
        }
    }
}

impl<W, C> Application<W, C> {
    pub fn with_workflow<NW>(self, workflow: NW) -> Application<NW, C> {
        Application {
            workflow,
            component_probe: self.component_probe,
        }
    }

    pub fn with_component_probe<NC>(self, component_probe: NC) -> Application<W, NC> {
        Application {
            workflow: self.workflow,
            component_probe,
        }
    }

    pub fn into_dyn(self) -> DynApplication
    where
        W: Workflow + 'static,
        C: ComponentProbe + 'static,
    {
        Application {
            workflow: Arc::new(self.workflow),
            component_probe: Arc::new(self.component_probe),
        }
    }
}

impl<W, C> Application<W, C>
where
    W: Workflow,
{
    pub async fn run_workflow(&self, request: WorkflowRequest) -> CapabilityResult<WorkflowResult> {
        self.workflow.run(request).await
    }
}

impl<W, C> Application<W, C>
where
    C: ComponentProbe,
{
    pub async fn probe_component(&self) -> CapabilityResult<String> {
        self.component_probe.probe().await
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use audiagentic_capability_api_spike::CapabilityErrorKind;

    #[derive(Clone)]
    struct FakeWorkflow(u32);

    #[async_trait]
    impl Workflow for FakeWorkflow {
        async fn run(&self, request: WorkflowRequest) -> CapabilityResult<WorkflowResult> {
            request.validate()?;
            Ok(WorkflowResult {
                runs: request.runs,
                completed: request.runs,
                cancelled: 0,
                retried: self.0,
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

    #[tokio::test]
    async fn minimal_application_reports_unavailable_capabilities() {
        let app = Application::minimal();
        let workflow = app
            .run_workflow(WorkflowRequest { runs: 1, steps: 1 })
            .await
            .unwrap_err();
        assert_eq!(workflow.kind(), CapabilityErrorKind::Unavailable);

        let component = app.probe_component().await.unwrap_err();
        assert_eq!(component.kind(), CapabilityErrorKind::Unavailable);
    }

    #[tokio::test]
    async fn typed_composition_delegates_and_can_be_erased_at_the_edge() {
        let app = Application::minimal()
            .with_workflow(FakeWorkflow(7))
            .with_component_probe(FakeProbe);

        let workflow = app
            .run_workflow(WorkflowRequest { runs: 3, steps: 2 })
            .await
            .unwrap();
        assert_eq!(workflow.completed, 3);
        assert_eq!(workflow.retried, 7);
        assert_eq!(app.probe_component().await.unwrap(), "fake:probe");

        let erased = app.into_dyn();
        assert_eq!(
            erased
                .run_workflow(WorkflowRequest { runs: 2, steps: 1 })
                .await
                .unwrap()
                .runs,
            2
        );
        assert_eq!(erased.probe_component().await.unwrap(), "fake:probe");
    }
}
