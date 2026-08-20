use audiagentic_kernel_core_spike::ApplicationContext;

#[derive(Clone, Debug)]
pub struct Application<C> {
    context: ApplicationContext,
    capabilities: C,
}

impl<C> Application<C> {
    pub fn new(context: ApplicationContext, capabilities: C) -> Self {
        Self {
            context,
            capabilities,
        }
    }

    pub fn context(&self) -> &ApplicationContext {
        &self.context
    }

    pub fn capabilities(&self) -> &C {
        &self.capabilities
    }

    pub fn into_parts(self) -> (ApplicationContext, C) {
        (self.context, self.capabilities)
    }
}

#[cfg(test)]
mod tests {
    use audiagentic_kernel_core_spike::ApplicationId;

    use super::*;

    #[derive(Clone, Debug, PartialEq, Eq)]
    struct ExampleCapabilities {
        value: u32,
    }

    #[test]
    fn application_is_generic_over_app_owned_capabilities() {
        let app = Application::new(
            ApplicationContext::new(ApplicationId::new("example.app").unwrap()),
            ExampleCapabilities { value: 42 },
        );

        assert_eq!(app.context().application.as_str(), "example.app");
        assert_eq!(app.capabilities().value, 42);
    }
}
