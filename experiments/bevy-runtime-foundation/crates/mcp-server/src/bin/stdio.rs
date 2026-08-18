use audiagentic_bevy_mcp_spike::AudiagenticMcpServer;
use audiagentic_bevy_runtime_spike::WorkflowRuntimeHandle;
use rmcp::{ServiceExt, transport::stdio};

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "info".into()),
        )
        .with_writer(std::io::stderr)
        .init();

    let runtime = WorkflowRuntimeHandle::spawn()?;
    let service = AudiagenticMcpServer::new(runtime).serve(stdio()).await?;
    service.waiting().await?;
    Ok(())
}
