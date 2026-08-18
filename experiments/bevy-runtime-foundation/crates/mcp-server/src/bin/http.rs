use std::net::SocketAddr;

use audiagentic_bevy_mcp_spike::AudiagenticMcpServer;
use audiagentic_bevy_runtime_spike::WorkflowRuntimeHandle;
use rmcp::transport::streamable_http_server::{
    StreamableHttpServerConfig, StreamableHttpService, session::local::LocalSessionManager,
};
use tokio_util::sync::CancellationToken;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "info".into()),
        )
        .init();

    let runtime = WorkflowRuntimeHandle::spawn()?;
    let cancellation = CancellationToken::new();
    let config = StreamableHttpServerConfig::default()
        .with_legacy_session_mode(false)
        .with_json_response(true)
        .with_cancellation_token(cancellation.child_token());

    let service = StreamableHttpService::new(
        {
            let runtime = runtime.clone();
            move || Ok(AudiagenticMcpServer::new(runtime.clone()))
        },
        LocalSessionManager::default().into(),
        config,
    );

    let router = axum::Router::new().nest_service("/mcp", service);
    let addr = std::env::var("AUDIAGENTIC_MCP_BIND")
        .unwrap_or_else(|_| "127.0.0.1:18080".to_owned())
        .parse::<SocketAddr>()?;
    let listener = tokio::net::TcpListener::bind(addr).await?;
    eprintln!("MCP_HTTP_READY=http://{addr}/mcp");

    axum::serve(listener, router)
        .with_graceful_shutdown(async move {
            let _ = tokio::signal::ctrl_c().await;
            cancellation.cancel();
        })
        .await?;

    Ok(())
}
