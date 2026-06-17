# foundation/workflow/propagation/

Config-driven state propagation engine.

## Intent

Keep parent/child workflow state transitions consistent across planning-style hierarchies.

## Capabilities

- Define propagation rules and configuration.
- Walk parent relationships.
- Heal inconsistent state.
- Record propagation logs.
- Apply propagation through `engine.py` and expose helpers through `workflow_item_api.py`.

Use this area when changing how child state affects parent state or how repair logic resolves broken hierarchies.
