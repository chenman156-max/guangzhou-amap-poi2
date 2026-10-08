# 广州市全类别高德 POI 采集

由原广州四区研究脚本扩展而来，检索范围覆盖广州全市，按高德官方分类表的全部 24 个大类逐类查询，保留返回的所有小类，不再限定住宅区、公园广场或体育场所。

## 范围与类别

检索矩形为 GCJ-02 经度 112.90–114.10、纬度 22.38–23.98，覆盖广州市政府公布的市域经纬度范围并留出坐标偏移余量。矩形包含邻市区域，结果按 `adcode` 的广州前缀 `4401` 筛选；这依赖高德返回的行政区属性，不是精确行政边界裁剪。覆盖越秀、荔湾、海珠、天河、白云、黄埔、番禺、花都、南沙、从化、增城。

`categories.json` 包含汽车服务、汽车销售、汽车维修、摩托车服务、餐饮服务、购物服务、生活服务、体育休闲服务、医疗保健服务、住宿服务、风景名胜、商务住宅、政府机构及社会团体、科教文化服务、交通设施服务、金融保险服务、公司企业、道路附属设施、地名地址信息、公共设施、事件活动、室内设施、虚拟数据、通行设施。其内容由官方 POI 分类编码下载表的大类提取而来，核对日期为 2026-10-08；未来分类变化可更新该 JSON 并使用新的输出目录。

## 运行

Python 3.9 或更高版本，仅使用标准库，无须 pip 安装依赖。将本目录中的文件放在同一个文件夹，命令行切换到该目录。

Windows CMD / Anaconda Prompt：

```bat
set "AMAP_KEY=你的高德Web服务Key"
python amap_fetch_poi_guangzhou_all.py --max-tasks 20
```

PowerShell：

```powershell
$env:AMAP_KEY="你的高德Web服务Key"
python amap_fetch_poi_guangzhou_all.py --max-tasks 20
```

macOS / Linux：

```bash
export AMAP_KEY='你的高德Web服务Key'
python3 amap_fetch_poi_guangzhou_all.py --max-tasks 20
```

先试跑 20 个网格类别任务，确认权限和返回数据正常。试跑只处理初始部分任务，不能据此判断全市类别分布。随后移除任务上限，使用相同输出目录续采：

```bash
python amap_fetch_poi_guangzhou_all.py
python check_poi_result.py
```

Key 只通过环境变量读取，不写入代码或断点文件。不要将真实 Key 写入 README、截图、日志或上传 GitHub。

## 网格与续采

默认每次请求前休眠 2 秒，分页、切换网格和切换类别均执行；这是针对此前请求频率超限问题沿用的设置。若账号仍提示 QPS 超限，可使用 `--interval 3` 加长间隔。

默认初始网格步长 0.05°，单页 25 条，最多读取 8 页。当一个网格的一类数据达到 200 条时，自动四等分，再分别检索，最多细分 5 层。达到细分深度后仍饱和的任务标记为 `truncated`。网络或解析失败最多尝试 3 次；接口业务错误立即停止，当前网格保持待采状态。

每个完成网格的结果和状态以 SQLite 事务一起保存，按 POI ID 去重，缺失 ID 时按名称、坐标、类别生成备用标识。即使中断，可用相同命令继续；中断发生在未提交的网格时会重新检索该网格，不会把部分分页误标记为完成。

全市全类别查询会产生大量请求，实际耗时与账号配额、密度和网络有关。默认初始任务数为 18,432，密集网格会额外增加任务。`--max-tasks` 是本次处理任务上限，不是 API 请求次数上限。

可选参数：

| 参数 | 默认值 | 用途 |
| --- | --- | --- |
| `--output` | `poi_output` | 结果和断点目录 |
| `--grid-step` | `0.05` | 初始网格步长（度） |
| `--max-depth` | `5` | 最大细分层数 |
| `--interval` | `2.0` | 每次请求前等待秒数 |
| `--max-tasks` | `0` | 0 表示不限制任务数 |
| `--export-only` | 关闭 | 只从已有断点重新导出 |
| `--categories` | 脚本旁的 `categories.json` | 分类配置文件 |

网格大小、分类或细分深度变更时须使用新的输出目录，以免与旧断点混用。

## 输出

| 文件 | 内容 |
| --- | --- |
| `poi_output/guangzhou_all_poi.csv` | 全市各类别合并结果，UTF-8 BOM |
| `poi_output/checkpoint.sqlite3` | 已采数据与网格任务，供续采使用 |
| `poi_output/summary.json` | 唯一 POI 数量、任务状态、未解决饱和网格数 |
| `poi_output/coverage_issues.csv` | 待采及达到深度上限的饱和网格 |

CSV 包含名称、地址、原始类别及类别编码、大类编码及名称、省市区、行政编码、GCJ-02 坐标及近似 WGS84 坐标。GIS 导入时选 `lon_wgs84` 为 X、`lat_wgs84` 为 Y，指定 WGS84（EPSG:4326）。转换为近似值，距离分析前应检查位置并使用适当投影。

## 完整性与验证

全类别指遍历分类表的所有大类，不代表取得高德数据库全部记录。官方说明相同查询参数翻页最多返回 200 条，并不支持返回全量。网格细分旨在减少分页截断，仍不能保证无遗漏。`all_tasks_processed=true` 只表示所有任务已处理；还应查看饱和任务和类别、行政区分布。

本次代码经过离线模拟验证，覆盖分页上限触发细分、断点续采、失败任务保留、ID 去重、全市行政编码筛选和 CSV 导出；未使用真实 Key 在线运行，不包含已采集数据。

## 来源

- [高德搜索 POI 2.0 文档](https://developer.amap.com/api/webservice/guide/api-advanced/newpoisearch)
- [高德官方分类编码下载页](https://developer.amap.com/api/webservice/download)
- [广州市人民政府：自然地理](https://www.gz.gov.cn/zlgz/gzgk/zrdl/content/mpost_10071227.html)

## 上传 GitHub

上传本目录中的代码、`categories.json`、README 和 `.gitignore`。运行输出和 Key 不随代码上传。
