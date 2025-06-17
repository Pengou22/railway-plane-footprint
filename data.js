// 记录火车站、高铁站地理位置
var station = {
    // '北京': { latLng: [39.90, 116.41], name: '北京', style: { r: 8, fill: '#fd2020', stroke: '#000000' } },
    '北京': { latLng: [39.90, 116.41], name: '北京', rank: 1 },
    '上海': { latLng: [31.24, 121.50], name: '上海', rank: 1 },
    '重庆': { latLng: [29.56, 106.54], name: '重庆', rank: 1 },

};
// setStationStyleByRank(station)

// 记录机场地理位置

// 记录路线
var lines = [
    {
        information: 'D1234',
        time: '2023-10-01',
        route: ['重庆', '上海', '北京']
    },
    {
        information: 'D5678',
        time: '2025-01-21',
        route: ['上海test', 'marker-002', '北京']

    }
]