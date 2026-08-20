use async_trait::async_trait;
use audiagentic_component_probe_api_spike::ComponentProbe;
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
    async fn probe(&self) -> Result<String, String> {
        let output = Command::new(&self.executable)
            .output()
            .await
            .map_err(|e| format!("failed to execute component runtime smoke: {e}"))?;
        if !output.status.success() {
            return Err(format!(
                "component runtime smoke failed: {}",
                String::from_utf8_lossy(&output.stderr)
            ));
        }
        let stdout = String::from_utf8_lossy(&output.stdout);
        if !stdout.contains("SMOKE_OK") {
            return Err("component runtime did not emit SMOKE_OK".to_owned());
        }
        let provider = stdout
            .lines()
            .find_map(|line| line.strip_prefix("DEFAULT_PROVIDER="))
            .ok_or_else(|| "component runtime did not report DEFAULT_PROVIDER".to_owned())?;
        Ok(provider.to_owned())
    }
}
