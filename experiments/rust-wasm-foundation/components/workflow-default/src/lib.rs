mod bindings {
    wit_bindgen::generate!({
        world: "provider",
        generate_all,
    });
}

use bindings::exports::audiagentic::workflow::engine::Guest;

struct Workflow;

impl Guest for Workflow {
    fn execute(input: String) -> Result<String, String> {
        Ok(format!("workflow-default:{input}"))
    }
}

bindings::export!(Workflow with_types_in bindings);
