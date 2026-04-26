from __future__ import annotations

import warnings

# Optional EventBus integration (task-0281)
try:
    from audiagentic.interoperability import DeliveryMode, get_bus
    from audiagentic.planning.app.propagation import StatePropagationEngine

    EVENT_BUS_ENABLED = True
except ImportError:
    EVENT_BUS_ENABLED = False
    DeliveryMode = None  # type: ignore
    StatePropagationEngine = None  # type: ignore


_propagation_subscriptions: dict[str, object] = {}


class EventService:
    def __init__(self, api):
        self.api = api
        self.propagation_engine = None
        self.propagation_subscription = None

    def initialize(self) -> None:
        if EVENT_BUS_ENABLED and StatePropagationEngine is not None:
            try:
                config_path = (
                    self.api.root / ".audiagentic" / "planning" / "config" / "state_propagation.yaml"
                )
                self.propagation_engine = StatePropagationEngine(
                    planning_api=self.api,
                    enabled=True,
                    config_path=config_path,
                )
                root_key = str(self.api.root.resolve())
                bus = get_bus()
                old = _propagation_subscriptions.get(root_key)
                if old is not None:
                    try:
                        bus.unsubscribe(old)
                    except Exception:
                        pass
                self.propagation_subscription = bus.subscribe(
                    "planning.item.state.changed",
                    self.on_state_change_for_propagation,
                )
                _propagation_subscriptions[root_key] = self.propagation_subscription
            except Exception as e:
                warnings.warn(
                    f"State propagation engine initialization failed: {e}", RuntimeWarning
                )

        if EVENT_BUS_ENABLED:
            try:
                from audiagentic.knowledge import setup_event_subscriptions

                setup_event_subscriptions()
            except ImportError:
                pass
            except Exception as e:
                warnings.warn(f"Knowledge event subscription setup failed: {e}", RuntimeWarning)

    def publish_event(
        self,
        event_type: str,
        payload: dict,
        metadata: dict | None = None,
        mode=None,
    ) -> None:
        self.api.events.emit(event_type, payload)

        if not EVENT_BUS_ENABLED:
            return

        try:
            bus = get_bus()
            bus.publish(
                event_type=event_type,
                payload=payload,
                metadata=metadata or {},
                mode=mode if mode is not None else DeliveryMode.ASYNC,
            )
        except Exception as e:
            warnings.warn(f"Event publish failed for {event_type}: {e}", RuntimeWarning)

    def on_state_change_for_propagation(
        self,
        event_type: str,
        payload: dict,
        metadata: dict,
    ) -> None:
        if not self.propagation_engine:
            return

        item_id = payload.get("id")
        new_state = payload.get("new_state")

        if not item_id or not new_state:
            return

        propagation_depth = metadata.get("propagation_depth", 0)
        max_depth = 10
        if self.propagation_engine._config:
            max_depth = self.propagation_engine._config.get("global", {}).get("max_depth", 10)

        if propagation_depth >= max_depth:
            return

        propagations = self.propagation_engine.propagate(item_id, new_state, metadata)
        if not propagations:
            return

        for target_id, target_kind, target_state in propagations:
            self.propagation_engine.apply_propagation(
                target_id=target_id,
                target_state=target_state,
                source_id=item_id,
                source_state=new_state,
                metadata=metadata,
            )

    def sync_delivery_mode(self):
        if DeliveryMode is None:
            return None
        return DeliveryMode.SYNC
