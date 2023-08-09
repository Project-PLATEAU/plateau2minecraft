from multiprocessing import Pool

import numpy as np
import trimesh.voxel
import trimesh.voxel.encoding
from trimesh import PointCloud, Trimesh
from trimesh.remesh import subdivide_to_size

from plateau2minecraft.types import TriangleMesh


def _draw_line(dense, size, start, end):
    current_voxel = np.floor(start + 0.5).astype(np.int32)
    last_x, last_y, last_z = np.floor(end + 0.5).astype(np.int32)
    ray = end - start

    step = np.where(ray >= 0, 1, -1)
    next_voxel_boundary = current_voxel + 0.5 * step
    (step_x, step_y, step_z) = step
    (tmax_x, tmax_y, tmax_z) = np.where(ray != 0, np.divide(next_voxel_boundary - start, ray, where=ray != 0), np.inf)
    (tdelta_x, tdelta_y, tdelta_z) = np.where(ray != 0, np.divide(step, ray, where=ray != 0), np.inf)
    cur_x, cur_y, cur_z = current_voxel
    if (0 <= cur_x <= size) and (0 <= cur_y < size) and (0 <= cur_z < size):
        dense[cur_x, cur_y, cur_z] = True

    while cur_x != last_x or cur_y != last_y or cur_z != last_z:
        if tmax_x < tmax_y:
            if tmax_x < tmax_z:
                cur_x += step_x
                tmax_x += tdelta_x
            else:
                cur_z += step_z
                tmax_z += tdelta_z
        else:
            if tmax_y < tmax_z:
                cur_y += step_y
                tmax_y += tdelta_y
            else:
                cur_z += step_z
                tmax_z += tdelta_z

        if (0 <= cur_x <= size) and (0 <= cur_y < size) and (0 <= cur_z < size):
            dense[cur_x, cur_y, cur_z] = True


def _fill_triangle(dense, size, tri):
    boxsize = np.max(tri, axis=0) - np.min(tri, axis=0)

    if (
        np.all(np.abs(tri[1] - tri[0]) < 1)
        and np.all(np.abs(tri[2] - tri[0]) < 1)
        and np.all(np.abs(tri[1] - tri[2]) < 1)
    ):
        # FIXME:
        # print("WARN: point")
        return

    norm = np.cross(tri[1] - tri[0], tri[2] - tri[0])
    norm = norm / np.linalg.norm(norm)
    # print(f"norm={norm}")

    norm_axis = (
        (0 if abs(norm[0]) > abs(norm[2]) else 2)
        if abs(norm[0]) > abs(norm[1])
        else (1 if abs(norm[1]) > abs(norm[2]) else 2)
    )
    # print(f"{norm_axis=}")

    # norm_axis=0 (x) --> yz-plane
    # norm_axis=1 (y) --> zx-plane
    # norm_axis=2 (z) --> xy-plane
    if norm_axis == 0:
        scan_axis = 1 if boxsize[1] >= boxsize[2] else 2
    elif norm_axis == 1:
        scan_axis = 2 if boxsize[2] >= boxsize[0] else 0
    else:
        scan_axis = 0 if boxsize[0] >= boxsize[1] else 1

    if scan_axis == 0:
        # sort vertices
        if tri[0, 0] > tri[1, 0]:
            tri[(0, 1), :] = tri[(1, 0), :]
        if tri[1, 0] > tri[2, 0]:
            tri[(1, 2), :] = tri[(2, 1), :]
        if tri[0, 0] > tri[1, 0]:
            tri[(0, 1), :] = tri[(1, 0), :]

        assert tri[1, 0] >= tri[0, 0]

        # edge setup
        if abs(tri[1, 0] - tri[0, 0]) > 0 and (tri[1, 0] - np.floor(tri[0, 0]) > 1):
            d1 = (tri[1] - tri[0]) / (tri[1, 0] - tri[0, 0])
            start = tri[0] + d1 * (1.0 - tri[0, 0] + np.floor(tri[0, 0]))
        else:
            d1 = (tri[2] - tri[1]) / (tri[2, 0] - tri[1, 0])
            start = tri[1] + d1 * (1.0 - tri[1, 0] + np.floor(tri[1, 0]))

        d2 = (tri[2] - tri[0]) / (tri[2, 0] - tri[0, 0])
        end = tri[0] + d2 * (1.0 - tri[0, 0] + np.floor(tri[0, 0]))
        vend = tri[1, 0]

        if np.linalg.norm(d1) > 1000 or np.linalg.norm(d2) > 1000:
            print("d warn")
            return

        while end[0] < tri[2, 0]:
            _draw_line(dense, size, start, end)

            start += d1
            end += d2
            if start[0] >= vend:
                vend = start[0] - tri[1, 0]
                start -= d1 * vend
                if tri[2, 0] - tri[1, 0] == 0:
                    break
                d1 = (tri[2] - tri[1]) / (tri[2, 0] - tri[1, 0])
                start += d1 * vend
                vend = tri[2, 0]

    elif scan_axis == 1:
        if tri[0, 1] > tri[1, 1]:
            tri[(0, 1), :] = tri[(1, 0), :]
        if tri[1, 1] > tri[2, 1]:
            tri[(1, 2), :] = tri[(2, 1), :]
        if tri[0, 1] > tri[1, 1]:
            tri[(0, 1), :] = tri[(1, 0), :]

        if abs(tri[1, 1] - tri[0, 1]) > 0 and (tri[1, 1] - np.floor(tri[0, 1]) > 1):
            d1 = (tri[1] - tri[0]) / (tri[1, 1] - tri[0, 1])
            start = tri[0] + d1 * (1.0 - tri[0, 1] + np.floor(tri[0, 1]))
        else:
            d1 = (tri[2] - tri[1]) / (tri[2, 1] - tri[1, 1])
            start = tri[1] + d1 * (1.0 - tri[1, 1] + np.floor(tri[1, 1]))

        d2 = (tri[2] - tri[0]) / (tri[2, 1] - tri[0, 1])
        end = tri[0] + d2 * (1.0 - tri[0, 1] + np.floor(tri[0, 1]))
        vend = tri[1, 1]

        if np.linalg.norm(d1) > 1000 or np.linalg.norm(d2) > 1000:
            print("d warn")
            return

        while end[1] < tri[2, 1]:
            _draw_line(dense, size, start, end)

            start += d1
            end += d2
            if start[1] >= vend:
                vend = start[1] - tri[1, 1]
                start -= d1 * vend
                if tri[2, 1] - tri[1, 1] == 0:
                    break
                d1 = (tri[2] - tri[1]) / (tri[2, 1] - tri[1, 1])
                start += d1 * vend
                vend = tri[2, 1]
    else:
        assert scan_axis == 2

        if tri[0, 2] > tri[1, 2]:
            tri[(0, 1), :] = tri[(1, 0), :]
        if tri[1, 2] > tri[2, 2]:
            tri[(1, 2), :] = tri[(2, 1), :]
        if tri[0, 2] > tri[1, 2]:
            tri[(0, 1), :] = tri[(1, 0), :]

        if abs(tri[1, 2] - tri[0, 2]) > 1e-1:
            d1 = (tri[1] - tri[0]) / (tri[1, 2] - tri[0, 2])
            start = tri[0] + d1 * (1.0 - tri[0, 2] + np.floor(tri[0, 2]))
        else:
            d1 = (tri[2] - tri[1]) / (tri[2, 2] - tri[1, 2])
            start = tri[1] + d1 * (1.0 - tri[1, 2] + np.floor(tri[1, 2]))

        d2 = (tri[2] - tri[0]) / (tri[2, 2] - tri[0, 2])
        end = tri[0] + d2 * (1.0 - tri[0, 2] + np.floor(tri[0, 2]))
        vend = tri[1, 2]

        if np.linalg.norm(d1) > 1000 or np.linalg.norm(d2) > 1000:
            print("d warn")
            return

        while end[2] < tri[2, 2]:
            _draw_line(dense, size, start, end)

            start += d1
            end += d2
            if start[2] >= vend:
                vend = start[2] - tri[1, 2]
                start -= d1 * vend
                if tri[2, 2] - tri[1, 2] == 0:
                    break
                d1 = (tri[2] - tri[1]) / (tri[2, 2] - tri[1, 2])
                start += d1 * vend
                vend = tri[2, 2]

    _draw_line(dense, size, tri[0], tri[1])
    _draw_line(dense, size, tri[0], tri[2])
    _draw_line(dense, size, tri[1], tri[2])


