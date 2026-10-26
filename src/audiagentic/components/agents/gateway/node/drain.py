"""Server-local historical work evidence; never a node-claimed eligibility lookup."""

from __future__ import annotations

from audiagentic.components.agents.gateway import store
from audiagentic.components.agents.gateway.service.shared_config import (
    SharedGatewayServerConfig,
    SharedNodeGrant,
)
from audiagentic.foundation.system.managed_service import ManagedServiceStore

from .checkpoints import NodeReceiptCheckpoints
from .contracts import CommandIdentity, conflict


class NodeDrainEligibility:
    """Configured canonical roots and fixed service custody, read without owner locks.

    Caller authenticates the enrolled credential FIRST under grant serialization.
    This object grants historical transport only, never output read permission,
    effect authority, preparation, or rebind. No wire IDs/cursors/roots are inputs.
    """

    def __init__(self, config: SharedGatewayServerConfig, service_store: ManagedServiceStore):
        from audiagentic.components.agents.gateway.service.contract import GATEWAY_SERVICE_KEY

        expected = ManagedServiceStore(GATEWAY_SERVICE_KEY, root=config.service_root)
        if (
            service_store.key != expected.key
            or service_store.root.resolve() != expected.root.resolve()
        ):
            raise conflict(1, "Drain custody store does not match configured gateway service")
        self.server_id = config.server_id
        self.projects = {key: root.resolve(strict=True) for key, root in config.projects.items()}
        self.service_store = service_store

    def eligible(self, config: SharedGatewayServerConfig, grant: SharedNodeGrant) -> bool:
        from audiagentic.components.agents.gateway.service.contract import GATEWAY_SERVICE_KEY

        if (
            config.server_id != self.server_id
            or ManagedServiceStore(GATEWAY_SERVICE_KEY, root=config.service_root).root.resolve()
            != self.service_store.root.resolve()
            or {key: root.resolve(strict=True) for key, root in config.projects.items()}
            != self.projects
        ):
            raise conflict(1, "Drain configured server/project scope changed")
        # This cursor was committed only AFTER canonical application by the
        # existing custody owner. It is historical server/node proof, not a
        # claimed log or an authorization to read any client's output.
        if (
            NodeReceiptCheckpoints(
                self.service_store, server_id=self.server_id, node_id=grant.node_id
            ).peek()
            is not None
        ):
            return True
        for workspace, project in grant.workspaces.items():
            root = self.projects.get(project)
            if root is None:
                continue
            for record in store.list_records(root, include_output=False):
                placement, dispatch = record.get("node-placement"), record.get("node-dispatch")
                if not isinstance(placement, dict) or not isinstance(dispatch, dict):
                    continue
                if (
                    placement.get("node-id") != grant.node_id
                    or placement.get("workspace-id") != workspace
                    or placement.get("server-project-id") != project
                    or placement.get("principal-id") not in grant.principals
                    or not dispatch.get("attestation-sha256")
                ):
                    continue
                identity = CommandIdentity.from_mapping(dispatch["identity"])
                if (
                    identity.node_id == grant.node_id
                    and identity.workspace_id == workspace
                    and identity.request_id == record["request-id"]
                    and identity.execution_profile_id == record["execution-profile-id"]
                    and identity.grant_revision == placement["grant-revision"]
                    and identity.grant_revision <= grant.revision
                ):
                    return True
        return False
