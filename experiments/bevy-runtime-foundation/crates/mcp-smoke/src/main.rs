use anyhow::{Context, Result, ensure};
use rmcp::{
    ClientInfo, ServiceExt,
    model::CallToolRequestParams,
    object,
    transport::{StreamableHttpClientTransport, TokioChildProcess},
};
use tokio::process::Command;

async fn exercise_stdio(server_path: &str) -> Result<()> {
    let client = ()
        .serve(TokioChildProcess::new(Command::new(server_path))?)
        .await
        .context("connect to stdio MCP server")?;

    let tools = client.list_all_tools().await?;
    ensure!(tools.iter().any(|tool| tool.name == "add"));
    ensure!(tools.iter().any(|tool| tool.name == "workflow_batch"));

    let add = client
        .call_tool(
            CallToolRequestParams::new("add")
                .with_arguments(object!({ "a": 20, "b": 22 })),
        )
        .await?;
    ensure!(add.is_error != Some(true), "stdio add failed: {add:?}");

    let workflow = client
        .call_tool(
            CallToolRequestParams::new("workflow_batch").with_arguments(object!({
                "runs": 5000,
                "steps": 12,
                "retry_every": 17,
                "cancel_every": 211
            })),
        )
        .await?;
    ensure!(
        workflow.is_error != Some(true),
        "stdio workflow failed: {workflow:?}"
    );

    println!("STDIO_TOOLS={}", tools.len());
    println!("STDIO_WORKFLOW={workflow:?}");
    client.cancel().await?;
    Ok(())
}

async fn exercise_http(uri: &str) -> Result<()> {
    let transport = StreamableHttpClientTransport::from_uri(uri);
    let client = ClientInfo::default()
        .serve(transport)
        .await
        .context("connect to HTTP MCP server")?;

    let tools = client.list_all_tools().await?;
    ensure!(tools.iter().any(|tool| tool.name == "add"));
    ensure!(tools.iter().any(|tool| tool.name == "workflow_batch"));

    let add = client
        .call_tool(
            CallToolRequestParams::new("add")
                .with_arguments(object!({ "a": 40, "b": 2 })),
        )
        .await?;
    ensure!(add.is_error != Some(true), "http add failed: {add:?}");

    let workflow = client
        .call_tool(
            CallToolRequestParams::new("workflow_batch").with_arguments(object!({
                "runs": 5000,
                "steps": 12,
                "retry_every": 17,
                "cancel_every": 211
            })),
        )
        .await?;
    ensure!(
        workflow.is_error != Some(true),
        "http workflow failed: {workflow:?}"
    );

    println!("HTTP_TOOLS={}", tools.len());
    println!("HTTP_WORKFLOW={workflow:?}");
    client.cancel().await?;
    Ok(())
}

#[tokio::main]
async fn main() -> Result<()> {
    let mut args = std::env::args().skip(1);
    let mode = args.next().context("usage: audiagentic-mcp-smoke <stdio|http> <target>")?;
    let target = args.next().context("missing target")?;

    match mode.as_str() {
        "stdio" => exercise_stdio(&target).await?,
        "http" => exercise_http(&target).await?,
        other => anyhow::bail!("unknown mode {other:?}"),
    }

    println!("MCP_{mode}_OK");
    Ok(())
}
