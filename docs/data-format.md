# 地图数据格式

个人行程源数据采用版本 3 格式。人工维护的数据中不保存坐标；
坐标统一从 OpenStreetMap 快照生成的车站和机场目录中读取。

## journeys-railway.json 与 journeys-flight.json

铁路和航空行程分别保存在两个文件中，但都使用相同的版本和 `journeys` 数组结构。
铁路文件中的 `mode` 必须为 `train`，航空文件中的 `mode` 必须为 `flight`：

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

铁路行程只能引用 `stations.json` 中的名称，航班只能引用 `airports.json`
中的名称。校验器会拒绝未知名称和可能产生歧义的重名。
铁路站首先匹配客运站目录中的正式名称；只有正式名称不存在时才匹配别名。
若正式名称或别名仍命中多个对象，需在行程中改用能够唯一匹配的正式名称。

新增目录中已有的唯一站名或机场名时，不需要手工维护坐标或 OSM ID。
改变铁路途经站后应运行完整构建，让 `routes.json` 按新的途经顺序重新寻路。

## 生成数据

以下文件均由构建脚本生成，不应手动修改：

- `stations.json`：全国客运站坐标、OSM 证据和显示等级；
- `airports.json`：全国客运机场坐标、IATA/ICAO 和 OSM 证据，排除通用航空；
- `railways.geojson`：MapLibre 直接读取的全国铁路 `MultiLineString` 图层；
- `routes.json`：每次铁路行程沿 OSM 铁路网计算出的轨迹；
- `admin-boundaries-province.json`：DataV.GeoAtlas 全国省域 GeoJSON。

省域文件采用 `schemaVersion: 2`，`geoJSON.features` 中的每个元素都是
可交互的 `Polygon` 或 `MultiPolygon`。文件按行政区特征分行，既方便查看，
也避免把庞大的坐标数组逐项缩进。

`data/raw/boundaries/china-provinces-datav.json` 是未经处理的 DataV 原始输入；
`admin-boundaries-province.json` 是网页使用的运行时产物。构建器会过滤额外
附属要素、统一省名和属性、简化并舍入坐标，同时裁去会拉大地图包围盒的海南
低纬离岸小面，再补充版本与来源元数据。保留原始文件是为了能够调整规则后
稳定重建，而不是让网页直接承担原始数据兼容和清洗工作。

客运站白名单来自 `data/source/station_name.js`。该文件是一个
`var station_names = '@...';` JavaScript 字符串：记录以 `@` 分隔，字段以
`|` 分隔，11 个字段依次为站名简码、中文站名、电报码、全拼、简拼、序号、
城市代码、城市名、国家代码、国家名和英文名。构建时排除国家代码非空的境外
记录，再按中文站名匹配 OSM 国铁车站，由 OSM 提供坐标。

目录会排除地铁、轻轨、单轨、有轨电车和无法安全匹配坐标的同名站，并要求
OSM 对象位于省域面内且靠近 `railway=rail`。无法匹配的白名单站名保存在
`stations.json` 的 `source.passengerWhitelist.unmatchedNames`
中，不会猜测坐标。

OSM 没有全国一致的国铁“一等站/二等站”字段，因此页面只使用可追溯的三级显示：

- `major`：OSM `usage=main`；
- `station`：OSM `railway=station`；
- `halt`：OSM `railway=halt`。

G 字头优先高速铁路，C/D 字头适度偏好高速铁路，K/Z/T/Y 字头偏好普速铁路。
`stops` 中的每两个相邻站都是强制途经约束，因此补充关键途经站可以有效修正
只有起终点时可能出现的路径歧义。

## 校验

每次编辑后运行：

```powershell
D:\Anaconda\python.exe pipeline\tools\validate_data.py
```

校验器会检查重复 ID、日期、坐标、地点类型、行程引用和铁路底图结构。
