use rmcp::{
    ServiceExt,
    model::{CallToolRequestParams, ClientInfo},
    object,
    transport::{StreamableHttpClientTransport, TokioChildProcess},
};
use tokio::process::Command;

fn require(value: bool, message: impl Into<String>) -> Result<(), Box<dyn std::error::Error>> {
    if value {
        Ok(())
    } else {
        Err(message.into().into())
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = std::env::args().skip(1);
    let mode = args.next().ok_or("missing smoke mode")?;
    let target = args.next().ok_or("missing target")?;

    match mode.as_str() {
        "minimal-stdio" => {
            let client = ().serve(TokioChildProcess::new(Command::new(&target))?).await?;
            let tools = client.list_all_tools().await?;
            require(
                tools.len() == 1 && tools[0].name == "greet",
                format!("unexpected minimal tools: {tools:?}"),
            )?;
            let reply = client
                .call_tool(
                    CallToolRequestParams::new("greet")
                        .with_arguments(object!({ "name": "Ada" })),
                )
                .await?;
            require(
                reply.is_error != Some(true),
                format!("minimal greet failed: {reply:?}"),
            )?;
            let greeting = format!("{reply:?}");
            require(greeting.contains("native:hello Ada"), greeting.clone())?;
            println!("MINIMAL_GREETING={greeting}");
            client.cancel().await?;
        }
        "mixed-stdio" => {
            let wasm = args.next().ok_or("missing wasm component path")?;
            let mut command = Command::new(&target);
            command.arg("stdio").arg(wasm);
            let client = ().serve(TokioChildProcess::new(command)?).await?;
            let tools = client.list_all_tools().await?;
            require(
                tools.iter().any(|tool| tool.name == "greet"),
                "mixed greet tool missing",
            )?;
            require(
                tools.iter().any(|tool| tool.name == "workflow_batch"),
                "mixed workflow tool missing",
            )?;

            let greet_reply = client
                .call_tool(
                    CallToolRequestParams::new("greet")
                        .with_arguments(object!({ "name": "Ada" })),
                )
                .await?;
            require(
                greet_reply.is_error != Some(true),
                format!("mixed stdio greet failed: {greet_reply:?}"),
            )?;
            let greeting = format!("{greet_reply:?}");
            require(greeting.contains("wasm:hello Ada"), greeting.clone())?;

            let workflow_reply = client
                .call_tool(
                    CallToolRequestParams::new("workflow_batch").with_arguments(object!({
                        "runs": 5000,
                        "steps": 12,
                        "retry_every": 17,
                        "cancel_every": 211
                    })),
                )
                .await?;
            require(
                workflow_reply.is_error != Some(true),
                format!("mixed stdio workflow failed: {workflow_reply:?}"),
            )?;
            let workflow = format!("{workflow_reply:?}");
            require(workflow.contains("\"runs\":5000"), workflow.clone())?;

            println!("MIXED_STDIO_GREETING={greeting}");
            println!("MIXED_STDIO_WORKFLOW={workflow}");
            client.cancel().await?;
        }
        "mixed-http" => {
            let transport = StreamableHttpClientTransport::from_uri(target);
            let client = ClientInfo::default().serve(transport).await?;
            let tools = client.list_all_tools().await?;
            require(
                tools.iter().any(|tool| tool.name == "greet"),
                "HTTP greet tool missing",
            )?;
            require(
                tools.iter().any(|tool| tool.name == "workflow_batch"),
                "HTTP workflow tool missing",
            )?;

            let greet_reply = client
                .call_tool(
                    CallToolRequestParams::new("greet")
                        .with_arguments(object!({ "name": "Ada" })),
                )
                .await?;
            require(
                greet_reply.is_error != Some(true),
                format!("mixed HTTP greet failed: {greet_reply:?}"),
            )?;
            let greeting = format!("{greet_reply:?}");
            require(greeting.contains("wasm:hello Ada"), greeting.clone())?;

            let workflow_reply = client
                .call_tool(
                    CallToolRequestParams::new("workflow_batch").with_arguments(object!({
                        "runs": 5000,
                        "steps": 12,
                        "retry_every": 17,
                        "cancel_every": 211
                    })),
                )
                .await?;
            require(
                workflow_reply.is_error != Some(true),
                format!("mixed HTTP workflow failed: {workflow_reply:?}"),
            )?;
            let workflow = format!("{workflow_reply:?}");
            require(workflow.contains("\"runs\":5000"), workflow.clone())?;

            println!("MIXED_HTTP_GREETING={greeting}");
            println!("MIXED_HTTP_WORKFLOW={workflow}");
            client.cancel().await?;
        }
        other => return Err(format!("unknown smoke mode {other:?}").into()),
    }

    println!("SMOKE_{mode}_OK");
    Ok(())
}
