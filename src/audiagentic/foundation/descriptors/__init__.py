"""Foundation descriptor loading mechanism.

Provides the generic mechanism used by all descriptor types:
    load YAML → resolve dotpath hooks → build step tree → construct typed descriptor

Submodules:
    resolver: Dotpath reference resolution (module:object)
    steps: Workflow step builder from declarative specs
    loader: YAML file loading with DescriptorSpec field maps
    registry: Generic typed descriptor registry
"""
from .loader import DescriptorSpec, iter_descriptor_files, load_descriptor
from .registry import DescriptorRegistry
from .resolver import resolve_ref
from .steps import build_step_from_spec, build_toolchain_step

__all__ = [
    "DescriptorRegistry",
    "DescriptorSpec",
    "build_step_from_spec",
    "build_toolchain_step",
    "iter_descriptor_files",
    "load_descriptor",
    "resolve_ref",
]
