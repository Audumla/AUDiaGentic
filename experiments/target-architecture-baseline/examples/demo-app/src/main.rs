#![forbid(unsafe_code)]

use std::sync::Arc;

use audiagentic_application::Application;
use audiagentic_core::{
    ApplicationContext, ApplicationId, ApplicationInstanceId, ApplicationManifest,
};
use target_baseline_demo_capability::Greeting;

struct DemoState {
    greeting: Arc<dyn Greeting>,
}

struct PlainGreeting;

impl Greeting for PlainGreeting {
    fn greet(&self, name: &str) -> String {
        format!("hello {name}")
    }
}

fn main() {
    let application_id = ApplicationId::try_from("target-baseline-demo").expect("valid id");
    let manifest = Arc::new(ApplicationManifest::new(application_id.clone(), "0.1.0"));
    let context = ApplicationContext::new(
        application_id,
        ApplicationInstanceId::try_from("target-baseline-demo-1").expect("valid instance id"),
    );
    let application = Application::new(
        manifest,
        context,
        DemoState {
            greeting: Arc::new(PlainGreeting),
        },
    );

    assert_eq!(application.state().greeting.greet("world"), "hello world");
    println!("TARGET_BASELINE_OK");
}
