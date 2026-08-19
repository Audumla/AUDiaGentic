use std::{collections::BTreeMap, fmt};

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct OwnershipId(String);

impl OwnershipId {
    pub fn new(value: impl Into<String>) -> Result<Self, ReconcileError> {
        let value = value.into();
        if value.trim().is_empty() {
            return Err(ReconcileError::InvalidOwnershipId);
        }
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Observed<T> {
    pub value: T,
    pub owner: Option<OwnershipId>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Change<T> {
    Upsert {
        key: String,
        before: Option<T>,
        after: T,
    },
    Remove {
        key: String,
        before: T,
    },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Plan<T> {
    pub owner: OwnershipId,
    pub changes: Vec<Change<T>>,
}

impl<T> Plan<T> {
    pub fn is_empty(&self) -> bool {
        self.changes.is_empty()
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ReconcileError {
    InvalidOwnershipId,
    OwnershipConflict {
        key: String,
        existing_owner: Option<OwnershipId>,
    },
}

impl fmt::Display for ReconcileError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidOwnershipId => f.write_str("ownership id must not be empty"),
            Self::OwnershipConflict {
                key,
                existing_owner,
            } => match existing_owner {
                Some(owner) => write!(f, "cannot reconcile {key}: owned by {}", owner.as_str()),
                None => write!(f, "cannot reconcile {key}: existing value is user-owned"),
            },
        }
    }
}

impl std::error::Error for ReconcileError {}

pub fn plan_owned_map<T>(
    owner: OwnershipId,
    observed: &BTreeMap<String, Observed<T>>,
    desired: &BTreeMap<String, T>,
) -> Result<Plan<T>, ReconcileError>
where
    T: Clone + Eq,
{
    let mut changes = Vec::new();

    for (key, wanted) in desired {
        match observed.get(key) {
            None => changes.push(Change::Upsert {
                key: key.clone(),
                before: None,
                after: wanted.clone(),
            }),
            Some(existing) if existing.owner.as_ref() == Some(&owner) => {
                if existing.value != *wanted {
                    changes.push(Change::Upsert {
                        key: key.clone(),
                        before: Some(existing.value.clone()),
                        after: wanted.clone(),
                    });
                }
            }
            Some(existing) if existing.value == *wanted => {}
            Some(existing) => {
                return Err(ReconcileError::OwnershipConflict {
                    key: key.clone(),
                    existing_owner: existing.owner.clone(),
                });
            }
        }
    }

    for (key, existing) in observed {
        if existing.owner.as_ref() == Some(&owner) && !desired.contains_key(key) {
            changes.push(Change::Remove {
                key: key.clone(),
                before: existing.value.clone(),
            });
        }
    }

    Ok(Plan { owner, changes })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn preserves_unknown_user_state_and_removes_only_owned_state() {
        let owner = OwnershipId::new("app/config").unwrap();
        let observed = BTreeMap::from([
            (
                "owned-old".into(),
                Observed {
                    value: "old",
                    owner: Some(owner.clone()),
                },
            ),
            (
                "user-value".into(),
                Observed {
                    value: "keep",
                    owner: None,
                },
            ),
        ]);
        let desired = BTreeMap::from([("owned-new".into(), "new")]);
        let plan = plan_owned_map(owner, &observed, &desired).unwrap();
        assert_eq!(plan.changes.len(), 2);
        assert!(
            plan.changes
                .iter()
                .any(|change| matches!(change, Change::Remove { key, .. } if key == "owned-old"))
        );
        assert!(
            !plan
                .changes
                .iter()
                .any(|change| matches!(change, Change::Remove { key, .. } if key == "user-value"))
        );
    }

    #[test]
    fn refuses_to_overwrite_user_owned_value() {
        let owner = OwnershipId::new("app/config").unwrap();
        let observed = BTreeMap::from([(
            "shared".into(),
            Observed {
                value: "user",
                owner: None,
            },
        )]);
        let desired = BTreeMap::from([("shared".into(), "ours")]);
        assert!(matches!(
            plan_owned_map(owner, &observed, &desired),
            Err(ReconcileError::OwnershipConflict { key, existing_owner: None }) if key == "shared"
        ));
    }
}
