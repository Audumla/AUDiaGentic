mod bindings {
    wit_bindgen::generate!({
        world: "greeter",
        path: "../../wit",
    });
}

struct GreeterComponent;

impl bindings::Guest for GreeterComponent {
    fn greet(name: String) -> String {
        format!("wasm:hello {name}")
    }
}

bindings::export!(GreeterComponent with_types_in bindings);
