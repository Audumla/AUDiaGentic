use async_trait::async_trait;

#[async_trait]
pub trait ComponentProbe: Send + Sync {
    async fn probe(&self) -> Result<String, String>;
}
