use std::collections::BTreeMap;

use thiserror::Error;

#[derive(Debug, Error, PartialEq, Eq)]
pub enum TemplateError {
    #[error("missing template key `{0}`")]
    MissingKey(String),
    #[error("unterminated template placeholder")]
    Unterminated,
}

pub fn render(template: &str, values: &BTreeMap<String, String>) -> Result<String, TemplateError> {
    let mut out = String::with_capacity(template.len());
    let mut rest = template;

    while let Some(start) = rest.find("{{") {
        out.push_str(&rest[..start]);
        let after_open = &rest[start + 2..];
        let end = after_open.find("}}").ok_or(TemplateError::Unterminated)?;
        let key = after_open[..end].trim();
        let value = values
            .get(key)
            .ok_or_else(|| TemplateError::MissingKey(key.to_owned()))?;
        out.push_str(value);
        rest = &after_open[end + 2..];
    }

    out.push_str(rest);
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn strict_render_replaces_known_values() {
        let values = BTreeMap::from([("name".to_owned(), "AUDiaGentic".to_owned())]);
        assert_eq!(render("hello {{ name }}", &values).unwrap(), "hello AUDiaGentic");
    }

    #[test]
    fn strict_render_rejects_missing_values() {
        assert_eq!(
            render("{{ missing }}", &BTreeMap::new()).unwrap_err(),
            TemplateError::MissingKey("missing".to_owned())
        );
    }
}
