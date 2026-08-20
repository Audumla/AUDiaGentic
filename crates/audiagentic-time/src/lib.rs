//! Deterministic deadline and timer semantics without a scheduler runtime.
//!
//! Callers supply the current timestamp explicitly. This crate never sleeps,
//! spawns tasks, owns a clock, or registers global timers.

use std::{
    collections::BTreeMap,
    error::Error,
    fmt,
    time::Duration,
};

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Timestamp(u64);

impl Timestamp {
    pub const fn from_millis(value: u64) -> Self {
        Self(value)
    }

    pub const fn as_millis(self) -> u64 {
        self.0
    }

    pub fn checked_add(self, duration: Duration) -> Option<Self> {
        let millis = u64::try_from(duration.as_millis()).ok()?;
        self.0.checked_add(millis).map(Self)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Deadline(Timestamp);

impl Deadline {
    pub const fn at(timestamp: Timestamp) -> Self {
        Self(timestamp)
    }

    pub const fn timestamp(self) -> Timestamp {
        self.0
    }

    pub const fn is_due(self, now: Timestamp) -> bool {
        now.0 >= self.0.0
    }
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct TimerId(String);

impl TimerId {
    pub fn new(value: impl Into<String>) -> Result<Self, TimerIdError> {
        let value = value.into();
        if value.trim().is_empty() {
            return Err(TimerIdError);
        }
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TimerIdError;

impl fmt::Display for TimerIdError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("timer id must not be empty")
    }
}

impl Error for TimerIdError {}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TimerSet {
    timers: BTreeMap<TimerId, Deadline>,
}

impl TimerSet {
    pub fn new() -> Self {
        Self {
            timers: BTreeMap::new(),
        }
    }

    pub fn len(&self) -> usize {
        self.timers.len()
    }

    pub fn is_empty(&self) -> bool {
        self.timers.is_empty()
    }

    pub fn arm(&mut self, id: TimerId, deadline: Deadline) -> Option<Deadline> {
        self.timers.insert(id, deadline)
    }

    pub fn cancel(&mut self, id: &TimerId) -> Option<Deadline> {
        self.timers.remove(id)
    }

    pub fn deadline(&self, id: &TimerId) -> Option<Deadline> {
        self.timers.get(id).copied()
    }

    pub fn next_deadline(&self) -> Option<Deadline> {
        self.timers.values().copied().min()
    }

    pub fn due(&self, now: Timestamp) -> Vec<TimerId> {
        let mut due = self
            .timers
            .iter()
            .filter(|(_, deadline)| deadline.is_due(now))
            .map(|(id, deadline)| (deadline.timestamp(), id.clone()))
            .collect::<Vec<_>>();
        due.sort();
        due.into_iter().map(|(_, id)| id).collect()
    }

    pub fn drain_due(&mut self, now: Timestamp) -> Vec<TimerId> {
        let due = self.due(now);
        for id in &due {
            self.timers.remove(id);
        }
        due
    }
}

impl Default for TimerSet {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn deadlines_are_evaluated_from_caller_supplied_time() {
        let deadline = Deadline::at(Timestamp::from_millis(100));
        assert!(!deadline.is_due(Timestamp::from_millis(99)));
        assert!(deadline.is_due(Timestamp::from_millis(100)));
        assert!(deadline.is_due(Timestamp::from_millis(101)));
    }

    #[test]
    fn timer_set_orders_and_drains_due_timers_deterministically() {
        let mut timers = TimerSet::new();
        timers.arm(
            TimerId::new("later").unwrap(),
            Deadline::at(Timestamp::from_millis(20)),
        );
        timers.arm(
            TimerId::new("first-b").unwrap(),
            Deadline::at(Timestamp::from_millis(10)),
        );
        timers.arm(
            TimerId::new("first-a").unwrap(),
            Deadline::at(Timestamp::from_millis(10)),
        );

        assert_eq!(
            timers.due(Timestamp::from_millis(10)),
            vec![
                TimerId::new("first-a").unwrap(),
                TimerId::new("first-b").unwrap()
            ]
        );
        assert_eq!(timers.drain_due(Timestamp::from_millis(10)).len(), 2);
        assert_eq!(timers.len(), 1);
        assert_eq!(
            timers.next_deadline(),
            Some(Deadline::at(Timestamp::from_millis(20)))
        );
    }
}
