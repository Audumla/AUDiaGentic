use std::{collections::BTreeMap, error::Error};

use audiagentic_config::{ConfigLayerId, ConfigLayers, ConfigRevision};
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
    config_revision: ConfigRevision,
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
    let resolved = ConfigLayers::new()
        .merge_toml(
            ConfigLayerId::new("application")?,
            "greeting = 'hello'\n",
        )
        .resolve::<GreetingConfig>()?;
    let composition = Greeter {
        greeting: resolved.value().greeting.clone(),
        config_revision: resolved.revision(),
        template: Template::parse("{{ greeting }}, {{ name }}!")?,
    };
    let app = Application::new(
        ApplicationIdentity::new(
            ApplicationId::new("medium-greeter")?,
            ApplicationInstanceId::new("local")?,
        ),
        composition,
    );

    assert_ne!(app.composition().config_revision.value(), 0);
    assert_eq!(app.composition().greet("world")?, "hello, world!");
    println!("MEDIUM_APP_OK");
    Ok(())
}