def _to_triangles(mesh: TriangleMesh) -> list[np.ndarray]:
    triangles = []
    vertices = np.asarray(mesh.vertices)
    for t in mesh.triangles:
        triangles.append(vertices[t])
    return triangles


# def voxelize(mesh: TriangleMesh) -> trimesh.points.PointCloud:
#     triangles = _to_triangles(mesh)

#     vertices = np.asarray(mesh.vertices)
#     center = np.mean(vertices, axis=0)
#     center[2] = 0

#     length = np.max(vertices, axis=0) - np.min(vertices, axis=0)
#     size = int(np.ceil(np.max(length)))

#     dense = np.ndarray((size, size, size), dtype=np.bool_)
#     dense[:, :, :] = False

#     for t in triangles:
#         _fill_triangle(dense, size, t - center)

#     voxel_grid = trimesh.voxel.VoxelGrid(dense)

#     point_cloud = trimesh.points.PointCloud(voxel_grid.points)
#     return point_cloud


def _sampling(submesh: Trimesh) -> np.ndarray:
    # area = submesh.area
    # sampling_count = int(area)
    # points, _ = sample_surface(submesh, int(sampling_count))
    # indices = points_to_indices(points, 1)
    # voxel_grid = fill_base(indices)
    # voxel = indices_to_points(voxel_grid, 1)

    vertices, faces = subdivide_to_size(submesh.vertices, submesh.faces, 5.0)
    mesh = Trimesh(vertices=vertices, faces=faces)
    voxel = mesh.voxelized(1).hollow()
    points = voxel.points
    return np.asarray(points)


def voxelize(mesh: TriangleMesh) -> trimesh.points.PointCloud:
    triangles = np.asarray(mesh.triangles)
    vertices = np.asarray(mesh.vertices)

    triangle_mesh = Trimesh(vertices=vertices, faces=triangles)

    num_submeshes = 1000
    submeshs = triangle_mesh.submesh(np.array_split(np.arange(len(triangle_mesh.faces)), num_submeshes))

    with Pool() as p:
        point_list = p.map(_sampling, submeshs)
    all_points = np.concatenate(point_list)

    # point_list = []
    # for mesh in submeshs:
    #     point_list.append(_sampling(mesh))
    # all_points = np.concatenate(point_list)

    return PointCloud(all_points)
