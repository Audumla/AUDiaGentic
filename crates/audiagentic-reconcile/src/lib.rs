//! Reconciliation vocabulary and pure planning primitives.
//!
//! I/O, retries, and ownership enforcement belong to the caller/host. This
//! crate provides explicit observed/desired state, plans, effects, and receipts.

use std::{error::Error, fmt};

macro_rules! define_reconcile_id {
    ($name:ident) => {
        #[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash)]
        pub struct $name(String);

        impl $name {
            pub fn new(value: impl Into<String>) -> Result<Self, ReconcileIdError> {
                let value = value.into();
                if value.trim().is_empty() {
                    return Err(ReconcileIdError(stringify!($name)));
                }
                Ok(Self(value))
            }

            pub fn as_str(&self) -> &str {
                &self.0
            }
        }
    };
}

define_reconcile_id!(OwnershipId);
define_reconcile_id!(EffectId);

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReconcileIdError(&'static str);

impl fmt::Display for ReconcileIdError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{} must not be empty", self.0)
    }
}

impl Error for ReconcileIdError {}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Observed<T>(pub T);

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Desired<T>(pub T);

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Change<T> {
    Replace { before: T, after: T },
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn equal_state_produces_no_effect() {
        let plan = plan_replace(
            OwnershipId::new("owner").unwrap(),
            EffectId::new("effect").unwrap(),
            &Observed("same"),
            &Desired("same"),
        );
        assert!(plan.is_noop());
    }

    #[test]
    fn differing_state_produces_explicit_change() {
        let plan = plan_replace(
            OwnershipId::new("owner").unwrap(),
            EffectId::new("effect").unwrap(),
            &Observed("old"),
            &Desired("new"),
        );
        assert_eq!(plan.changes().len(), 1);
    }
}
