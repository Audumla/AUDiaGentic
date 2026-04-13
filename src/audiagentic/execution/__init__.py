"""Job orchestration and execution domain for AUDiaGentic.

Owns prompt launching, state machines, job control, and packet execution.
Durable state (job records, session input) lives in runtime.state.
"""
