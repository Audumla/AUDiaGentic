#![forbid(unsafe_code)]

use serde_json::{Map, Value};
use thiserror::Error;

#[derive(Clone, Debug, Eq, PartialEq, Error)]
pub enum TemplateError {
    #[error("template path {path:?} not found; available top-level keys: {available_keys:?}")]
    MissingPath {
        path: String,
        available_keys: Vec<String>,
    },
}

pub fn has_placeholders(template: &str) -> bool {
    template
        .find('{')
        .and_then(|start| template[start + 1..].find('}'))
        .is_some()
}

pub fn resolve_path<'a>(context: &'a Map<String, Value>, path: &str) -> Option<&'a Value> {
    let mut segments = path.split('.');
    let first = segments.next()?;
    if first.is_empty() {
        return None;
    }

    let mut current = context.get(first)?;
    for segment in segments {
        let Value::Object(map) = current else {
            return None;
        };
        current = map.get(segment)?;
    }
    Some(current)
}

pub fn render_template(
    template: &str,
    context: &Map<String, Value>,
) -> Result<String, TemplateError> {
    let mut output = String::with_capacity(template.len());
    let mut rest = template;

    while let Some(start) = rest.find('{') {
        output.push_str(&rest[..start]);
        let after_open = &rest[start + 1..];
        let Some(end) = after_open.find('}') else {
            output.push_str(&rest[start..]);
            return Ok(output);
        };

        let path = after_open[..end].trim();
        let value = resolve_path(context, path).ok_or_else(|| TemplateError::MissingPath {
            path: path.to_owned(),
            available_keys: sorted_keys(context),
        })?;
        output.push_str(&render_value(value));
        rest = &after_open[end + 1..];
    }

    output.push_str(rest);
    Ok(output)
}

fn sorted_keys(context: &Map<String, Value>) -> Vec<String> {
    let mut keys: Vec<String> = context.keys().cloned().collect();
    keys.sort();
    keys
}

fn render_value(value: &Value) -> String {
    match value {
        Value::Null => String::new(),
        Value::String(text) => text.clone(),
        Value::Bool(value) => value.to_string(),
        Value::Number(value) => value.to_string(),
        Value::Array(_) | Value::Object(_) => {
            serde_json::to_string(value).expect("serde_json::Value must serialize")
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn renders_dotted_paths_and_structures() {
        let Value::Object(context) = json!({
            "event": {"payload": {"id": 42}},
            "tags": ["a", "b"],
            "optional": null
        }) else {
            unreachable!();
        };

        assert_eq!(
            render_template("id={event.payload.id} tags={tags} n={optional}", &context).unwrap(),
            "id=42 tags=[\"a\",\"b\"] n="
        );
    }

    #[test]
    fn missing_paths_are_strict_and_diagnostic() {
        let Value::Object(context) = json!({"alpha": 1, "beta": 2}) else {
            unreachable!();
        };
        let error = render_template("{gamma.id}", &context).unwrap_err();
        assert_eq!(
            error,
            TemplateError::MissingPath {
                path: "gamma.id".to_owned(),
                available_keys: vec!["alpha".to_owned(), "beta".to_owned()],
            }
        );
    }

    #[test]
    fn unmatched_open_brace_is_left_literal() {
        let context = Map::new();
        assert_eq!(
            render_template("literal { text", &context).unwrap(),
            "literal { text"
        );
    }
}
