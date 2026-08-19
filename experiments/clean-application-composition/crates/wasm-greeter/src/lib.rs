use std::{path::Path, sync::Arc};

use async_trait::async_trait;
use audiagentic_clean_capabilities::{CapabilityError, CapabilityResult, Greeting};
use wasmtime::{
    Engine, Store,
    component::{Component, Linker, ResourceTable},
};
use wasmtime_wasi::{WasiCtx, WasiCtxView, WasiView};

mod bindings {
    wasmtime::component::bindgen!({
        world: "greeter",
        path: "../../wit",
    });
}

struct HostState {
    wasi: WasiCtx,
    table: ResourceTable,
}

impl WasiView for HostState {
    fn ctx(&mut self) -> WasiCtxView<'_> {
        WasiCtxView {
            ctx: &mut self.wasi,
            table: &mut self.table,
        }
    }
}

#[derive(Clone)]
pub struct WasmGreeter {
    engine: Engine,
    component: Arc<Component>,
}

impl WasmGreeter {
    pub fn load(path: impl AsRef<Path>) -> CapabilityResult<Self> {
        let mut config = wasmtime::Config::new();
        config.wasm_component_model(true);
        let engine =
            Engine::new(&config).map_err(|error| CapabilityError::failed("greeting", error))?;
        let component = Component::from_file(&engine, path)
            .map_err(|error| CapabilityError::failed("greeting", error))?;
        Ok(Self {
            engine,
            component: Arc::new(component),
        })
    }
}

#[async_trait]
impl Greeting for WasmGreeter {
    async fn greet(&self, name: &str) -> CapabilityResult<String> {
        let engine = self.engine.clone();
        let component = self.component.clone();
        let name = name.to_owned();

        tokio::task::spawn_blocking(move || {
            let mut linker = Linker::<HostState>::new(&engine);
            wasmtime_wasi::p2::add_to_linker_sync(&mut linker)
                .map_err(|error| CapabilityError::failed("greeting", error))?;

            let state = HostState {
                wasi: WasiCtx::builder().build(),
                table: ResourceTable::new(),
            };
            let mut store = Store::new(&engine, state);
            let instance = bindings::Greeter::instantiate(&mut store, &component, &linker)
                .map_err(|error| CapabilityError::failed("greeting", error))?;
            instance
                .call_greet(&mut store, &name)
                .map_err(|error| CapabilityError::failed("greeting", error))
        })
        .await
        .map_err(|error| CapabilityError::failed("greeting", error))?
    }
}
