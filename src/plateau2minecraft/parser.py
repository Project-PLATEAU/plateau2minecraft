from pathlib import Path

import lxml.etree as et
import numpy as np
import pyproj

from plateau2minecraft.earcut import earcut
from plateau2minecraft.earcut.utils_3d import project3d_to_2d
from plateau2minecraft.types import TriangleMesh

_NS = {
    "gml": "http://www.opengis.net/gml",
    "bldg": "http://www.opengis.net/citygml/building/2.0",
    "brid": "http://www.opengis.net/citygml/bridge/2.0",
    "veg": "http://www.opengis.net/citygml/vegetation/2.0",
    "frn": "http://www.opengis.net/citygml/cityfurniture/2.0",
    "tran": "http://www.opengis.net/citygml/transportation/2.0",
}

_XPATH_LIST = {
    "bldg": [
        ".//bldg:Building",
        ".//bldg:WallSurface",
        ".//bldg:RoofSurface",
        ".//bldg:GroundSurface",
        ".//bldg:OuterFloorSurface",
        ".//bldg:OuterCeilingSurface",
        ".//bldg:ClosureSurface",
        ".//bldg:BuildingInstallation",
        ".//bldg:Window",
        ".//bldg:Door",
    ],
    "tran": [".//tran:Road", ".//tran:TrafficArea"],
    "brid": [
        ".//brid:Bridge",
        ".//brid:BridgePart",
        ".//brid:RoofSurface",
        ".//brid:GroundSurface",
        ".//brid:WallSurface",
        ".//brid:ClosureSurface",
        ".//brid:OuterFloorSurface",
        ".//brid:OuterCeilingSurface",
        ".//brid:BridgeConstructionElement",
        ".//brid:OuterBridgeInstallation",
        ".//brid:Door",
        ".//brid:Window",
        ".//brid:IntBridgeInstallation",
        ".//brid:BridgeFurniture",
    ],
    "frn": [".//frn:CityFurniture"],
    "veg": [".//veg:PlantCover", ".//veg:SolitaryVegetationObject"],
}

transformer = pyproj.Transformer.from_crs("epsg:6697", "epsg:3857", always_xy=True)


def _load_polygons(doc, obj_path: str) -> list[list[np.ndarray]]:
    polygons = []
    for obj in doc.iterfind(obj_path, _NS):
        found = False
        for lod in [2, 1]:
            for polygon_path in [
                f".//bldg:lod{lod}MultiSurface//gml:Polygon",
                f".//bldg:lod{lod}Geometry//gml:Polygon",
                f".//bldg:lod{lod}Solid//gml:Polygon",
                f".//tran:lod{lod}MultiSurface//gml:Polygon",
                f".//tran:lod{lod}Geometry//gml:Polygon",
                f".//brid:lod{lod}MultiSurface//gml:Polygon",
                f".//brid:lod{lod}Geometry//gml:Polygon",
                f".//veg:lod{lod}MultiSurface//gml:Polygon",
                f".//veg:lod{lod}Geometry//gml:Polygon",
                f".//frn:lod{lod}MultiSurface//gml:Polygon",
                f".//frn:lod{lod}Geometry//gml:Polygon",
            ]:
                for polygon in obj.iterfind(polygon_path, _NS):
                    pos_list = polygon.find("./gml:exterior//gml:posList", _NS)
                    vertices = np.fromstring(pos_list.text, dtype=np.float64, sep=" ")
                    assert len(vertices) % 3 == 0
                    assert len(vertices) / 3 >= 3
                    exterior = vertices.reshape(-1, 3)[:-1]
                    rings = []
                    rings.append(exterior)
                    for pos_list in polygon.iterfind("./gml:interior//gml:posList", _NS):
                        vertices = np.fromstring(pos_list.text, dtype=np.float64, sep=" ")
                        assert len(vertices) % 3 == 0
                        # assert len(vertices) / 3 > 1000
                        vertices = vertices.reshape(-1, 3)[:-1]
                        rings.append(vertices)
                    polygons.append(rings)
                    found = True

            if found:
                break

    return polygons


def _triangulate(polygons: list[list[np.ndarray]]) -> TriangleMesh:
    vertices = []
    triangles = []
    for polygon in polygons:
        vertex = np.vstack(polygon)
        hole_indices = []
        if len(polygon) > 1:
            hi = polygon[0].shape[0]
            for ring in polygon[1:]:
                hole_indices.append(hi)
                hi += ring.shape[0]
        xx, yy = transformer.transform(vertex[:, 1], vertex[:, 0])
        vertex[:, 0] = np.asarray(xx)
        vertex[:, 1] = np.asarray(yy)
        flatten_vertices = vertex.flatten()

        flatten_vertices = project3d_to_2d(flatten_vertices, len(polygon[0]))
        if flatten_vertices is not None and (cut := earcut(flatten_vertices, hole_indices, dim=2)):
            cut = np.asarray(cut).reshape(-1, 3)

            if len(triangles) > 0:
                max_index = np.max(np.asarray(triangles, dtype=np.int32))
                cut += max_index + 1
            else:
                max_index = 0
                cut += max_index

            vertices.extend(vertex)
            triangles.extend(cut)

    return TriangleMesh(vertices, triangles)


def get_triangle_meshs(file_path: Path, feature_type: str) -> TriangleMesh:
    obj_paths = _XPATH_LIST[feature_type]

    doc = et.parse(file_path, None)

    triangles = []
    vertices = []
    max_index = 0
    for obj_path in obj_paths:
        polygons = _load_polygons(doc, obj_path)

        if polygons:
            triangle_mesh = _triangulate(polygons)

            vertices.extend(triangle_mesh.vertices)

            t = np.asarray(triangle_mesh.triangles, dtype=np.int32)
            t += max_index
            triangles.extend(t)

            max_index = np.asarray(triangles).max() + 1
            # max_index += np.asarray(triangles).max()

    return TriangleMesh(vertices, triangles)
