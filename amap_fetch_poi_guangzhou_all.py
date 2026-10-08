"""广州市全类别 POI 检索：网格细分、SQLite 断点续采、CSV 导出。"""
import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request

from coordinates import gcj02_to_wgs84

# 覆盖官方公布的市域经纬度范围，并留出坐标偏移余量；接口坐标为 GCJ-02。
BBOX = (112.90, 22.38, 114.10, 23.98)
DISTRICTS = {"荔湾区", "越秀区", "海珠区", "天河区", "白云区", "黄埔区",
             "番禺区", "花都区", "南沙区", "从化区", "增城区"}
PAGE_SIZE = 25
MAX_PAGES = 8  # 官方说明：相同查询最多返回 200 条。
FIELDS = ["id", "name", "type", "typecode", "category_code", "category_name",
          "address", "province", "city", "district", "adcode", "citycode",
          "lon_gcj02", "lat_gcj02", "lon_wgs84", "lat_wgs84"]


def text_value(value):
    return value if isinstance(value, str) else ""


def polygon(box):
    west, south, east, north = box
    return f"{west:.6f},{north:.6f}|{east:.6f},{south:.6f}"


def grid(box, step):
    west, south, east, north = box
    for x in range(math.ceil(round((east - west) / step, 10))):
        for y in range(math.ceil(round((north - south) / step, 10))):
            yield (round(west + x * step, 6), round(south + y * step, 6),
                   round(min(east, west + (x + 1) * step), 6),
                   round(min(north, south + (y + 1) * step), 6))


def subdivide(box):
    west, south, east, north = box
    midx, midy = round((west + east) / 2, 6), round((south + north) / 2, 6)
    return [(west, south, midx, midy), (midx, south, east, midy),
            (west, midy, midx, north), (midx, midy, east, north)]


def fetch_cell(key, box, category, interval):
    rows = []
    for page in range(1, MAX_PAGES + 1):
        params = {"key": key, "polygon": polygon(box), "types": category,
                  "page_size": PAGE_SIZE, "page_num": page, "output": "json"}
        url = "https://restapi.amap.com/v5/place/polygon?" + urllib.parse.urlencode(params)
        for attempt in range(3):
            time.sleep(interval)
            try:
                with urllib.request.urlopen(url, timeout=30) as response:
                    data = json.load(response)
                break
            except (urllib.error.URLError, TimeoutError, OSError, ValueError):
                if attempt == 2:
                    # 不输出包含 Key 的 URL 或异常原文。
                    raise RuntimeError("网络或响应解析失败，当前任务未标记完成，可重运行续采。") from None
                time.sleep(2 ** attempt)
        if not isinstance(data, dict):
            raise RuntimeError("接口响应结构异常，停止采集。")
        if data.get("status") != "1":
            raise RuntimeError(f"高德接口返回错误码 {data.get('infocode', 'unknown')}；"
                               "请核对 Key、服务权限、配额；当前任务保留待采状态。")
        pois = data.get("pois", [])
        if not isinstance(pois, list) or any(not isinstance(p, dict) for p in pois):
            raise RuntimeError("POI 返回结构异常，停止采集。")
        rows.extend(pois)
        if len(pois) < PAGE_SIZE:
            return rows, False
    return rows, True


def normalize(poi, categories):
    adcode = text_value(poi.get("adcode"))
    # 广州市行政编码前缀为 4401；不再限定原研究四区或原研究类别。
    if not adcode.startswith("4401"):
        return None
    try:
        lon, lat = map(float, text_value(poi.get("location")).split(","))
        if not math.isfinite(lon) or not math.isfinite(lat):
            return None
        if not (BBOX[0] <= lon <= BBOX[2] and BBOX[1] <= lat <= BBOX[3]):
            return None
    except (ValueError, TypeError):
        return None
    wlon, wlat = gcj02_to_wgs84(lon, lat)
    code = text_value(poi.get("typecode"))
    category_code = code[:2] + "0000" if len(code) >= 2 else ""
    record = dict(zip(FIELDS, [
        text_value(poi.get("id")), text_value(poi.get("name")),
        text_value(poi.get("type")), code, category_code,
        categories.get(category_code, "未识别"), text_value(poi.get("address")),
        text_value(poi.get("pname")), text_value(poi.get("cityname")),
        text_value(poi.get("adname")), adcode, text_value(poi.get("citycode")),
        lon, lat, wlon, wlat]))
    identity = record["id"] or "fallback:" + hashlib.sha256(
        json.dumps([record["name"], lon, lat, code], ensure_ascii=False).encode()).hexdigest()
    return identity, record


