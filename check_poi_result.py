"""检查全市 CSV，统计区级和类别分布，并提示未完成及饱和网格。"""
import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path

from amap_fetch_poi_guangzhou_all import BBOX, DISTRICTS, FIELDS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("poi_output"))
    args = parser.parse_args()
    ids, districts, categories, anomalies = set(), Counter(), Counter(), Counter()
    count = 0
    with (args.output / "guangzhou_all_poi.csv").open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not set(FIELDS).issubset(reader.fieldnames or []):
            raise ValueError("CSV 缺少必要字段")
        for row in reader:
            count += 1
            districts[row["district"]] += 1
            categories[row["category_code"] + " " + row["category_name"]] += 1
            if not row["adcode"].startswith("4401"):
                anomalies["非广州行政编码"] += 1
            if row["district"] not in DISTRICTS:
                anomalies["行政区名称异常"] += 1
            if row["city"] != "广州市":
                anomalies["城市名称异常"] += 1
            if row["id"]:
                if row["id"] in ids:
                    anomalies["重复ID行数"] += 1
                ids.add(row["id"])
            else:
                anomalies["ID缺失"] += 1
            try:
                lon, lat, wlon, wlat = (float(row[k]) for k in
                                       ["lon_gcj02", "lat_gcj02", "lon_wgs84", "lat_wgs84"])
                if not all(math.isfinite(v) for v in (lon, lat, wlon, wlat)) or not (
                        BBOX[0] <= lon <= BBOX[2] and BBOX[1] <= lat <= BBOX[3]):
                    anomalies["坐标异常"] += 1
            except ValueError:
                anomalies["坐标异常"] += 1
    print(f"总记录数：{count}")
    print("行政区分布：", dict(sorted(districts.items())))
    print("类别分布：", dict(sorted(categories.items())))
    print("异常统计：", dict(anomalies))
    summary = json.loads((args.output / "summary.json").read_text())
    print("采集任务状态：", summary)
    print("零异常不代表完整全量；请查看 coverage_issues.csv 的待采/饱和任务。")
    return 1 if anomalies else 0


if __name__ == "__main__":
    raise SystemExit(main())
