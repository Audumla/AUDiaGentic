#![forbid(unsafe_code)]

/// Example of a capability contract living outside AUDiaGentic core.
pub trait Greeting: Send + Sync {
    fn greet(&self, name: &str) -> String;
}
