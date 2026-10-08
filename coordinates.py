"""原研究脚本中的 GCJ-02 → 近似 WGS84 转换。"""
import math

PI = math.pi
A = 6378245.0
EE = 0.00669342162296594323


def out_of_china(lon, lat):
    return not (73.66 < lon < 135.05 and 3.86 < lat < 53.55)


def transform_lat(x, y):
    ret = (
        -100.0
        + 2.0 * x
        + 3.0 * y
        + 0.2 * y * y
        + 0.1 * x * y
        + 0.2 * math.sqrt(abs(x))
    )
    ret += (
        20.0 * math.sin(6.0 * x * PI)
        + 20.0 * math.sin(2.0 * x * PI)
    ) * 2.0 / 3.0
    ret += (
        20.0 * math.sin(y * PI)
        + 40.0 * math.sin(y / 3.0 * PI)
    ) * 2.0 / 3.0
    ret += (
        160.0 * math.sin(y / 12.0 * PI)
        + 320.0 * math.sin(y * PI / 30.0)
    ) * 2.0 / 3.0
    return ret


def transform_lon(x, y):
    ret = (
        300.0
        + x
        + 2.0 * y
        + 0.1 * x * x
        + 0.1 * x * y
        + 0.1 * math.sqrt(abs(x))
    )
    ret += (
        20.0 * math.sin(6.0 * x * PI)
        + 20.0 * math.sin(2.0 * x * PI)
    ) * 2.0 / 3.0
    ret += (
        20.0 * math.sin(x * PI)
        + 40.0 * math.sin(x / 3.0 * PI)
    ) * 2.0 / 3.0
    ret += (
        150.0 * math.sin(x / 12.0 * PI)
        + 300.0 * math.sin(x / 30.0 * PI)
    ) * 2.0 / 3.0
    return ret


def gcj02_to_wgs84(lon, lat):
    if not math.isfinite(lon) or not math.isfinite(lat):
        return None, None

    lon = float(lon)
    lat = float(lat)

    if out_of_china(lon, lat):
        return lon, lat

    dlat = transform_lat(lon - 105.0, lat - 35.0)
    dlon = transform_lon(lon - 105.0, lat - 35.0)

    radlat = lat / 180.0 * PI
    magic = math.sin(radlat)
    magic = 1 - EE * magic * magic
    sqrtmagic = math.sqrt(magic)

    dlat = (dlat * 180.0) / (
        (A * (1 - EE)) / (magic * sqrtmagic) * PI
    )
    dlon = (dlon * 180.0) / (
        A / sqrtmagic * math.cos(radlat) * PI
    )

    mg_lat = lat + dlat
    mg_lon = lon + dlon

    return lon * 2 - mg_lon, lat * 2 - mg_lat


