# Application platform spike validation

The temporary PR-only formatter used during spike development was removed before final validation. The final candidate is validated through the normal `rust-production-foundation` workflow on the clean production tree.

Validation must cover Rust 1.95 formatting, strict Clippy, workspace tests, all executable composition proofs, dependency-direction gates, and Linux/macOS/Windows architecture jobs.
