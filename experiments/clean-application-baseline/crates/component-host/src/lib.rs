use async_trait::async_trait;
use audiagentic_capability_api_spike::{ComponentProbe, ComponentProbeError};
use tokio::process::Command;

pub struct WasmComponentProbe {
    executable: String,
}

impl WasmComponentProbe {
    pub fn new(executable: impl Into<String>) -> Self {
        Self {
            executable: executable.into(),
        }
    }
}

#[async_trait]
impl ComponentProbe for WasmComponentProbe {
    async fn probe(&self) -> Result<String, ComponentProbeError> {
        let output = Command::new(&self.executable)
            .output()
            .await
            .map_err(|error| ComponentProbeError::Unavailable(error.to_string()))?;
        if !output.status.success() {
            return Err(ComponentProbeError::Internal(
                String::from_utf8_lossy(&output.stderr).into_owned(),
            ));
        }
        let stdout = String::from_utf8_lossy(&output.stdout);
        if !stdout.contains("SMOKE_OK") {
            return Err(ComponentProbeError::InvalidResponse(
                "component runtime did not emit SMOKE_OK".to_owned(),
            ));
        }
        let provider = stdout
            .lines()
            .find_map(|line| line.strip_prefix("DEFAULT_PROVIDER="))
            .ok_or_else(|| {
                ComponentProbeError::InvalidResponse(
                    "component runtime did not report DEFAULT_PROVIDER".to_owned(),
                )
            })?;
        Ok(provider.to_owned())
    }
}
