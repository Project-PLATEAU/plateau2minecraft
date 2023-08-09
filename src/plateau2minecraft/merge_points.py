import numpy as np
from trimesh.points import PointCloud


def merge(points: list[PointCloud]) -> PointCloud:
    return PointCloud(np.vstack([point.vertices for point in points]), np.vstack([point.colors for point in points]))
