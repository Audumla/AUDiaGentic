use std::{thread, time::Instant};

use async_trait::async_trait;
use audiagentic_clean_capabilities::{
    BatchResult, BatchSpec, CapabilityError, CapabilityResult, Workflow,
};
use bevy_app::{App, Plugin, Update};
use bevy_ecs::{prelude::*, schedule::IntoScheduleConfigs};
use tokio::sync::{mpsc, oneshot};

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

struct WorkflowPlugin;

impl Plugin for WorkflowPlugin {
    fn build(&self, app: &mut App) {
        app.add_message::<RunFinished>()
            .add_systems(Update, advance_runs);
    }
}

struct MetricsPlugin;

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

fn execute_batch(app: &mut App, spec: BatchSpec) -> CapabilityResult<BatchResult> {
    if spec.runs == 0 || spec.steps == 0 {
        return Err(CapabilityError::failed(
            "workflow",
            "runs and steps must be greater than zero",
        ));
    }

    let before = app.world().resource::<RuntimeStats>().clone();
    let retry_at = (spec.steps / 2).max(1);

    for i in 1..=spec.runs {
        app.world_mut().spawn(WorkflowRun {
            remaining: spec.steps,
            retry_at,
            retry_budget: u8::from(spec.retry_every > 0 && i % spec.retry_every == 0),
            retries: 0,
            tick: 0,
            cancel_on_tick: (spec.cancel_every > 0 && i % spec.cancel_every == 0)
                .then_some(3.min(spec.steps)),
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
            return Ok(BatchResult {
                runs: spec.runs,
                completed: (stats.completed - before.completed) as u32,
                cancelled: (stats.cancelled - before.cancelled) as u32,
                retried: (stats.retried - before.retried) as u32,
                ticks,
                elapsed_micros: start.elapsed().as_micros(),
            });
        }
        if ticks > max_ticks {
            return Err(CapabilityError::failed(
                "workflow",
                format!("batch did not converge after {ticks} ticks"),
            ));
        }
    }
}

enum RuntimeCommand {
    RunBatch {
        spec: BatchSpec,
        response: oneshot::Sender<CapabilityResult<BatchResult>>,
    },
}

#[derive(Clone)]
pub struct BevyWorkflow {
    tx: mpsc::Sender<RuntimeCommand>,
}

impl BevyWorkflow {
    pub fn spawn() -> CapabilityResult<Self> {
        let (tx, mut rx) = mpsc::channel::<RuntimeCommand>(64);
        thread::Builder::new()
            .name("audiagentic-clean-bevy-workflow".to_owned())
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
            .map_err(|error| CapabilityError::failed("workflow", error))?;
        Ok(Self { tx })
    }
}

#[async_trait]
impl Workflow for BevyWorkflow {
    async fn run_batch(&self, spec: BatchSpec) -> CapabilityResult<BatchResult> {
        let (response, rx) = oneshot::channel();
        self.tx
            .send(RuntimeCommand::RunBatch { spec, response })
            .await
            .map_err(|error| CapabilityError::failed("workflow", error))?;
        rx.await
            .map_err(|error| CapabilityError::failed("workflow", error))?
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn capability_boundary_hides_bevy() {
        let workflow: Box<dyn Workflow> = Box::new(BevyWorkflow::spawn().unwrap());
        let result = workflow
            .run_batch(BatchSpec {
                runs: 10_000,
                steps: 12,
                retry_every: 17,
                cancel_every: 101,
            })
            .await
            .unwrap();
        assert_eq!(result.completed + result.cancelled, 10_000);
        assert!(result.retried > 0);
    }
}
