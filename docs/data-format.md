# 地图数据格式

个人行程和地点源数据均采用版本 3 格式。人工维护的数据中不再
保存坐标；坐标统一从 OpenStreetMap 快照生成。

## locations.json

`locations` 数组同时保存车站和机场，只记录稳定 ID、显示名称和 OSM 绑定：

```json
{
  "schemaVersion": 3,
  "locations": [
    {
      "id": "cqx",
      "type": "station",
      "name": "重庆西",
      "osmId": "n9466211968"
    },
    {
      "id": "cqjb",
      "type": "airport",
      "name": "重庆江北",
      "osmId": "a206564952"
    }
  ]
}
```

字段说明：

- `id`：稳定、唯一的小写标识；创建后不要随意修改；
- `type`：只能是 `station` 或 `airport`；
- `name`：地图中显示的名称；
- `osmId`：Osmium 导出的 OSM 要素 ID。

添加名称在全国唯一的新地点时，可以先省略 `osmId` 并运行铁路构建脚本；
脚本会自动匹配并写回绑定。如果出现重名，构建器会列出候选 ID，必须明确
选择，不能仅凭名称猜测。

## journeys.json

铁路和航空行程保存在同一个 `journeys` 数组中：

```json
{
  "schemaVersion": 3,
  "journeys": [
    {
      "id": "train-2026-02-09-g475",
      "mode": "train",
      "code": "G475",
      "date": "2026-02-09",
      "stops": ["重庆西", "潼南"],
      "note": "驶入潼南站的第一班 G 字头列车"
    }
  ]
}
```

字段说明：

- `id`：行程唯一标识，推荐格式为 `方式-日期-班次`；
- `mode`：`train` 或 `flight`；
- `code`：车次或航班号；
- `date`：`YYYY-MM-DD` 格式日期；
- `stops`：直接填写地点的中文 `name`，至少包含起点与终点，可在中间加入途经站；
- `note`：可选的旅程记忆。

铁路行程只能引用 `station` 的名称，航班只能引用 `airport` 的名称。地点名称在
整个项目中必须唯一；校验器会拒绝可能产生歧义的重名。

## 生成数据

以下文件均由构建脚本生成，不应手动修改：

- `places.json`：当前 OSM 快照中的车站和机场坐标；
- `passenger-stations.json`：全国客运站坐标、OSM 证据和显示等级；
- `railways.json`：用于显示的全国铁路底图；
- `journey-routes.json`：每次铁路行程沿 OSM 铁路网计算出的轨迹；
- `admin-boundaries-province.json`：DataV.GeoAtlas 全国省域 GeoJSON。

省域文件采用 `schemaVersion: 2`，`geoJSON.features` 中的每个元素都是
可交互的 `Polygon` 或 `MultiPolygon`。文件按行政区特征分行，既方便查看，
也避免把庞大的坐标数组逐项缩进。

客运站白名单来自 `data/source/station_name.js`。该文件是一个
`var station_names = '@...';` JavaScript 字符串：记录以 `@` 分隔，字段以
`|` 分隔，11 个字段依次为站名简码、中文站名、电报码、全拼、简拼、序号、
城市代码、城市名、国家代码、国家名和英文名。构建时排除国家代码非空的境外
记录，再按中文站名匹配 OSM 国铁车站，由 OSM 提供坐标。

目录会排除地铁、轻轨、单轨、有轨电车和无法安全匹配坐标的同名站，并要求
OSM 对象位于省域面内且靠近 `railway=rail`。无法匹配的白名单站名保存在
`passenger-stations.json` 的 `source.passengerWhitelist.unmatchedNames`
中，不会猜测坐标。

OSM 没有全国一致的国铁“一等站/二等站”字段，因此页面只使用可追溯的三级显示：

- `major`：OSM `usage=main`；
- `station`：OSM `railway=station`；
- `halt`：OSM `railway=halt`。

G/C 字头优先高速铁路，D 字头适度偏好高速铁路，K/Z/T/Y 字头偏好普速铁路。
`stops` 中的每两个相邻站都是强制途经约束，因此补充关键途经站可以有效修正
只有起终点时可能出现的路径歧义。

## 校验

每次编辑后运行：

```powershell
D:\Anaconda\python.exe pipeline\tools\validate_data.py
```

校验器会检查重复 ID、日期、坐标、地点类型、行程引用和铁路底图结构。

## 页面录入

页面表单生成的 `footprint-update-*.json` 同时携带更新后的 `locations.json`
和 `journeys.json`。在项目根目录运行：

```powershell
D:\Anaconda\python.exe pipeline\tools\import_journey_bundle.py <更新包.json>
powershell -ExecutionPolicy Bypass -File pipeline/build.ps1
```

第一条命令导入源数据，第二条命令重新解析 OSM 坐标并生成实际铁路路线。
