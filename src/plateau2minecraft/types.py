from dataclasses import dataclass

import numpy as np


@dataclass
class TriangleMesh:
    vertices: list[np.ndarray]
    triangles: list[np.ndarray]
