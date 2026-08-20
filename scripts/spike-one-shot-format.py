from pathlib import Path


def replace_once(path: str, old: str, new: str, already: str) -> None:
    target = Path(path)
    source = target.read_text()
    if already in source:
        return
    if old not in source:
        raise SystemExit(f"review patch target not found in {path}")
    target.write_text(source.replace(old, new, 1))


replace_once(
    "crates/audiagentic-events/src/lib.rs",
    '''        let Some(oldest) = self.oldest_sequence() else {\n            return Ok(EventPage {\n                events: Vec::new(),\n                next_cursor: cursor,\n                has_more: false,\n            });\n        };\n''',
    '''        let Some(oldest) = self.oldest_sequence() else {\n            if cursor.get() > 0 {\n                return Err(EventStreamError::CursorAhead {\n                    cursor,\n                    latest_available: EventSequence::new(0),\n                });\n            }\n            return Ok(EventPage {\n                events: Vec::new(),\n                next_cursor: cursor,\n                has_more: false,\n            });\n        };\n''',
    "latest_available: EventSequence::new(0)",
)

replace_once(
    "crates/audiagentic-events/src/lib.rs",
    '''    #[test]\n    fn event_ids_reject_empty_values() {\n''',
    '''    #[test]\n    fn empty_stream_rejects_a_cursor_ahead_of_sequence_zero() {\n        let stream = EventStream::<JobEvent>::new(EventStreamId::new("empty").unwrap());\n        assert!(matches!(\n            stream.page_after(EventCursor::new(1), 1),\n            Err(EventStreamError::CursorAhead {\n                latest_available,\n                ..\n            }) if latest_available == EventSequence::new(0)\n        ));\n    }\n\n    #[test]\n    fn event_ids_reject_empty_values() {\n''',
    "empty_stream_rejects_a_cursor_ahead_of_sequence_zero",
)

replace_once(
    "examples/platform-app/src/main.rs",
    '''    assert_eq!(workflow.status(), WorkflowStatus::Completed);\n\n    assert!(matches!(\n''',
    '''    assert_eq!(workflow.status(), WorkflowStatus::Completed);\n    assert!(events.iter().any(|event| matches!(\n        event.payload(),\n        PlatformEvent::ChildRoundTrip(value) if value == "platform:ping"\n    )));\n\n    assert!(matches!(\n''',
    'PlatformEvent::ChildRoundTrip(value) if value == "platform:ping"',
)
