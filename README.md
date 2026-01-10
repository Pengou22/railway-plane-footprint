# 空铁足迹-记录你的历史行程

## 简介

这是一个可以手动添加你的历史行程的网站，介于12306只保存最近一个月的行程信息，同时航旅纵横没办法手动添加铁路行程，所以自己做了一个小网站，来弥补之前行程没有被记录的遗憾，也同时学习一下Web开发的前端三件套，自己玩一玩。
A website that records the history of railway and plane journeys.

## 使用方法

直接修改 json 中相应文件的数据即可，各文件的含义如下：

- stations.json 存储火车站的数据信息，格式为 “"cqx": { "LatLng": [106.44, 29.50], "name": "重庆西"},”，其中 "cqx" 表示之后线路需要引用的站点简称，"LatLng" 表示经纬度，"name" 表示在地图中显示的名字；
- trains.json 存储火车路线的数据信息，格式为 “{"code": "G8888", "time": "20xx-xx-xx", "route": ["cqx", "szb"], "information": "xxx"},”，其中 "code" 表示车次号，"time" 表示乘坐时间，"route" 表示起点终点即填入 stations.json 的站点简称，"information" 表示值得记录的信息；
- airports.json 存储机场的数据信息，格式同 stations.json；
- flights.json 存储航班的数据信息，格式同 trains.json；
