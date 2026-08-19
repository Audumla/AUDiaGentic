#![forbid(unsafe_code)]

mod bindings {
    wit_bindgen::generate!({
        world: "host-aware",
        path: "../../wit",
    });
}

struct GreetingComponent;

impl bindings::Guest for GreetingComponent {
    fn greet(name: String) -> String {
        bindings::audiagentic::baseline::observer::observe(&format!("greet:{name}"));
        format!("wasm:{name}")
    }
}

bindings::export!(GreetingComponent with_types_in bindings);
