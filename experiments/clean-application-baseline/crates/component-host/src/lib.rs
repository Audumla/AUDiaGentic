use std::{path::PathBuf, time::Duration};

use async_trait::async_trait;
use audiagentic_capability_api_spike::{CapabilityError, CapabilityResult, ComponentProbe};
use tokio::{process::Command, time::timeout};

const DEFAULT_PROBE_TIMEOUT: Duration = Duration::from_secs(30);

#[derive(Clone)]
pub struct WasmComponentProbe {
    executable: PathBuf,
    timeout: Duration,
}

impl WasmComponentProbe {
    pub fn new(executable: impl Into<PathBuf>) -> Self {
        Self {
            executable: executable.into(),
            timeout: DEFAULT_PROBE_TIMEOUT,
        }
    }

    pub fn with_timeout(mut self, timeout: Duration) -> Self {
        self.timeout = timeout;
        self
    }
}

fn parse_provider(stdout: &[u8]) -> CapabilityResult<String> {
    let stdout = String::from_utf8_lossy(stdout);
    if !stdout.contains("SMOKE_OK") {
        return Err(CapabilityError::execution(
            "component_probe",
            "component runtime did not emit SMOKE_OK",
        ));
    }
    stdout
        .lines()
        .find_map(|line| line.strip_prefix("DEFAULT_PROVIDER="))
        .map(ToOwned::to_owned)
        .ok_or_else(|| {
            CapabilityError::execution(
                "component_probe",
                "component runtime did not report DEFAULT_PROVIDER",
            )
        })
}

#[async_trait]
impl ComponentProbe for WasmComponentProbe {
    async fn probe(&self) -> CapabilityResult<String> {
        let mut command = Command::new(&self.executable);
        command.kill_on_drop(true);

        let output = timeout(self.timeout, command.output())
            .await
            .map_err(|_| {
                CapabilityError::timeout(
                    "component_probe",
                    format!("component runtime exceeded {:?}", self.timeout),
                )
            })?
            .map_err(|error| {
                CapabilityError::execution(
                    "component_probe",
                    format!("failed to execute component runtime smoke: {error}"),
                )
            })?;

        if !output.status.success() {
            return Err(CapabilityError::execution(
                "component_probe",
                format!(
                    "component runtime smoke failed: {}",
                    String::from_utf8_lossy(&output.stderr)
                ),
            ));
        }

        parse_provider(&output.stdout)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use audiagentic_capability_api_spike::CapabilityErrorKind;

    #[test]
    fn parses_successful_component_provider() {
        let provider =
            parse_provider(b"DEFAULT_PROVIDER=workflow-default:smoke\nSMOKE_OK\n").unwrap();
        assert_eq!(provider, "workflow-default:smoke");
    }

    #[test]
    fn rejects_incomplete_component_output() {
        let error = parse_provider(b"DEFAULT_PROVIDER=workflow-default:smoke\n").unwrap_err();
        assert_eq!(error.kind(), CapabilityErrorKind::Execution);
    }
}
