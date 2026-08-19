use async_trait::async_trait;
use audiagentic_clean_capabilities::{CapabilityResult, Greeting};

#[derive(Debug, Default)]
pub struct NativeGreeter;

#[async_trait]
impl Greeting for NativeGreeter {
    async fn greet(&self, name: &str) -> CapabilityResult<String> {
        Ok(format!("native:hello {name}"))
    }
}
