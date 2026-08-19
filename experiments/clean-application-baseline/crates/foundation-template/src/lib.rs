use std::fmt;

use serde_json::Value;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TemplateError {
    UnclosedPlaceholder,
    EmptyPlaceholder,
    MissingValue(String),
    NonScalarValue(String),
}

impl fmt::Display for TemplateError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::UnclosedPlaceholder => f.write_str("template contains an unclosed placeholder"),
            Self::EmptyPlaceholder => f.write_str("template contains an empty placeholder"),
            Self::MissingValue(path) => write!(f, "template value is missing: {path}"),
            Self::NonScalarValue(path) => write!(f, "template value is not scalar: {path}"),
        }
    }
}

impl std::error::Error for TemplateError {}

pub fn render(template: &str, data: &Value) -> Result<String, TemplateError> {
    let mut out = String::with_capacity(template.len());
    let mut rest = template;

    while let Some(open) = rest.find('{') {
        out.push_str(&rest[..open]);
        let after_open = &rest[open + 1..];
        let Some(close) = after_open.find('}') else {
            return Err(TemplateError::UnclosedPlaceholder);
        };
        let path = &after_open[..close];
        if path.is_empty() {
            return Err(TemplateError::EmptyPlaceholder);
        }
        out.push_str(&resolve_scalar(data, path)?);
        rest = &after_open[close + 1..];
    }

    out.push_str(rest);
    Ok(out)
}

fn resolve_scalar(root: &Value, path: &str) -> Result<String, TemplateError> {
    let mut current = root;
    for part in path.split('.') {
        current = current
            .get(part)
            .ok_or_else(|| TemplateError::MissingValue(path.to_owned()))?;
    }

    match current {
        Value::Null => Ok("null".to_owned()),
        Value::Bool(value) => Ok(value.to_string()),
        Value::Number(value) => Ok(value.to_string()),
        Value::String(value) => Ok(value.clone()),
        Value::Array(_) | Value::Object(_) => Err(TemplateError::NonScalarValue(path.to_owned())),
    }
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    #[test]
    fn renders_strict_dotted_scalar_paths() {
        let data = json!({"user": {"name": "Marius"}, "count": 3});
        assert_eq!(render("hello {user.name} x{count}", &data).unwrap(), "hello Marius x3");
    }

    #[test]
    fn missing_and_structured_values_fail() {
        let data = json!({"user": {"name": "Marius"}});
        assert_eq!(render("{missing}", &data), Err(TemplateError::MissingValue("missing".into())));
        assert_eq!(render("{user}", &data), Err(TemplateError::NonScalarValue("user".into())));
    }
}
