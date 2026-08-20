use std::error::Error;

use audiagentic_core::{Application, ApplicationId, ApplicationIdentity, ApplicationInstanceId};

#[derive(Debug, Clone, Copy)]
struct Calculator;

impl Calculator {
    fn add(self, left: i64, right: i64) -> i64 {
        left + right
    }
}

fn main() -> Result<(), Box<dyn Error>> {
    let app = Application::new(
        ApplicationIdentity::new(
            ApplicationId::new("tiny-calculator")?,
            ApplicationInstanceId::new("local")?,
        ),
        Calculator,
    );

    assert_eq!(app.composition().add(20, 22), 42);
    println!("TINY_APP_OK");
    Ok(())
}
