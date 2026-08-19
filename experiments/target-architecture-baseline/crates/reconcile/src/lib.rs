#![forbid(unsafe_code)]

use std::collections::{BTreeMap, BTreeSet};
use std::fmt;

use serde::de::Error as _;
use serde::{Deserialize, Deserializer, Serialize};
use thiserror::Error;

fn validate_id(raw: &str, kind: &'static str) -> Result<(), IdError> {
    if raw.is_empty() {
        return Err(IdError::Empty { kind });
    }
    if raw.trim() != raw {
        return Err(IdError::SurroundingWhitespace { kind });
    }
    Ok(())
}

#[derive(Clone, Debug, Eq, PartialEq, Error)]
pub enum IdError {
    #[error("{kind} must not be empty")]
    Empty { kind: &'static str },
    #[error("{kind} must not contain leading or trailing whitespace")]
    SurroundingWhitespace { kind: &'static str },
}

macro_rules! string_id {
    ($name:ident, $kind:literal) => {
        #[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd, Hash, Serialize)]
        #[serde(transparent)]
        pub struct $name(String);

        impl $name {
            pub fn new(value: impl Into<String>) -> Result<Self, IdError> {
                let value = value.into();
                validate_id(&value, $kind)?;
                Ok(Self(value))
            }

            pub fn as_str(&self) -> &str {
                &self.0
            }
        }

        impl fmt::Display for $name {
            fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
                formatter.write_str(&self.0)
            }
        }

        impl<'de> Deserialize<'de> for $name {
            fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
            where
                D: Deserializer<'de>,
            {
                let value = String::deserialize(deserializer)?;
                Self::new(value).map_err(D::Error::custom)
            }
        }
    };
}

string_id!(OwnerId, "owner id");
string_id!(ManagedId, "managed id");

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct DesiredItem<T> {
    pub name: String,
    pub value: T,
}

impl<T> DesiredItem<T> {
    pub fn new(name: impl Into<String>, value: T) -> Self {
        Self {
            name: name.into(),
            value,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct DesiredSet<T> {
    pub owner: OwnerId,
    pub items: BTreeMap<ManagedId, DesiredItem<T>>,
}

impl<T> DesiredSet<T> {
    pub fn new(owner: OwnerId, items: BTreeMap<ManagedId, DesiredItem<T>>) -> Self {
        Self { owner, items }
    }
}

/// Durable ownership evidence is intentionally separate from the user-owned
/// target data. Stable managed IDs may point at mutable target names.
#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
pub struct OwnershipRegistry {
    #[serde(default)]
    pub owners: BTreeMap<OwnerId, BTreeMap<ManagedId, String>>,
}

impl OwnershipRegistry {
    pub fn names_for(&self, owner: &OwnerId) -> Option<&BTreeMap<ManagedId, String>> {
        self.owners.get(owner)
    }

    fn owner_of_name(&self, name: &str) -> Option<(&OwnerId, &ManagedId)> {
        self.owners.iter().find_map(|(owner, entries)| {
            entries.iter().find_map(|(managed_id, owned_name)| {
                (owned_name == name).then_some((owner, managed_id))
            })
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum Change<T> {
    Upsert {
        managed_id: ManagedId,
        name: String,
        before: Option<T>,
        after: T,
    },
    Remove {
        managed_id: ManagedId,
        name: String,
        before: T,
    },
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum ConflictReason {
    UnmanagedCollision,
    OwnedByOther {
        owner: OwnerId,
        managed_id: ManagedId,
    },
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Conflict {
    pub managed_id: ManagedId,
    pub name: String,
    pub reason: ConflictReason,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Plan<T> {
    pub owner: OwnerId,
    pub changes: Vec<Change<T>>,
    pub conflicts: Vec<Conflict>,
    pub next_registry: OwnershipRegistry,
}

impl<T> Plan<T> {
    pub fn is_safe(&self) -> bool {
        self.conflicts.is_empty()
    }

    pub fn changed(&self) -> bool {
        !self.changes.is_empty()
    }
}

/// Plan one owner's changes without mutating the target or ownership registry.
///
/// `observed` is the user-owned target keyed by mutable target name. Ownership
/// lives only in `registry`. Unknown target entries are therefore treated as
/// user-owned and never claimed or overwritten.
pub fn plan<T>(
    desired: &DesiredSet<T>,
    observed: &BTreeMap<String, T>,
    registry: &OwnershipRegistry,
) -> Plan<T>
where
    T: Clone + PartialEq,
{
    let mut next_registry = registry.clone();
    let previous_scope = registry
        .owners
        .get(&desired.owner)
        .cloned()
        .unwrap_or_default();
    let mut changes = Vec::new();
    let mut conflicts = Vec::new();
    let mut scheduled_removals = BTreeSet::new();

    // Retire managed IDs no longer desired before considering new claims.
    for (managed_id, old_name) in &previous_scope {
        if desired.items.contains_key(managed_id) {
            continue;
        }
        if let Some(before) = observed.get(old_name) {
            changes.push(Change::Remove {
                managed_id: managed_id.clone(),
                name: old_name.clone(),
                before: before.clone(),
            });
            scheduled_removals.insert(old_name.clone());
        }
        next_registry
            .owners
            .entry(desired.owner.clone())
            .or_default()
            .remove(managed_id);
    }

    for (managed_id, item) in &desired.items {
        let old_name = previous_scope.get(managed_id).cloned();
        let existing_owner = next_registry
            .owner_of_name(&item.name)
            .map(|(owner, id)| (owner.clone(), id.clone()));
        let is_self_owned = existing_owner
            .as_ref()
            .is_some_and(|(owner, id)| owner == &desired.owner && id == managed_id);

        if let Some((owner, other_id)) = existing_owner
            && !is_self_owned
        {
            conflicts.push(Conflict {
                managed_id: managed_id.clone(),
                name: item.name.clone(),
                reason: ConflictReason::OwnedByOther {
                    owner,
                    managed_id: other_id,
                },
            });
            continue;
        }

        let observed_at_name = if scheduled_removals.contains(&item.name) {
            None
        } else {
            observed.get(&item.name)
        };
        if observed_at_name.is_some() && !is_self_owned && old_name.as_deref() != Some(&item.name) {
            conflicts.push(Conflict {
                managed_id: managed_id.clone(),
                name: item.name.clone(),
                reason: ConflictReason::UnmanagedCollision,
            });
            continue;
        }

        match observed_at_name {
            Some(before) if before != &item.value => changes.push(Change::Upsert {
                managed_id: managed_id.clone(),
                name: item.name.clone(),
                before: Some(before.clone()),
                after: item.value.clone(),
            }),
            None => changes.push(Change::Upsert {
                managed_id: managed_id.clone(),
                name: item.name.clone(),
                before: None,
                after: item.value.clone(),
            }),
            Some(_) => {}
        }

        if let Some(old_name) = old_name
            && old_name != item.name
            && !scheduled_removals.contains(&old_name)
            && let Some(before) = observed.get(&old_name)
        {
            changes.push(Change::Remove {
                managed_id: managed_id.clone(),
                name: old_name.clone(),
                before: before.clone(),
            });
            scheduled_removals.insert(old_name);
        }
        next_registry
            .owners
            .entry(desired.owner.clone())
            .or_default()
            .insert(managed_id.clone(), item.name.clone());
    }

    Plan {
        owner: desired.owner.clone(),
        changes,
        conflicts,
        next_registry,
    }
}

/// Evidence sufficient for a capability to journal or undo successfully applied
/// planned changes. Persistence and effect ordering belong to that capability.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Receipt<T> {
    pub owner: OwnerId,
    pub changes: Vec<Change<T>>,
}

impl<T: Clone> Receipt<T> {
    pub fn from_plan(plan: &Plan<T>) -> Option<Self> {
        plan.is_safe().then(|| Self {
            owner: plan.owner.clone(),
            changes: plan.changes.clone(),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn owner(value: &str) -> OwnerId {
        OwnerId::new(value).unwrap()
    }

    fn mid(value: &str) -> ManagedId {
        ManagedId::new(value).unwrap()
    }

    #[test]
    fn unknown_user_entries_are_preserved_and_cannot_be_claimed() {
        let desired = DesiredSet::new(
            owner("app-a"),
            BTreeMap::from([(mid("owned"), DesiredItem::new("user", 1))]),
        );
        let observed = BTreeMap::from([("user".to_owned(), 7), ("other".to_owned(), 9)]);

        let result = plan(&desired, &observed, &OwnershipRegistry::default());
        assert!(!result.is_safe());
        assert!(result.changes.is_empty());
        assert_eq!(result.conflicts.len(), 1);
        assert_eq!(result.conflicts[0].reason, ConflictReason::UnmanagedCollision);
    }

    #[test]
    fn stable_managed_id_can_rename_without_losing_ownership() {
        let owner = owner("app-a");
        let managed_id = mid("server-1");
        let registry = OwnershipRegistry {
            owners: BTreeMap::from([(
                owner.clone(),
                BTreeMap::from([(managed_id.clone(), "old-name".to_owned())]),
            )]),
        };
        let observed = BTreeMap::from([("old-name".to_owned(), 1)]);
        let desired = DesiredSet::new(
            owner.clone(),
            BTreeMap::from([(managed_id.clone(), DesiredItem::new("new-name", 2))]),
        );

        let result = plan(&desired, &observed, &registry);
        assert!(result.is_safe());
        assert!(result.changes.iter().any(|change| matches!(
            change,
            Change::Upsert {
                name,
                before: None,
                after: 2,
                ..
            } if name == "new-name"
        )));
        assert!(result.changes.iter().any(|change| matches!(
            change,
            Change::Remove {
                name,
                before: 1,
                ..
            } if name == "old-name"
        )));
        assert_eq!(
            result
                .next_registry
                .names_for(&owner)
                .unwrap()
                .get(&managed_id),
            Some(&"new-name".to_owned())
        );
    }

    #[test]
    fn another_owner_reserves_its_managed_name() {
        let other_owner = owner("app-b");
        let registry = OwnershipRegistry {
            owners: BTreeMap::from([(
                other_owner.clone(),
                BTreeMap::from([(mid("other-id"), "shared".to_owned())]),
            )]),
        };
        let desired = DesiredSet::new(
            owner("app-a"),
            BTreeMap::from([(mid("mine"), DesiredItem::new("shared", 1))]),
        );
        let observed = BTreeMap::from([("shared".to_owned(), 9)]);

        let result = plan(&desired, &observed, &registry);
        assert!(!result.is_safe());
        assert!(matches!(
            result.conflicts[0].reason,
            ConflictReason::OwnedByOther { .. }
        ));
    }

    #[test]
    fn removing_a_retired_managed_id_never_removes_unknown_entries() {
        let owner = owner("app-a");
        let managed_id = mid("old");
        let registry = OwnershipRegistry {
            owners: BTreeMap::from([(
                owner.clone(),
                BTreeMap::from([(managed_id, "owned".to_owned())]),
            )]),
        };
        let observed = BTreeMap::from([("owned".to_owned(), 1), ("user".to_owned(), 2)]);
        let desired = DesiredSet::<i32>::new(owner, BTreeMap::new());

        let result = plan(&desired, &observed, &registry);
        assert!(result.is_safe());
        assert_eq!(result.changes.len(), 1);
        assert!(matches!(
            &result.changes[0],
            Change::Remove { name, .. } if name == "owned"
        ));
    }
}
