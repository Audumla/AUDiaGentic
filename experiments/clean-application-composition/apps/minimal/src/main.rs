use std::sync::Arc;

use audiagentic_clean_capabilities::Greeting;
use audiagentic_clean_mcp_surface::GreetingMcpServer;
use audiagentic_clean_native_greeter::NativeGreeter;
use rmcp::{ServiceExt, transport::stdio};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let greeting: Arc<dyn Greeting> = Arc::new(NativeGreeter);
    let service = GreetingMcpServer::new(greeting).serve(stdio()).await?;
    service.waiting().await?;
    Ok(())
}
