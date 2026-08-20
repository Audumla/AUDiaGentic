use std::collections::BTreeSet;

use async_trait::async_trait;
use audiagentic_process_api_spike::{ProcessError, ProcessOutput, ProcessRequest, ProcessRunner};
use tokio::process::Command;

#[derive(Clone, Debug)]
pub struct NativeProcessRunner {
    allowed_programs: BTreeSet<String>,
}

impl NativeProcessRunner {
    pub fn new(allowed_programs: impl IntoIterator<Item = String>) -> Self {
        Self {
            allowed_programs: allowed_programs.into_iter().collect(),
        }
    }
}

#[async_trait]
impl ProcessRunner for NativeProcessRunner {
    async fn run(&self, request: ProcessRequest) -> Result<ProcessOutput, ProcessError> {
        if !self.allowed_programs.contains(&request.program) {
            return Err(ProcessError::Denied(request.program));
        }

        let output = Command::new(&request.program)
            .args(&request.args)
            .env_clear()
            .envs(&request.environment)
            .output()
            .await
            .map_err(|error| ProcessError::Launch(error.to_string()))?;

        Ok(ProcessOutput {
            exit_code: output.status.code(),
            stdout: String::from_utf8_lossy(&output.stdout).into_owned(),
            stderr: String::from_utf8_lossy(&output.stderr).into_owned(),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn denied_program_never_launches() {
        let runner = NativeProcessRunner::new(Vec::new());
        let result = runner
            .run(ProcessRequest {
                program: "definitely-not-allowed".into(),
                args: Vec::new(),
                environment: Default::default(),
            })
            .await;
        assert_eq!(
            result,
            Err(ProcessError::Denied("definitely-not-allowed".into()))
        );
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn allowlisted_program_runs_with_explicit_environment() {
        let runner = NativeProcessRunner::new(["/bin/echo".to_owned()]);
        let output = runner
            .run(ProcessRequest {
                program: "/bin/echo".into(),
                args: vec!["hello".into()],
                environment: Default::default(),
            })
            .await
            .unwrap();
        assert_eq!(output.exit_code, Some(0));
        assert_eq!(output.stdout.trim(), "hello");
    }
}
