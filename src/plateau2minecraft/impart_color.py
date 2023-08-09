from trimesh.points import PointCloud

from plateau2minecraft.feature_color import colors


def assign(point_cloud: PointCloud, feature_type: str) -> PointCloud:
    point_cloud.colors = colors[feature_type]
    return point_cloud
