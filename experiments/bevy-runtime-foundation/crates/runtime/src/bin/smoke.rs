use audiagentic_bevy_runtime_spike::{BatchSpec, WorkflowRuntimeHandle};

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let runtime = WorkflowRuntimeHandle::spawn()?;
    let result = runtime
        .run_batch(BatchSpec {
            runs: 50_000,
            steps: 16,
            retry_every: 17,
            cancel_every: 997,
        })
        .await?;

    anyhow::ensure!(result.completed + result.cancelled == result.runs);
    anyhow::ensure!(result.retried > 0);
    anyhow::ensure!(result.cancelled > 0);

    println!("BEVY_RUNS={}", result.runs);
    println!("BEVY_COMPLETED={}", result.completed);
    println!("BEVY_CANCELLED={}", result.cancelled);
    println!("BEVY_RETRIED={}", result.retried);
    println!("BEVY_TICKS={}", result.ticks);
    println!("BEVY_ELAPSED_US={}", result.elapsed_micros);
    println!("BEVY_RUNTIME_OK");
    Ok(())
}
