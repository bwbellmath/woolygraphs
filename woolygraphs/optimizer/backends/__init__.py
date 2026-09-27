"""
Optimizer backends.

Available backends:
- PyTorchBackend: Gradient-based optimization using PyTorch
- ForceDirectedBackend: Simple force-directed using numpy
"""

from .pytorch import PyTorchBackend, ForceDirectedBackend, TORCH_AVAILABLE

__all__ = [
    'PyTorchBackend',
    'ForceDirectedBackend',
    'TORCH_AVAILABLE',
]
