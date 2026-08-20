use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct OwnedValue<T> {
    pub owner: String,
    pub value: T,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum Change<T> {
    Create { desired: OwnedValue<T> },
    Update { before: OwnedValue<T>, desired: OwnedValue<T> },
    Remove { before: OwnedValue<T> },
    Noop,
    Conflict { current_owner: String, desired_owner: String },
}

pub fn plan<T>(observed: Option<OwnedValue<T>>, desired: Option<OwnedValue<T>>) -> Change<T>
where
    T: Clone + PartialEq,
{
    match (observed, desired) {
        (None, None) => Change::Noop,
        (None, Some(desired)) => Change::Create { desired },
        (Some(before), None) => Change::Remove { before },
        (Some(before), Some(desired)) if before.owner != desired.owner => Change::Conflict {
            current_owner: before.owner,
            desired_owner: desired.owner,
        },
        (Some(before), Some(desired)) if before.value == desired.value => Change::Noop,
        (Some(before), Some(desired)) => Change::Update { before, desired },
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Receipt<B, A> {
    pub owner: String,
    pub before: B,
    pub after: A,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn foreign_ownership_conflicts_instead_of_overwriting() {
        let observed = OwnedValue { owner: "user".into(), value: 1 };
        let desired = OwnedValue { owner: "app".into(), value: 2 };
        assert!(matches!(plan(Some(observed), Some(desired)), Change::Conflict { .. }));
    }

    #[test]
    fn same_owner_can_update() {
        let observed = OwnedValue { owner: "app".into(), value: 1 };
        let desired = OwnedValue { owner: "app".into(), value: 2 };
        assert!(matches!(plan(Some(observed), Some(desired)), Change::Update { .. }));
    }
}
