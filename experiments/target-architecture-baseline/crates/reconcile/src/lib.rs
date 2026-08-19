#![forbid(unsafe_code)]

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd, Hash, Serialize, Deserialize)]
#[serde(transparent)]
pub struct OwnerId(String);

impl OwnerId {
    pub fn new(value: impl Into<String>) -> Result<Self, OwnerIdError> {
        let value = value.into();
        if value.is_empty() {
            return Err(OwnerIdError::Empty);
        }
        if value.trim() != value {
            return Err(OwnerIdError::SurroundingWhitespace);
        }
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Error)]
pub enum OwnerIdError {
    #[error("owner id must not be empty")]
    Empty,
    #[error("owner id must not contain leading or trailing whitespace")]
    SurroundingWhitespace,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum ObservedItem<T> {
    Unmanaged(T),
    Managed { owner: OwnerId, value: T },
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct DesiredSet<T> {
    pub owner: OwnerId,
    pub items: BTreeMap<String, T>,
}

impl<T> DesiredSet<T> {
    pub fn new(owner: OwnerId, items: BTreeMap<String, T>) -> Self {
        Self { owner, items }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Change<T> {
    Create { key: String, after: T },
    Update { key: String, before: T, after: T },
    Remove { key: String, before: T },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ConflictReason {
    UnmanagedCollision,
    OwnedByOther { owner: OwnerId },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Conflict {
    pub key: String,
    pub desired_owner: OwnerId,
    pub reason: ConflictReason,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Plan<T> {
    pub owner: OwnerId,
    pub changes: Vec<Change<T>>,
    pub conflicts: Vec<Conflict>,
}

impl<T> Plan<T> {
    pub fn is_safe(&self) -> bool {
        self.conflicts.is_empty()
    }
}

/// Plan the changes necessary for one owner without claiming or deleting data
/// that is unmanaged or belongs to another owner.
pub fn plan<T>(desired: &DesiredSet<T>, observed: &BTreeMap<String, ObservedItem<T>>) -> Plan<T>
where
    T: Clone + PartialEq,
{
    let mut changes = Vec::new();
    let mut conflicts = Vec::new();

    for (key, desired_value) in &desired.items {
        match observed.get(key) {
            None => changes.push(Change::Create {
                key: key.clone(),
                after: desired_value.clone(),
            }),
            Some(ObservedItem::Unmanaged(_)) => conflicts.push(Conflict {
                key: key.clone(),
                desired_owner: desired.owner.clone(),
                reason: ConflictReason::UnmanagedCollision,
            }),
            Some(ObservedItem::Managed { owner, .. }) if owner != &desired.owner => {
                conflicts.push(Conflict {
                    key: key.clone(),
                    desired_owner: desired.owner.clone(),
                    reason: ConflictReason::OwnedByOther {
                        owner: owner.clone(),
                    },
                });
            }
            Some(ObservedItem::Managed { value, .. }) if value != desired_value => {
                changes.push(Change::Update {
                    key: key.clone(),
                    before: value.clone(),
                    after: desired_value.clone(),
                });
            }
            Some(ObservedItem::Managed { .. }) => {}
        }
    }

    for (key, observed_item) in observed {
        if desired.items.contains_key(key) {
            continue;
        }
        if let ObservedItem::Managed { owner, value } = observed_item
            && owner == &desired.owner
        {
            changes.push(Change::Remove {
                key: key.clone(),
                before: value.clone(),
            });
        }
    }

    Plan {
        owner: desired.owner.clone(),
        changes,
        conflicts,
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct AppliedChange<T> {
    pub key: String,
    pub owner: OwnerId,
    pub before: Option<T>,
    pub after: Option<T>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Receipt<T> {
    pub applied: Vec<AppliedChange<T>>,
}

impl<T> Receipt<T> {
    pub fn new(applied: Vec<AppliedChange<T>>) -> Self {
        Self { applied }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn owner(value: &str) -> OwnerId {
        OwnerId::new(value).unwrap()
    }

    #[test]
    fn creates_updates_and_removes_only_the_callers_owned_items() {
        let desired = DesiredSet::new(
            owner("app-a"),
            BTreeMap::from([
                ("create".to_owned(), 1),
                ("update".to_owned(), 2),
                ("same".to_owned(), 3),
            ]),
        );
        let observed = BTreeMap::from([
            (
                "update".to_owned(),
                ObservedItem::Managed {
                    owner: owner("app-a"),
                    value: 1,
                },
            ),
            (
                "same".to_owned(),
                ObservedItem::Managed {
                    owner: owner("app-a"),
                    value: 3,
                },
            ),
            (
                "remove".to_owned(),
                ObservedItem::Managed {
                    owner: owner("app-a"),
                    value: 4,
                },
            ),
            ("user".to_owned(), ObservedItem::Unmanaged(9)),
            (
                "other".to_owned(),
                ObservedItem::Managed {
                    owner: owner("app-b"),
                    value: 10,
                },
            ),
        ]);

        let result = plan(&desired, &observed);
        assert!(result.is_safe());
        assert_eq!(result.changes.len(), 3);
        assert!(result.changes.iter().any(|change| matches!(change, Change::Create { key, .. } if key == "create")));
        assert!(result.changes.iter().any(|change| matches!(change, Change::Update { key, .. } if key == "update")));
        assert!(result.changes.iter().any(|change| matches!(change, Change::Remove { key, .. } if key == "remove")));
    }

    #[test]
    fn refuses_to_claim_unmanaged_or_other_owned_keys() {
        let desired = DesiredSet::new(
            owner("app-a"),
            BTreeMap::from([("user".to_owned(), 1), ("other".to_owned(), 2)]),
        );
        let observed = BTreeMap::from([
            ("user".to_owned(), ObservedItem::Unmanaged(7)),
            (
                "other".to_owned(),
                ObservedItem::Managed {
                    owner: owner("app-b"),
                    value: 8,
                },
            ),
        ]);

        let result = plan(&desired, &observed);
        assert!(!result.is_safe());
        assert_eq!(result.changes.len(), 0);
        assert_eq!(result.conflicts.len(), 2);
    }
}
