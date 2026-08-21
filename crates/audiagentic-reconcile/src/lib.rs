//! Reconciliation vocabulary and pure planning primitives.
//!
//! I/O, retries, and ownership enforcement belong to the caller/host. This
//! crate provides explicit observed/desired state, plans, effects, and receipts.

use std::{error::Error, fmt};

use audiagentic_errors::{CodedError, ErrorCode, ErrorDefinition};

const OWNERSHIP_ID_EMPTY: ErrorDefinition = ErrorDefinition::new(
    ErrorCode::new("VAL-RECONCILE-001"),
    "Reconciliation ownership id must not be empty.",
    "Provide a stable non-empty ownership identifier.",
);
const EFFECT_ID_EMPTY: ErrorDefinition = ErrorDefinition::new(
    ErrorCode::new("VAL-RECONCILE-002"),
    "Reconciliation effect id must not be empty.",
    "Provide a stable non-empty effect identifier.",
);

macro_rules! define_reconcile_id {
    ($name:ident, $label:literal, $definition:ident) => {
        #[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash)]
        pub struct $name(String);

        impl $name {
            pub fn new(value: impl Into<String>) -> Result<Self, ReconcileIdError> {
                let value = value.into();
                if value.trim().is_empty() {
                    return Err(ReconcileIdError {
                        label: $label,
                        definition: &$definition,
                    });
                }
                Ok(Self(value))
            }

            pub fn as_str(&self) -> &str {
                &self.0
            }
        }
    };
}

define_reconcile_id!(OwnershipId, "ownership id", OWNERSHIP_ID_EMPTY);
define_reconcile_id!(EffectId, "effect id", EFFECT_ID_EMPTY);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ReconcileIdError {
    label: &'static str,
    definition: &'static ErrorDefinition,
}

impl CodedError for ReconcileIdError {
    fn definition(&self) -> &'static ErrorDefinition {
        self.definition
    }
}

impl fmt::Display for ReconcileIdError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{} must not be empty", self.label)
    }
}

impl Error for ReconcileIdError {}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Observed<T>(pub T);

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Desired<T>(pub T);

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Change<T> {
    Create { after: T },
    Replace { before: T, after: T },
    Delete { before: T },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Plan<C> {
    ownership: OwnershipId,
    effect: EffectId,
    changes: Vec<C>,
}

impl<C> Plan<C> {
    pub fn new(ownership: OwnershipId, effect: EffectId, changes: Vec<C>) -> Self {
        Self {
            ownership,
            effect,
            changes,
        }
    }

    pub fn ownership(&self) -> &OwnershipId {
        &self.ownership
    }

    pub fn effect(&self) -> &EffectId {
        &self.effect
    }

    pub fn changes(&self) -> &[C] {
        &self.changes
    }

    pub fn is_noop(&self) -> bool {
        self.changes.is_empty()
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Receipt<R> {
    effect: EffectId,
    result: R,
}

impl<R> Receipt<R> {
    pub fn new(effect: EffectId, result: R) -> Self {
        Self { effect, result }
    }

    pub fn effect(&self) -> &EffectId {
        &self.effect
    }

    pub fn result(&self) -> &R {
        &self.result
    }
}

pub fn plan_replace<T: Clone + PartialEq>(
    ownership: OwnershipId,
    effect: EffectId,
    observed: &Observed<T>,
    desired: &Desired<T>,
) -> Plan<Change<T>> {
    let changes = if observed.0 == desired.0 {
        Vec::new()
    } else {
        vec![Change::Replace {
            before: observed.0.clone(),
            after: desired.0.clone(),
        }]
    };
    Plan::new(ownership, effect, changes)
}

/// Plans presence-aware state without performing I/O. This is the primitive
/// used by capabilities such as managed configuration where create/delete are
/// semantically distinct from replacement.
pub fn plan_presence<T: Clone + PartialEq>(
    ownership: OwnershipId,
    effect: EffectId,
    observed: &Observed<Option<T>>,
    desired: &Desired<Option<T>>,
) -> Plan<Change<T>> {
    let changes = match (&observed.0, &desired.0) {
        (None, None) => Vec::new(),
        (None, Some(after)) => vec![Change::Create {
            after: after.clone(),
        }],
        (Some(before), None) => vec![Change::Delete {
            before: before.clone(),
        }],
        (Some(before), Some(after)) if before == after => Vec::new(),
        (Some(before), Some(after)) => vec![Change::Replace {
            before: before.clone(),
            after: after.clone(),
        }],
    };
    Plan::new(ownership, effect, changes)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ownership() -> OwnershipId {
        OwnershipId::new("owner").unwrap()
    }

    fn effect() -> EffectId {
        EffectId::new("effect").unwrap()
    }

    #[test]
    fn identifiers_have_distinct_stable_error_identity() {
        assert_eq!(
            OwnershipId::new(" ").unwrap_err().code().as_str(),
            "VAL-RECONCILE-001"
        );
        assert_eq!(
            EffectId::new("").unwrap_err().code().as_str(),
            "VAL-RECONCILE-002"
        );
    }

    #[test]
    fn equal_state_produces_no_effect() {
        let plan = plan_replace(ownership(), effect(), &Observed("same"), &Desired("same"));
        assert!(plan.is_noop());
    }

    #[test]
    fn differing_state_produces_explicit_change() {
        let plan = plan_replace(ownership(), effect(), &Observed("old"), &Desired("new"));
        assert_eq!(plan.changes().len(), 1);
        assert!(matches!(
            plan.changes(),
            [Change::Replace {
                before: "old",
                after: "new"
            }]
        ));
    }

    #[test]
    fn presence_planning_distinguishes_create_replace_and_delete() {
        let create = plan_presence(
            ownership(),
            effect(),
            &Observed::<Option<&str>>(None),
            &Desired(Some("one")),
        );
        assert!(matches!(
            create.changes(),
            [Change::Create { after: "one" }]
        ));

        let replace = plan_presence(
            ownership(),
            effect(),
            &Observed(Some("one")),
            &Desired(Some("two")),
        );
        assert!(matches!(
            replace.changes(),
            [Change::Replace {
                before: "one",
                after: "two"
            }]
        ));

        let delete = plan_presence(
            ownership(),
            effect(),
            &Observed(Some("two")),
            &Desired(None),
        );
        assert!(matches!(
            delete.changes(),
            [Change::Delete { before: "two" }]
        ));
    }
}
