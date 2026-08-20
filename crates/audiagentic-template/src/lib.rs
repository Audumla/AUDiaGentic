//! Small deterministic text templating with no I/O or application coupling.

use std::{collections::BTreeMap, error::Error, fmt};

#[derive(Debug, Clone, PartialEq, Eq)]
enum Part {
    Literal(String),
    Slot(String),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Template {
    parts: Vec<Part>,
}

impl Template {
    pub fn parse(source: &str) -> Result<Self, TemplateError> {
        let mut parts = Vec::new();
        let mut cursor = 0;

        while let Some(relative_start) = source[cursor..].find("{{") {
            let start = cursor + relative_start;
            if start > cursor {
                parts.push(Part::Literal(source[cursor..start].to_owned()));
            }
            let slot_start = start + 2;
            let relative_end = source[slot_start..]
                .find("}}")
                .ok_or(TemplateError::UnclosedSlot)?;
            let end = slot_start + relative_end;
            let name = source[slot_start..end].trim();
            if name.is_empty() {
                return Err(TemplateError::EmptySlot);
            }
            parts.push(Part::Slot(name.to_owned()));
            cursor = end + 2;
        }

        if cursor < source.len() {
            parts.push(Part::Literal(source[cursor..].to_owned()));
        }

        Ok(Self { parts })
    }

    pub fn render(&self, values: &BTreeMap<String, String>) -> Result<String, TemplateError> {
        let mut rendered = String::new();
        for part in &self.parts {
            match part {
                Part::Literal(value) => rendered.push_str(value),
                Part::Slot(name) => rendered.push_str(
                    values
                        .get(name)
                        .ok_or_else(|| TemplateError::MissingValue(name.clone()))?,
                ),
            }
        }
        Ok(rendered)
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TemplateError {
    EmptySlot,
    UnclosedSlot,
    MissingValue(String),
}

impl fmt::Display for TemplateError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::EmptySlot => f.write_str("template slot must not be empty"),
            Self::UnclosedSlot => f.write_str("template slot is not closed"),
            Self::MissingValue(name) => write!(f, "missing template value: {name}"),
        }
    }
}

impl Error for TemplateError {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn renders_named_values() {
        let template = Template::parse("hello {{ name }}").unwrap();
        let values = BTreeMap::from([("name".to_owned(), "world".to_owned())]);
        assert_eq!(template.render(&values).unwrap(), "hello world");
    }

    #[test]
    fn missing_values_are_typed_errors() {
        let template = Template::parse("{{ name }}").unwrap();
        assert_eq!(
            template.render(&BTreeMap::new()).unwrap_err(),
            TemplateError::MissingValue("name".to_owned())
        );
    }
}
