from audiagentic.foundation.config.merge import deep_merge

from .component_paths import load_component_paths, resolve_component_path
from .package import REPO_ROOT, SRC_ROOT, find_repo_root
from .project import find_project_root
from .resolution import (
    build_layered_path_map,
    iter_layered_candidates,
    load_layered_mapping,
    resolve_existing_dir,
    resolve_existing_file,
    resolve_required_dir,
    resolve_required_file,
)

__all__ = [
    "REPO_ROOT",
    "SRC_ROOT",
    "build_layered_path_map",
    "deep_merge",
    "find_project_root",
    "find_repo_root",
    "iter_layered_candidates",
    "load_component_paths",
    "load_layered_mapping",
    "resolve_component_path",
    "resolve_existing_dir",
    "resolve_existing_file",
    "resolve_required_dir",
    "resolve_required_file",
]
