from ..descriptors.base import (
    CliInstallRecipe,
    ProviderDescriptor,
    ProviderPermissions,
    VsCodeExtension,
)
from ..descriptors.registry import register

register(ProviderDescriptor(
    provider_id="qwen",
    display_name="Qwen (Alibaba)",
    cli_probe=["qwen", "--version"],
    cli_install=CliInstallRecipe("npm", "@qwen-code/qwen-code", "qwen"),
    vscode_extensions=(
        VsCodeExtension("Alibaba-Cloud.tongyi-lingma", "Tongyi Lingma"),
    ),
    permissions=ProviderPermissions(
        can_write_files=True,
        can_execute_shell=True,
        can_browse_web=False,
        can_read_env=True,
        notes="CLI agent; Alibaba Cloud account auth required",
    ),
    agent_files=(),
))
