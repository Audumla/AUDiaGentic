mod bindings {
    wit_bindgen::generate!({
        world: "process",
        generate_all,
    });
}

use bindings::{
    audiagentic::{host::audit, workflow::engine},
    exports::wasi::http::incoming_handler::Guest,
    wasi::http::types::{
        Fields, IncomingRequest, OutgoingBody, OutgoingResponse, ResponseOutparam,
    },
};

struct Process;

fn respond(response_out: ResponseOutparam, status: u16, text: &str) {
    let response = OutgoingResponse::new(Fields::new());
    response.set_status_code(status).expect("valid HTTP status");
    let body = response.body().expect("response body");
    ResponseOutparam::set(response_out, Ok(response));
    let stream = body.write().expect("response stream");
    stream
        .blocking_write_and_flush(text.as_bytes())
        .expect("write response");
    drop(stream);
    OutgoingBody::finish(body, None).expect("finish response");
}

impl Guest for Process {
    fn handle(_request: IncomingRequest, response_out: ResponseOutparam) {
        match engine::execute("smoke") {
            Ok(output) => {
                audit::emit("workflow.execute", &output);
                respond(response_out, 200, &output);
            }
            Err(error) => {
                audit::emit("workflow.error", &error);
                respond(response_out, 500, &error);
            }
        }
    }
}

bindings::export!(Process with_types_in bindings);
