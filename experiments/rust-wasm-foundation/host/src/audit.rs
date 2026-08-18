use std::{
    collections::{HashMap, HashSet},
    sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    },
};

use tokio::sync::Mutex;
use wash_runtime::{
    engine::{
        ctx::{ActiveCtx, SharedCtx, extract_active_ctx},
        workload::{ResolvedWorkload, WorkloadItem},
    },
    plugin::{HostPlugin, WitInterfaces},
    wit::{WitInterface, WitWorld},
};

mod bindings {
    wasmtime::component::bindgen!({
        imports: { default: async | trappable },
        inline: r#"
            package audiagentic:host@0.1.0;

            interface audit {
                emit: func(action: string, detail: string);
            }

            world provider {
                import audit;
            }
        "#,
    });
}

#[derive(Debug, Clone)]
pub struct AuditSnapshot {
    pub calls: usize,
    pub binds: usize,
    pub resolved: usize,
    pub unbinds: usize,
    pub entries: Vec<(String, String)>,
}

#[derive(Default)]
pub struct AuditHostPlugin {
    calls: AtomicUsize,
    binds: AtomicUsize,
    resolved: AtomicUsize,
    unbinds: AtomicUsize,
    entries: Mutex<Vec<(String, String)>>,
    components: Mutex<HashMap<String, String>>,
}

impl AuditHostPlugin {
    pub async fn snapshot(&self) -> AuditSnapshot {
        AuditSnapshot {
            calls: self.calls.load(Ordering::SeqCst),
            binds: self.binds.load(Ordering::SeqCst),
            resolved: self.resolved.load(Ordering::SeqCst),
            unbinds: self.unbinds.load(Ordering::SeqCst),
            entries: self.entries.lock().await.clone(),
        }
    }
}

impl<'a> bindings::audiagentic::host::audit::Host for ActiveCtx<'a> {
    async fn emit(&mut self, action: String, detail: String) -> wasmtime::Result<()> {
        let plugin = self.try_get_plugin::<AuditHostPlugin>("audiagentic-audit")?;
        plugin.calls.fetch_add(1, Ordering::SeqCst);
        plugin.entries.lock().await.push((action, detail));
        Ok(())
    }
}

#[async_trait::async_trait]
impl HostPlugin for AuditHostPlugin {
    fn id(&self) -> &'static str {
        "audiagentic-audit"
    }

    fn world(&self) -> WitWorld {
        WitWorld {
            imports: HashSet::from([WitInterface::from("audiagentic:host/audit@0.1.0")]),
            ..Default::default()
        }
    }

    async fn on_workload_bind(
        &self,
        _workload: &wash_runtime::engine::workload::UnresolvedWorkload,
        interfaces: WitInterfaces<'_>,
    ) -> anyhow::Result<()> {
        if !interfaces.contains("audiagentic", "host", &["audit"]) {
            anyhow::bail!("audit plugin bound without audiagentic:host/audit");
        }
        self.binds.fetch_add(1, Ordering::SeqCst);
        Ok(())
    }

    async fn on_workload_item_bind<'a>(
        &self,
        item: &mut WorkloadItem<'a>,
        interfaces: WitInterfaces<'_>,
    ) -> anyhow::Result<()> {
        if !interfaces.contains("audiagentic", "host", &["audit"]) {
            anyhow::bail!("audit item bind missing audiagentic:host/audit");
        }
        bindings::audiagentic::host::audit::add_to_linker::<_, SharedCtx>(
            item.linker(),
            extract_active_ctx,
        )?;
        Ok(())
    }

    async fn on_workload_resolved(
        &self,
        workload: &ResolvedWorkload,
        component_id: &str,
    ) -> anyhow::Result<()> {
        self.resolved.fetch_add(1, Ordering::SeqCst);
        self.components
            .lock()
            .await
            .insert(component_id.to_owned(), workload.id().to_owned());
        Ok(())
    }

    async fn on_workload_unbind(
        &self,
        _workload_id: &str,
        interfaces: WitInterfaces<'_>,
    ) -> anyhow::Result<()> {
        if interfaces.contains("audiagentic", "host", &["audit"]) {
            self.unbinds.fetch_add(1, Ordering::SeqCst);
        }
        Ok(())
    }
}
