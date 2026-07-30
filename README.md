# 空铁足迹

一个用于记录个人铁路与航空历史行程的交互式地图。

页面以 MapLibre GL 的 WebGL 地图为基础，将省域、经过离线筛选和简化的
OpenStreetMap 全国铁路网以及历史足迹绘制为地图图层。车站、机场坐标直接由
OSM 生成，铁路足迹通过带车型偏好的 A* 寻路沿真实铁路网络绘制。

左侧抽屉默认收起，展开后可开关全国铁路网、按年份和月份筛选并连续浏览历史
行程。行程卡片支持悬停临时加粗、点击多选锁定真实路线。底图采用可交互的
详细省域边界。

## 本地预览

项目通过 `fetch` 加载 JSON，不能直接双击 `index.html`。在项目根目录运行：

```powershell
D:\Anaconda\python.exe -m http.server 8000
```

然后访问 <http://127.0.0.1:8000/>。

## 目录结构

- `assets/`：网页直接加载的样式、脚本、图片和 MapLibre GL；
- `data/source/`：人工维护的铁路/航空行程和客运站白名单；
- `data/generated/`：构建脚本生成、网页直接读取的数据；
- `data/raw/`：OSM PBF 和省域边界原始输入；
- `pipeline/`：完整构建流程、数据生成和校验工具；
- `docs/`：数据格式、构建说明和开发记录；
- `references/`：不参与当前网页运行的第三方参考项目；
- `archive/`：保留但不参与当前构建的旧铁路中间数据。

## 更新个人行程

铁路与航空行程分别维护：

- `data/source/journeys-railway.json`：铁路行程，`stops` 按顺序填写中文车站名；
- `data/source/journeys-flight.json`：航空行程，`stops` 按顺序填写中文机场名。

名称会直接解析到 `stations.json` 或 `airports.json`。正式名称优先于别名；
若仍有多个同名候选，需在行程中改用能唯一匹配的正式名称。

字段格式和编辑示例见 [`docs/data-format.md`](docs/data-format.md)。

编辑后运行数据校验：

```powershell
D:\Anaconda\python.exe pipeline\tools\validate_data.py
```

## 更新全国铁路网

铁路、车站和机场数据来自 OpenStreetMap。构建脚本会完成以下流程：

1. 从中国 OSM PBF 中筛选 `railway=rail`；
2. 提取火车站、机场及稳定 OSM 元素 ID；
3. 解析 `station_name.js` 客运站白名单，并与原始 OSM 站点匹配；
4. 生成全国客运铁路站与民航客运机场目录；
5. 构建包含道岔和站线的铁路拓扑图；
6. 根据 G、C/D、普速等车型偏好，为每段行程执行 A* 寻路；
7. 排除通用航空、私人和停用机场；
8. 生成铁路底图、全国车站/机场目录和实际轨道足迹。

把新的中国 PBF 放入 `data/raw/osm/`，然后运行：

```powershell
powershell -ExecutionPolicy Bypass -File pipeline/build.ps1 `
  -InputPbf data/raw/osm/china-latest.osm.pbf `
  -Snapshot 2026-07-26
```

原始 PBF、旧铁路实验数据和 `data/cache` 均被 Git 忽略。构建产物为：

- `data/generated/stations.json`：约 3.3 千座已匹配 OSM 坐标的全国客运站目录；
- `data/generated/airports.json`：从 OSM 筛选并排除通用航空等对象的全国客运机场目录；
- `data/generated/railways.geojson`：约 0.82 MB、由 MapLibre 工作线程直接读取的铁路显示图层；
- `data/generated/routes.json`：约 0.27 MB 的实际轨道足迹；
- `data/generated/admin-boundaries-province.json`：省域可交互面。

更完整的构建说明见
[`docs/build-pipeline.md`](docs/build-pipeline.md)。

## 数据来源

全国铁路网基于
[OpenStreetMap contributors](https://www.openstreetmap.org/copyright)
提供的数据，并按 ODbL 1.0 使用和署名。

省域底图来自
[DataV.GeoAtlas](https://datav.aliyun.com/portal/school/atlas/area_selector)
`areas_v3` 全国省域 GeoJSON。
