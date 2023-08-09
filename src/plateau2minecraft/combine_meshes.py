import numpy as np

from plateau2minecraft.types import TriangleMesh


# 利用していない
def combine(meshs: list[TriangleMesh]) -> TriangleMesh:
    vertices = []
    triangles = []
    max_index = 0
    for mesh in meshs:
        vertices.extend(mesh.vertices)

        t = np.asarray(mesh.triangles, dtype=np.int32)
        t += max_index
        triangles.extend(t)

        max_index += np.asarray(triangles).max() + 1

    return TriangleMesh(vertices, triangles)
