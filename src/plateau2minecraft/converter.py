import os
from pathlib import Path

import numpy as np
from click import Path
from trimesh.points import PointCloud

from .anvil import Block, EmptyRegion
from .anvil.errors import OutOfBoundsCoordinates


class Minecraft:
    def __init__(self, point_cloud: PointCloud) -> None:
        self.point_cloud = point_cloud

    def _point_shift(self, points: np.ndarray, x: float, y: float, z: float) -> np.ndarray:
        points += np.array([x, y, z])
        return points

    def _split_point_cloud(self, vertices: np.ndarray, block_size: int = 512) -> dict[str, np.ndarray]:
        # XYZ座標の取得
        x = vertices[:, 0]
        y = vertices[:, 1]

        # XY座標をブロックサイズで割って、整数値に丸めることでブロックIDを作成
        block_id_x = np.floor(x / block_size).astype(int)
        block_id_y = np.floor(y / block_size).astype(int)

        # ブロックIDを一意の文字列として結合
        block_ids = [f"r.{id_x}.{id_y}.mca" for id_x, id_y in zip(block_id_x, block_id_y)]

        # 各ブロックIDとそのブロックに含まれる座標を格納する辞書を作成
        blocks = {}
        for i, block_id in enumerate(block_ids):
            if block_id not in blocks:
                blocks[block_id] = []
            blocks[block_id].append(vertices[i])

        # ブロックIDと座標を含む辞書を返す
        return blocks

    def _standardize_vertices(self, blocks: dict[str, np.ndarray], block_size: int = 512):
        standardized_blocks = {}
        for block_id, vertices in blocks.items():
            standardized_vertices = [vertex % block_size for vertex in vertices]
            standardized_blocks[block_id] = standardized_vertices
        return standardized_blocks

    def build_region(self, output: Path, origin: tuple[float, float, float] | None = None) -> None:
        points = np.asarray(self.point_cloud.vertices)

        origin_point = self._get_world_origin(points) if origin is None else origin
        print(f"origin_point: {origin_point}")

        # 点群の中心を原点に移動
        points = self._point_shift(points, -origin_point[0], -origin_point[1], 0)
        # ボクセル中心を原点とする。ボクセルは1m間隔なので、原点を右に0.5m、下に0.5mずらす
        points = self._point_shift(points, 0.5, 0.5, 0)
        # Y軸を反転させて、Minecraftの南北とあわせる
        points[:, 1] *= -1

        # 原点を中心として、x軸方向に512m、y軸方向に512mの領域を作成する
        # 領域ごとに、ボクセルの点群を分割する
        # 分割した点群を、領域ごとに保存する
        blocks = self._split_point_cloud(points)
        standardized_blocks = self._standardize_vertices(blocks)

        stone = Block("minecraft", "stone")

        # data/output/world_data/region/フォルダの中身を削除
        # フォルダが存在しない場合は、フォルダを作成する
        # フォルダが存在する場合は、フォルダの中身を削除する
        if os.path.exists("data/output/world_data/region"):
            for file in os.listdir("data/output/world_data/region"):
                os.remove(f"data/output/world_data/region/{file}")
        else:
            os.makedirs("data/output/world_data/region", exist_ok=True)

        for block_id, points in standardized_blocks.items():
            region = EmptyRegion(0, 0)
            points = np.asarray(points).astype(int)
            for row in points:
                x, y, z = row
                try:
                    region.set_block(stone, x, z, y) # MinecraftとはY-UPの右手系なので、そのように変数を定義する
                except OutOfBoundsCoordinates:
                    continue
            print(f"save: {block_id}")
            region.save(f"{output}/world_data/region/{block_id}")

    def _get_world_origin(self, vertices):
        min_x = min(vertices[:, 0])
        max_x = max(vertices[:, 0])

        min_y = min(vertices[:, 1])
        max_y = max(vertices[:, 1])

        # 中心座標を求める
        center_x = (max_x + min_x) / 2
        center_y = (max_y + min_y) / 2

        # 中心座標を右に0.5m、下に0.5mずらす
        origin_point = (center_x + 0.5, center_y + 0.5)

        return origin_point
