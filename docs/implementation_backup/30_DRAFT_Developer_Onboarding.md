# DRAFT Developer Onboarding

> Draft guidance only. Not an MVP blocker.

## Quick start for implementors

1. Read `00_Implementation_Index.md`.
2. Read `13_Packet_Execution_Rules.md`.
3. Read your assigned packet and all direct dependency packets.
4. Run validators before opening a PR.
5. Do not change shared contracts unless the change-control rules explicitly allow it.

## Packet development order

1. data structures / schemas
2. pure logic
3. CLI or wrapper layer
4. fixtures
5. tests
6. documentation delta if required by your packet

## Stop conditions

Stop and escalate if:
- you need to change a file your packet does not own
- you think a contract needs to change
- you cannot satisfy acceptance criteria without widening scope