def initialize(db, categories, step, max_depth):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS tasks (
            category TEXT, box TEXT, depth INTEGER, status TEXT DEFAULT 'pending',
            raw_count INTEGER DEFAULT 0, rejected_count INTEGER DEFAULT 0,
            PRIMARY KEY(category, box));
        CREATE TABLE IF NOT EXISTS pois (identity TEXT PRIMARY KEY, record TEXT);
    """)
    config = json.dumps({"schema": 1, "bbox": BBOX, "categories": categories,
                         "step": step, "max_depth": max_depth}, sort_keys=True)
    old = db.execute("SELECT value FROM metadata WHERE name='config'").fetchone()
    if old and old[0] != config:
        raise ValueError("续采配置与原任务不同，请恢复配置或使用新的 --output 目录。")
    if not old:
        with db:
            db.execute("INSERT INTO metadata VALUES ('config', ?)", (config,))
            db.executemany("INSERT INTO tasks(category,box,depth) VALUES(?,?,0)",
                           ((code, json.dumps(box)) for code in categories for box in grid(BBOX, step)))


def process_task(db, task, key, categories, max_depth, interval, fetcher=fetch_cell):
    category, box_json, depth = task
    box = json.loads(box_json)
    pois, saturated = fetcher(key, box, category, interval)
    accepted = [normalize(poi, categories) for poi in pois]
    rejected = sum(item is None for item in accepted)
    split = saturated and depth < max_depth
    status = "split" if split else "truncated" if saturated else "done"
    with db:
        db.executemany("INSERT OR IGNORE INTO pois VALUES(?,?)",
                       ((item[0], json.dumps(item[1], ensure_ascii=False))
                        for item in accepted if item is not None))
        if split:
            db.executemany("INSERT OR IGNORE INTO tasks(category,box,depth) VALUES(?,?,?)",
                           ((category, json.dumps(child), depth + 1) for child in subdivide(box)))
        db.execute("UPDATE tasks SET status=?,raw_count=?,rejected_count=? WHERE category=? AND box=?",
                   (status, len(pois), rejected, category, box_json))
    return status


def export(db, output):
    counts = dict(db.execute("SELECT status,COUNT(*) FROM tasks GROUP BY status"))
    with (output / "guangzhou_all_poi.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        for (record,) in db.execute("SELECT record FROM pois ORDER BY identity"):
            writer.writerow(json.loads(record))
    with (output / "coverage_issues.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["category", "box_gcj02", "depth", "status", "raw_count", "rejected_count"])
        writer.writerows(db.execute("SELECT category,box,depth,status,raw_count,rejected_count FROM tasks "
                                   "WHERE status IN ('pending','truncated') ORDER BY category,box"))
    summary = {"unique_pois": db.execute("SELECT COUNT(*) FROM pois").fetchone()[0],
               "tasks": counts, "all_tasks_processed": counts.get("pending", 0) == 0,
               "unresolved_saturated_cells": counts.get("truncated", 0),
               "full_database_guaranteed": False}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("poi_output"))
    parser.add_argument("--categories", type=Path, default=Path(__file__).with_name("categories.json"))
    parser.add_argument("--grid-step", type=float, default=0.05)
    parser.add_argument("--max-depth", type=int, default=5)
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--max-tasks", type=int, default=0, help="试跑任务上限，0 表示不限制")
    parser.add_argument("--export-only", action="store_true")
    args = parser.parse_args()
    if not (0.001 <= args.grid_step <= 0.05 and 0 <= args.max_depth <= 8
            and args.interval >= 0.1 and args.max_tasks >= 0):
        parser.error("grid-step 须在 0.001–0.05；max-depth 在 0–8；interval ≥0.1；max-tasks ≥0")
    categories = json.loads(args.categories.read_text(encoding="utf-8"))
    if not isinstance(categories, dict) or not categories or any(
            not isinstance(k, str) or len(k) != 6 or not k.isdigit()
            or not isinstance(v, str) for k, v in categories.items()):
        parser.error("categories 必须为六位分类编码到名称的非空 JSON 对象")
    key = os.environ.get("AMAP_KEY", "").strip()
    if not args.export_only and not key:
        parser.error("请先设置环境变量 AMAP_KEY 为高德 Web 服务 Key")
    args.output.mkdir(parents=True, exist_ok=True)
    database = args.output / "checkpoint.sqlite3"
    if args.export_only and not database.exists():
        parser.error("没有可导出的 checkpoint.sqlite3，请先采集")
    db = sqlite3.connect(database)
    processed = 0
    exit_code = 0
    initialized = False
    try:
        initialize(db, categories, args.grid_step, args.max_depth)
        initialized = True
        if not args.export_only:
            while args.max_tasks == 0 or processed < args.max_tasks:
                task = db.execute("SELECT category,box,depth FROM tasks WHERE status='pending' "
                                  "ORDER BY depth DESC,category,box LIMIT 1").fetchone()
                if task is None:
                    break
                status = process_task(db, task, key, categories, args.max_depth, args.interval)
                processed += 1
                if processed % 20 == 0 or status == "truncated":
                    print(f"本次已处理 {processed} 个任务；当前类别 {task[0]}；状态 {status}", flush=True)
    except KeyboardInterrupt:
        print("已中断，将导出已有结果；相同命令可续采。")
        exit_code = 130
    except (RuntimeError, ValueError) as error:
        print(str(error))
        exit_code = 1
    finally:
        if initialized:
            export(db, args.output)
        db.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
