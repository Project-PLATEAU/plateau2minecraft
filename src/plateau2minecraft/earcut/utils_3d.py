import math
from typing import Optional

import numpy as np


def _normal(a: np.ndarray) -> Optional[np.ndarray]:
    b = np.roll(a, -1, axis=0)
    n = np.average(np.cross(a - b, a + b), axis=0)
    d = np.linalg.norm(n)
    if d < 1e-7:
        return None
    else:
        return n / d


def _project_to_2d(normal: np.ndarray, vertices: np.ndarray) -> np.ndarray:
    nx, ny = normal[:2]
    dd = (nx**2 + ny**2) ** 0.5
    if dd < 1e-8:
        return vertices[:, :2]
    ax: float = -ny / dd
    ay: float = nx / dd
    theta = math.acos(normal[2])
    sint = math.sin(theta)
    cost = math.cos(theta)
    s = ax * ay * (1 - cost)
    t = ay * sint
    u = ax * sint
    R = np.array(
        [
            [ax * ax * (1 - cost) + cost, s, t],
            [s, ay * ay * (1 - cost) + cost, -u],
            [-t, u, cost],
        ]
    )
    return (vertices @ R)[:, :2]


def project3d_to_2d(data, num_outer: int) -> Optional[np.ndarray]:
    d = data.reshape(-1, 3)
    norm = _normal(d[:num_outer])
    if norm is None:
        return None
    return _project_to_2d(norm, d).flatten()
