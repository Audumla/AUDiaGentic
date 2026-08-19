#![forbid(unsafe_code)]

use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use audiagentic_application::Application;
use audiagentic_core::{
    ApplicationContext, ApplicationId, ApplicationInstanceId, ApplicationManifest,
};
use target_baseline_demo_capability::{Greeting, GreetingError};
use wasmtime::component::{Component, HasSelf, Linker};
use wasmtime::{Engine, Store};

wasmtime::component::bindgen!({
    world: "host-aware",
    path: "../../wit",
});

#[derive(Default)]
struct HostState {
    observations: Vec<String>,
}

impl audiagentic::baseline::observer::Host for HostState {
    fn record(&mut self, message: String) {
        self.observations.push(message);
    }
}

struct WasmGreetingInner {
    store: Store<HostState>,
    bindings: HostAware,
}

struct WasmGreeting {
    inner: Mutex<WasmGreetingInner>,
}

impl WasmGreeting {
    fn from_bytes(bytes: &[u8]) -> Result<Self, GreetingError> {
        let engine = Engine::default();
        let component = Component::from_binary(&engine, bytes)
            .map_err(|error| GreetingError::new(error.to_string()))?;
        let mut linker = Linker::new(&engine);
        HostAware::add_to_linker::<_, HasSelf<_>>(&mut linker, |state| state)
            .map_err(|error| GreetingError::new(error.to_string()))?;
        let mut store = Store::new(&engine, HostState::default());
        let bindings = HostAware::instantiate(&mut store, &component, &linker)
            .map_err(|error| GreetingError::new(error.to_string()))?;
        Ok(Self {
            inner: Mutex::new(WasmGreetingInner { store, bindings }),
        })
    }

    fn observations(&self) -> Vec<String> {
        self.inner
            .lock()
            .expect("wasm greeting mutex poisoned")
            .store
            .data()
            .observations
            .clone()
    }
}

impl Greeting for WasmGreeting {
    fn greet(&self, name: &str) -> Result<String, GreetingError> {
        let mut inner = self
            .inner
            .lock()
            .map_err(|_| GreetingError::new("wasm greeting mutex poisoned"))?;
        let WasmGreetingInner { store, bindings } = &mut *inner;
        bindings
            .call_greet(store, name)
            .map_err(|error| GreetingError::new(error.to_string()))
    }
}

fn missing_host_authority_is_rejected(bytes: &[u8]) -> Result<bool, GreetingError> {
    let engine = Engine::default();
    let component = Component::from_binary(&engine, bytes)
        .map_err(|error| GreetingError::new(error.to_string()))?;
    let linker = Linker::<HostState>::new(&engine);
    let mut store = Store::new(&engine, HostState::default());
    Ok(HostAware::instantiate(&mut store, &component, &linker).is_err())
}

fn main() -> Result<(), GreetingError> {
    let component_path = std::env::args_os()
        .nth(1)
        .map(PathBuf::from)
        .ok_or_else(|| GreetingError::new("usage: target-baseline-wasm-demo <component.wasm>"))?;
    let bytes = std::fs::read(&component_path)
        .map_err(|error| GreetingError::new(format!("read {component_path:?}: {error}")))?;

    assert!(missing_host_authority_is_rejected(&bytes)?);
    println!("MISSING_HOST_AUTHORITY_REJECTED");

    let greeting = Arc::new(WasmGreeting::from_bytes(&bytes)?);
    let application_id = ApplicationId::try_from("target-baseline-wasm-demo")
        .map_err(|error| GreetingError::new(error.to_string()))?;
    let manifest = Arc::new(ApplicationManifest::new(application_id.clone(), "0.1.0"));
    let context = ApplicationContext::new(
        application_id,
        ApplicationInstanceId::try_from("target-baseline-wasm-demo-1")
            .map_err(|error| GreetingError::new(error.to_string()))?,
    );
    let application = Application::new(manifest, context, Arc::clone(&greeting));

    let result = application.state().greet("world")?;
    assert_eq!(result, "wasm:world");
    assert_eq!(greeting.observations(), vec!["greet:world"]);
    println!("DIRECT_WASMTIME_GREETING={result}");
    println!("HOST_AUTHORITY_CALLS={:?}", greeting.observations());
    println!("DIRECT_WASMTIME_OK");
    Ok(())
}
