use std::{thread, time::Instant};

use anyhow::{Context, Result, bail};
use bevy_app::{App, Plugin, Update};
use bevy_ecs::{prelude::*, schedule::IntoScheduleConfigs};
use serde::Serialize;
use tokio::sync::{mpsc, oneshot};

#[derive(Debug, Clone, Copy)]
pub struct BatchSpec {
    pub runs: u32,
    pub steps: u16,
    pub retry_every: u32,
    pub cancel_every: u32,
}

#[derive(Debug, Clone, Serialize)]
pub struct BatchResult {
    pub runs: u32,
    pub completed: u32,
    pub cancelled: u32,
    pub retried: u32,
    pub ticks: u64,
    pub elapsed_micros: u128,
}

#[derive(Component, Debug)]
struct WorkflowRun {
    remaining: u16,
    retry_at: u16,
    retry_budget: u8,
    retries: u8,
    tick: u16,
    cancel_on_tick: Option<u16>,
    state: RunState,
}

#[derive(Debug, Clone, Copy, Eq, PartialEq)]
enum RunState {
    Ready,
    Running,
    Retrying,
    Completed,
    Cancelled,
}

#[derive(Message, Debug, Clone, Copy)]
struct RunFinished {
    cancelled: bool,
    retries: u8,
}

#[derive(Resource, Debug, Default, Clone)]
struct RuntimeStats {
    completed: u64,
    cancelled: u64,
    retried: u64,
}

pub struct WorkflowPlugin;

impl Plugin for WorkflowPlugin {
    fn build(&self, app: &mut App) {
        app.add_message::<RunFinished>()
            .add_systems(Update, advance_runs);
    }
}

pub struct MetricsPlugin;

impl Plugin for MetricsPlugin {
    fn build(&self, app: &mut App) {
        app.init_resource::<RuntimeStats>()
            .add_systems(Update, collect_finished.after(advance_runs));
    }
}

fn advance_runs(mut runs: Query<&mut WorkflowRun>, mut finished: MessageWriter<RunFinished>) {
    for mut run in &mut runs {
        match run.state {
            RunState::Ready => run.state = RunState::Running,
            RunState::Running => {
                run.tick = run.tick.saturating_add(1);

                if run.cancel_on_tick == Some(run.tick) {
                    run.state = RunState::Cancelled;
                    finished.write(RunFinished {
                        cancelled: true,
                        retries: run.retries,
                    });
                    continue;
                }

                if run.retry_budget > 0 && run.remaining == run.retry_at {
                    run.retry_budget -= 1;
                    run.retries += 1;
                    run.state = RunState::Retrying;
                    continue;
                }

                run.remaining = run.remaining.saturating_sub(1);
                if run.remaining == 0 {
                    run.state = RunState::Completed;
                    finished.write(RunFinished {
                        cancelled: false,
                        retries: run.retries,
                    });
                }
            }
            RunState::Retrying => run.state = RunState::Running,
            RunState::Completed | RunState::Cancelled => {}
        }
    }
}

fn collect_finished(mut messages: MessageReader<RunFinished>, mut stats: ResMut<RuntimeStats>) {
    for message in messages.read() {
        if message.cancelled {
            stats.cancelled += 1;
        } else {
            stats.completed += 1;
        }
        stats.retried += u64::from(message.retries);
    }
}

fn build_app() -> App {
    let mut app = App::new();
    app.add_plugins((WorkflowPlugin, MetricsPlugin));
    app
}

fn execute_batch(app: &mut App, spec: BatchSpec) -> Result<BatchResult> {
    if spec.runs == 0 {
        bail!("runs must be greater than zero");
    }
    if spec.steps == 0 {
        bail!("steps must be greater than zero");
    }

    let before = app.world().resource::<RuntimeStats>().clone();
    let retry_at = (spec.steps / 2).max(1);

    for i in 1..=spec.runs {
        let retry_budget = u8::from(spec.retry_every > 0 && i % spec.retry_every == 0);
        let cancel_on_tick =
            (spec.cancel_every > 0 && i % spec.cancel_every == 0).then_some(3.min(spec.steps));

        app.world_mut().spawn(WorkflowRun {
            remaining: spec.steps,
            retry_at,
            retry_budget,
            retries: 0,
            tick: 0,
            cancel_on_tick,
            state: RunState::Ready,
        });
    }

    let start = Instant::now();
    let mut ticks = 0_u64;
    let max_ticks = u64::from(spec.steps) * 4 + 32;

    loop {
        app.update();
        ticks += 1;

        let stats = app.world().resource::<RuntimeStats>();
        let finished = (stats.completed - before.completed) + (stats.cancelled - before.cancelled);
        if finished == u64::from(spec.runs) {
            let result = BatchResult {
                runs: spec.runs,
                completed: (stats.completed - before.completed) as u32,
                cancelled: (stats.cancelled - before.cancelled) as u32,
                retried: (stats.retried - before.retried) as u32,
                ticks,
                elapsed_micros: start.elapsed().as_micros(),
            };
            return Ok(result);
        }

        if ticks > max_ticks {
            bail!(
                "batch did not converge after {ticks} ticks (finished {finished}/{})",
                spec.runs
            );
        }
    }
}

enum RuntimeCommand {
    RunBatch {
        spec: BatchSpec,
        response: oneshot::Sender<Result<BatchResult>>,
    },
}

#[derive(Clone)]
pub struct WorkflowRuntimeHandle {
    tx: mpsc::Sender<RuntimeCommand>,
}

impl WorkflowRuntimeHandle {
    pub fn spawn() -> Result<Self> {
        let (tx, mut rx) = mpsc::channel::<RuntimeCommand>(64);

        thread::Builder::new()
            .name("audiagentic-bevy-runtime".to_owned())
            .spawn(move || {
                let mut app = build_app();
                while let Some(command) = rx.blocking_recv() {
                    match command {
                        RuntimeCommand::RunBatch { spec, response } => {
                            let _ = response.send(execute_batch(&mut app, spec));
                        }
                    }
                }
            })
            .context("spawn Bevy runtime thread")?;

        Ok(Self { tx })
    }

    pub async fn run_batch(&self, spec: BatchSpec) -> Result<BatchResult> {
        let (response, rx) = oneshot::channel();
        self.tx
            .send(RuntimeCommand::RunBatch { spec, response })
            .await
            .context("Bevy runtime is not available")?;
        rx.await.context("Bevy runtime dropped response")?
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn runs_large_batch_with_retry_and_cancel() {
        let runtime = WorkflowRuntimeHandle::spawn().unwrap();
        let result = runtime
            .run_batch(BatchSpec {
                runs: 10_000,
                steps: 12,
                retry_every: 17,
                cancel_every: 101,
            })
            .await
            .unwrap();

        assert_eq!(result.completed + result.cancelled, 10_000);
        assert!(result.cancelled > 0);
        assert!(result.retried > 0);
        assert!(result.ticks < 80);
    }
}
