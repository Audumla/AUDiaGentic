use std::{collections::BTreeMap, error::Error};

use audiagentic_config::from_toml;
use audiagentic_core::{Application, ApplicationId, ApplicationIdentity, ApplicationInstanceId};
use audiagentic_template::{Template, TemplateError};
use schemars::JsonSchema;
use serde::Deserialize;

#[derive(Debug, Deserialize, JsonSchema)]
struct GreetingConfig {
    greeting: String,
}

#[derive(Debug)]
struct Greeter {
    greeting: String,
    template: Template,
}

impl Greeter {
    fn greet(&self, name: &str) -> Result<String, TemplateError> {
        self.template.render(&BTreeMap::from([
            ("greeting".to_owned(), self.greeting.clone()),
            ("name".to_owned(), name.to_owned()),
        ]))
    }
}

fn main() -> Result<(), Box<dyn Error>> {
    let config: GreetingConfig = from_toml("greeting = 'hello'\n")?;
    let composition = Greeter {
        greeting: config.greeting,
        template: Template::parse("{{ greeting }}, {{ name }}!")?,
    };
    let app = Application::new(
        ApplicationIdentity::new(
            ApplicationId::new("medium-greeter")?,
            ApplicationInstanceId::new("local")?,
        ),
        composition,
    );

    assert_eq!(app.composition().greet("world")?, "hello, world!");
    println!("MEDIUM_APP_OK");
    Ok(())
}
