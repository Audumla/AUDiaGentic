use std::sync::{Arc, Mutex};

use tracing::{info, info_span};
use tracing_subscriber::fmt::MakeWriter;

#[derive(Clone, Default)]
struct Buffer(Arc<Mutex<Vec<u8>>>);

struct BufferWriter(Arc<Mutex<Vec<u8>>>);

impl std::io::Write for BufferWriter {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        self.0.lock().unwrap().extend_from_slice(bytes);
        Ok(bytes.len())
    }

    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

impl<'a> MakeWriter<'a> for Buffer {
    type Writer = BufferWriter;

    fn make_writer(&'a self) -> Self::Writer {
        BufferWriter(Arc::clone(&self.0))
    }
}

#[test]
fn application_edge_emits_structured_execution_context() {
    let output = Buffer::default();
    let subscriber = tracing_subscriber::fmt()
        .without_time()
        .with_target(false)
        .with_writer(output.clone())
        .finish();

    tracing::subscriber::with_default(subscriber, || {
        let execution = info_span!(
            "application.execution",
            execution_id = "execution-proof",
            correlation_id = "correlation-proof",
            config_revision = "revision-proof",
        );
        let _guard = execution.enter();
        info!(operation = "managed_config.apply", "effect completed");
    });

    let rendered = String::from_utf8(output.0.lock().unwrap().clone()).unwrap();
    assert!(rendered.contains("application.execution"));
    assert!(rendered.contains("execution_id=\"execution-proof\""));
    assert!(rendered.contains("correlation_id=\"correlation-proof\""));
    assert!(rendered.contains("config_revision=\"revision-proof\""));
    assert!(rendered.contains("operation=\"managed_config.apply\""));
}
