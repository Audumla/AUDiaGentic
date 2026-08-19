use std::{net::SocketAddr, path::PathBuf, sync::Arc};

use audiagentic_clean_capabilities::{Greeting, Workflow};
use audiagentic_clean_mcp_surface::MixedMcpServer;
use audiagentic_clean_wasm_greeter::WasmGreeter;
use audiagentic_clean_workflow_bevy::BevyWorkflow;
use rmcp::{
    ServiceExt,
    transport::{
        stdio,
        streamable_http_server::{
            StreamableHttpServerConfig, StreamableHttpService, session::local::LocalSessionManager,
        },
    },
};
use tokio_util::sync::CancellationToken;

fn compose(wasm_path: PathBuf) -> Result<MixedMcpServer, Box<dyn std::error::Error>> {
    let greeting: Arc<dyn Greeting> = Arc::new(WasmGreeter::load(wasm_path)?);
    let workflow: Arc<dyn Workflow> = Arc::new(BevyWorkflow::spawn()?);
    Ok(MixedMcpServer::new(greeting, workflow))
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = std::env::args().skip(1);
    let mode = args.next().unwrap_or_else(|| "stdio".to_owned());
    let wasm_path = PathBuf::from(args.next().ok_or("missing greeter component path")?);
    let server = compose(wasm_path)?;

    match mode.as_str() {
        "stdio" => {
            let service = server.serve(stdio()).await?;
            service.waiting().await?;
        }
        "http" => {
            let cancellation = CancellationToken::new();
            let config = StreamableHttpServerConfig::default()
                .with_legacy_session_mode(false)
                .with_json_response(true)
                .with_cancellation_token(cancellation.child_token());
            let service = StreamableHttpService::new(
                move || Ok(server.clone()),
                LocalSessionManager::default().into(),
                config,
            );
            let router = axum::Router::new().nest_service("/mcp", service);
            let addr = std::env::var("AUDIAGENTIC_MCP_BIND")
                .unwrap_or_else(|_| "127.0.0.1:18081".to_owned())
                .parse::<SocketAddr>()?;
            let listener = tokio::net::TcpListener::bind(addr).await?;
            eprintln!("MCP_HTTP_READY=http://{addr}/mcp");
            axum::serve(listener, router).await?;
        }
        other => return Err(format!("unknown mode {other:?}").into()),
    }
    Ok(())
}
