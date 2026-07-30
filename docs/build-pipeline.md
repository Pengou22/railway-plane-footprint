# 全国铁路底图构建

`pipeline/` 保存 OSM 地点提取、铁路底图与行程寻路的可复现构建流程。
原始数据与中间文件体积很大，不进入 Git。

## 环境

- Anaconda；
- 名为 `osmium` 的 Conda 环境；
- 该环境中的 `osmium-tool`；
- Anaconda `base` 环境中的 Python 3、NumPy 和 SciPy。

当前构建器不依赖 GDAL、GeoPandas、Shapely 或在线路径服务。省域构建还读取
仓库内的 `data/raw/boundaries/china-provinces-datav.json`，页面运行与重建
过程均不需要联网。

## 输入

从 Geofabrik 等 OpenStreetMap 数据提供方取得中国 `.osm.pbf` 快照，并放入
`data/raw/osm/`。

不要把 PBF 提交到 Git。当前完整中国快照约 1.4 GB。

## 构建

在项目根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File pipeline/build.ps1 `
  -InputPbf data/raw/osm/china-260325.osm.pbf `
  -Snapshot 2026-03-25
```

可调参数：

- `Tolerance`：Douglas–Peucker 简化容差，单位为经纬度角度，默认 `0.005`；
- `MinimumLengthKm`：过滤过短线段，默认 `2.0`；
- `OutputJson`：最终输出路径，默认 `data/generated/railways.geojson`。

默认流程：

```text
China PBF
  ├─ railway=station/halt + aeroway=aerodrome
  │   ├─ station_name.js 白名单 + 省域范围 + 临近 railway=rail
  │   │   └─ data/generated/stations.json
  │   └─ 有效 IATA/定期客运证据 + 省域范围 - 通用航空
  │       └─ data/generated/airports.json
  └─ railway=rail
      ├─ usage=main/branch
      │   └─ 合并与简化
      │       └─ data/generated/railways.geojson
      └─ 全部轨道、道岔及站线
          └─ 压缩拓扑图
              └─ 分车型 A* 寻路
                  └─ data/generated/routes.json

DataV.GeoAtlas areas_v3 全国省域 GeoJSON
  └─ 简化与名称标准化
      └─ data/generated/admin-boundaries-province.json
```

显示层只保留主线与支线；路由层保留全部 `railway=rail`，否则上下行正线之间
负责换线的 `crossover/siding/yard` 会被删除，铁路拓扑将出现大量平行但
不连通的轨道。服务线和非客运线在寻路中保留，但具有较高成本。

车站不是强行吸附为单一轨道节点。构建器会保留站区附近多个候选接入点，
A* 同时考虑这些入口，避免因上下行线或站场映射方式造成数百公里绕行。

## 当前产物

基于 2026-03-25 OSM 快照、默认参数生成：

- 4,066 条显示线；
- 40,938 个坐标点；
- 850 条高速铁路显示线；
- 3,216 条普速铁路显示线；
- 510,820 个铁路路由节点、593,432 条拓扑边；
- 58 条沿实际轨道生成的历史行程；
- 12,628 个足迹坐标点；
- `station_name.js` 共 3,369 个境内客运站名，其中 3,321 个已匹配 OSM 坐标；
- 已匹配目录中主要站 44、普通站 3,261、乘降所 16；
- 288 座带 OSM 客运证据且已排除通用航空等对象的机场；
- 34 个省级行政区，共 23,501 个坐标点；
- 铁路底图以两类 `MultiLineString` GeoJSON 供 MapLibre 工作线程直接读取，
  足迹路线则按行程动态装入 WebGL 图层；
- 铁路底图约 0.82 MB、客运站目录约 1.80 MB、客运机场目录约 0.07 MB、
  省界约 0.88 MB；两个地点目录均在页面启动时加载，地图只绘制行程涉及的地点。

省域产物是 MapLibre 可直接读取的 GeoJSON 面，支持鼠标命中、高亮和悬停
省名。构建时会裁掉海南省位于低纬南海的离岸小面，避免地图按完整包围盒
缩放后把大陆主图挤窄；市域和县域边界不再生成或加载，以降低页面
解析、内存和绘制开销。

网页中的省域、铁路网与行程均由 MapLibre 工作线程切片并作为 WebGL 图层
绘制。拖动或缩放地图时，列车和飞机动画会暂时停止，结束操作后再恢复，避免
动画更新抢占平移帧。左侧单层抽屉默认收起，展开后可按年份和月份筛选并直接
浏览历史行程；悬停时临时加粗行程，点击可多选锁定，再次点击则单独解锁。

当前车型偏好：

- `G`：优先高速铁路；
- `C/D`：适度优先高速铁路；
- `K/Z/T/Y`：优先普速铁路；
- 其他车次：距离与线路类型均衡。

页面动画同样使用这三类车型：`K/Z/T/Y` 与其他普速车为速度单位 `1`，
`C/D` 为 `2`，`G` 为 `3`，飞机为 `5`。运行时间按起终点经纬度之间的
直线距离计算，以 1,300 km 为参考距离；飞机约 15 秒走完该参考距离，
其余车型按速度单位同比换算。图标仍沿实际轨迹运动，所以线路绕行程度不同
时会保留轻微的视觉速度差。每轮运行前还会重新随机等待 0–10 秒，等待期间
图标不会显示。

偏好是成本倾向，不是硬过滤。算法不会为了追逐某种线路类型接受明显不合理的
全国绕行；每一段还会执行轨道距离与直线距离的合理性检查。

客运站目录以 `station_name.js` 的 3,369 个境内中文站名为白名单，再与 OSM
的国铁站点进行名称匹配并取得坐标。地铁、轻轨、单轨、有轨电车、国境外对象
以及离铁路过远的同名对象会被排除。当前 OSM 快照无法安全匹配的 48 个站名会
记录在产物元数据中，不会写入推测坐标。

页面启动时会加载该目录，所有铁路站均按名称直接从中解析坐标，正式名称优先
于别名。因此新增目录中已有的普通客运站不需要手工填写经纬度；若名称仍命中
多个候选，构建器会列出候选项，需在行程中改用能唯一匹配的正式站名。

客运机场目录从 OSM 的 `aeroway=aerodrome` 中提取，以有效三字母 IATA 代码或
`scheduled_service=yes` 作为客运证据，并排除明确标记为通用航空、私人、停用
或废弃的机场。相同 IATA 的面、关系和节点会合并为同一座机场。

## 数据许可

铁路数据来自 OpenStreetMap contributors，并依据 ODbL 1.0 使用。网页中必须
保留可见的 OpenStreetMap 署名与许可链接。

省域边界源文件来自
[DataV.GeoAtlas](https://datav.aliyun.com/portal/school/atlas/area_selector)
`areas_v3/bound/100000_full`。

仓库保留的 `data/raw/boundaries/china-provinces-datav.json` 是原始 GeoJSON；
网页加载的 `data/generated/admin-boundaries-province.json` 则经过省名与属性
标准化、坐标简化和精度统一，并过滤附属要素、裁去海南低纬离岸小面和添加
构建元数据。两者分别承担“可复现输入”和“稳定、轻量的网页运行数据”职责。
