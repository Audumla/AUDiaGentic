//! Typed domain-event vocabulary without a global event bus.
//!
//! This crate owns event identity, correlation/causation metadata, and a small
//! in-memory ordered stream primitive. Delivery, durability, fan-out, retries,
//! queues, and transport semantics stay with the application or a proven
//! adapter rather than becoming implicit platform behavior.

use std::{error::Error, fmt};

use audiagentic_core::CorrelationId;

macro_rules! define_event_id {
    ($name:ident, $label:literal) => {
        #[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash)]
        pub struct $name(String);

        impl $name {
            pub fn new(value: impl Into<String>) -> Result<Self, EventIdError> {
                let value = value.into();
                if value.trim().is_empty() {
                    return Err(EventIdError($label));
                }
                Ok(Self(value))
            }

            pub fn as_str(&self) -> &str {
                &self.0
            }
        }

        impl fmt::Display for $name {
            fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str(&self.0)
            }
        }
    };
}

define_event_id!(EventId, "event id");
define_event_id!(EventStreamId, "event stream id");
define_event_id!(CausationId, "causation id");

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EventIdError(&'static str);

impl fmt::Display for EventIdError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{} must not be empty", self.0)
    }
}

impl Error for EventIdError {}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct EventSequence(u64);

impl EventSequence {
    pub const fn new(value: u64) -> Self {
        Self(value)
    }

    pub const fn get(self) -> u64 {
        self.0
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EventEnvelope<E> {
    event_id: EventId,
    stream_id: EventStreamId,
    sequence: EventSequence,
    correlation_id: CorrelationId,
    causation_id: Option<CausationId>,
    payload: E,
}

impl<E> EventEnvelope<E> {
    pub fn event_id(&self) -> &EventId {
        &self.event_id
    }

    pub fn stream_id(&self) -> &EventStreamId {
        &self.stream_id
    }

    pub fn sequence(&self) -> EventSequence {
        self.sequence
    }

    pub fn correlation_id(&self) -> &CorrelationId {
        &self.correlation_id
    }

    pub fn causation_id(&self) -> Option<&CausationId> {
        self.causation_id.as_ref()
    }

    pub fn payload(&self) -> &E {
        &self.payload
    }

    pub fn into_payload(self) -> E {
        self.payload
    }
}

/// A small ordered event stream owned by the caller. This is intentionally not
/// a singleton publisher, subscriber registry, queue, or transport abstraction.
#[derive(Debug, Clone)]
pub struct EventStream<E> {
    stream_id: EventStreamId,
    events: Vec<EventEnvelope<E>>,
}

impl<E> EventStream<E> {
    pub fn new(stream_id: EventStreamId) -> Self {
        Self {
            stream_id,
            events: Vec::new(),
        }
    }

    pub fn stream_id(&self) -> &EventStreamId {
        &self.stream_id
    }

    pub fn len(&self) -> usize {
        self.events.len()
    }

    pub fn is_empty(&self) -> bool {
        self.events.is_empty()
    }

    pub fn last_sequence(&self) -> Option<EventSequence> {
        self.events.last().map(EventEnvelope::sequence)
    }

    pub fn append(
        &mut self,
        event_id: EventId,
        correlation_id: CorrelationId,
        causation_id: Option<CausationId>,
        payload: E,
    ) -> &EventEnvelope<E> {
        let sequence = EventSequence::new(self.events.len() as u64 + 1);
        self.events.push(EventEnvelope {
            event_id,
            stream_id: self.stream_id.clone(),
            sequence,
            correlation_id,
            causation_id,
            payload,
        });
        self.events.last().expect("event was just appended")
    }

    pub fn iter(&self) -> impl Iterator<Item = &EventEnvelope<E>> {
        self.events.iter()
    }

    pub fn after(
        &self,
        sequence: EventSequence,
    ) -> impl Iterator<Item = &EventEnvelope<E>> {
        self.events
            .iter()
            .filter(move |event| event.sequence() > sequence)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[derive(Debug, Clone, PartialEq, Eq)]
    enum JobEvent {
        Started,
        Completed,
    }

    #[test]
    fn stream_assigns_order_without_owning_delivery() {
        let mut stream = EventStream::new(EventStreamId::new("job-42").unwrap());
        let correlation = CorrelationId::new("corr-42").unwrap();

        stream.append(
            EventId::new("event-1").unwrap(),
            correlation.clone(),
            None,
            JobEvent::Started,
        );
        stream.append(
            EventId::new("event-2").unwrap(),
            correlation,
            Some(CausationId::new("command-2").unwrap()),
            JobEvent::Completed,
        );

        assert_eq!(stream.len(), 2);
        assert_eq!(stream.last_sequence(), Some(EventSequence::new(2)));
        let later = stream.after(EventSequence::new(1)).next().unwrap();
        assert_eq!(later.payload(), &JobEvent::Completed);
        assert_eq!(later.sequence().get(), 2);
    }

    #[test]
    fn event_ids_reject_empty_values() {
        assert!(EventId::new(" ").is_err());
        assert!(EventStreamId::new("").is_err());
        assert!(CausationId::new("\t").is_err());
    }
}
