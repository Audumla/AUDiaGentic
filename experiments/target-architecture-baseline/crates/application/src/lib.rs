#![forbid(unsafe_code)]

use std::sync::Arc;

use audiagentic_core::{ApplicationContext, ApplicationManifest};

/// Generic application shell.
///
/// `S` is defined by the concrete application. The base runtime never stores a
/// type-indexed service registry and never needs to know which capabilities an
/// application selected.
pub struct Application<S> {
    manifest: Arc<ApplicationManifest>,
    context: ApplicationContext,
    state: S,
}

impl<S> Application<S> {
    pub fn new(manifest: Arc<ApplicationManifest>, context: ApplicationContext, state: S) -> Self {
        debug_assert_eq!(manifest.id, context.application_id);
        Self {
            manifest,
            context,
            state,
        }
    }

    pub fn manifest(&self) -> &ApplicationManifest {
        self.manifest.as_ref()
    }

    pub fn context(&self) -> &ApplicationContext {
        &self.context
    }

    pub fn state(&self) -> &S {
        &self.state
    }

    pub fn state_mut(&mut self) -> &mut S {
        &mut self.state
    }

    pub fn into_state(self) -> S {
        self.state
    }
}

impl<S: Clone> Clone for Application<S> {
    fn clone(&self) -> Self {
        Self {
            manifest: Arc::clone(&self.manifest),
            context: self.context.clone(),
            state: self.state.clone(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use audiagentic_core::{ApplicationId, ApplicationInstanceId};

    #[derive(Clone, Debug, Eq, PartialEq)]
    struct State {
        value: u32,
    }

    #[test]
    fn application_is_only_manifest_context_and_typed_state() {
        let application_id = ApplicationId::try_from("demo").unwrap();
        let manifest = Arc::new(ApplicationManifest::new(application_id.clone(), "1"));
        let context = ApplicationContext::new(
            application_id,
            ApplicationInstanceId::try_from("demo-1").unwrap(),
        );
        let application = Application::new(manifest, context, State { value: 7 });

        assert_eq!(application.state().value, 7);
        assert_eq!(application.manifest().id.as_str(), "demo");
    }
}
