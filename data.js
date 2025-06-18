// 记录火车站、高铁站地理位置
var station = {
    // '北京': { latLng: [39.90, 116.41], name: '北京', rank: 1 },
    // '上海': { latLng: [31.24, 121.50], name: '上海', rank: 1 },
    // '重庆': { latLng: [29.56, 106.54], name: '重庆', rank: 1 },
    'tna': { latLng: [30.22, 105.88], name: '潼南', rank: 1 },
    'hch': { latLng: [29.96, 106.28], name: '合川', rank: 1 },
    'cqb': { latLng: [29.61, 106.55], name: '重庆北', rank: 1 },
    'cqx': { latLng: [29.50, 106.44], name: '重庆西', rank: 1 },
    'gyd': { latLng: [26.66, 106.74], name: '贵阳东', rank: 0 },
    'gyb': { latLng: [26.62, 106.67], name: '贵阳北', rank: 0 },
    'gzn': { latLng: [22.99, 113.27], name: '广州南', rank: 1 },
    'szb': { latLng: [22.61, 114.03], name: '深圳北', rank: 1 },
    'lji': { latLng: [26.81, 100.25], name: '丽江', rank: 1 },
    'kmi': { latLng: [25.02, 102.72], name: '昆明', rank: 1 },
    'xgl': { latLng: [27.81, 99.69], name: '香格里拉', rank: 1 },
    'cdd': { latLng: [30.63, 104.14], name: '成都东', rank: 1 },
    'ghb': { latLng: [31.01, 104.28], name: '广汉北', rank: 1 },
    'xni': { latLng: [36.62, 101.81], name: '西宁', rank: 1 },
    'sni': { latLng: [30.54, 105.54], name: '遂宁', rank: 0 },
    'zyi': { latLng: [27.66, 106.95], name: '遵义', rank: 0 },
    'hme': { latLng: [22.86, 113.67], name: '虎门', rank: 0 },
    'ycd': { latLng: [29.37, 105.95], name: '永川东', rank: 0 },
    'rcb': { latLng: [29.43, 105.64], name: '荣昌北', rank: 0 },
    'njb': { latLng: [29.61, 105.08], name: '内江北', rank: 0 },
    'zyb': { latLng: [30.13, 104.68], name: '资阳北', rank: 0 },
    'glx': { latLng: [25.35, 110.27], name: '桂林西', rank: 0 },
    'dli': { latLng: [25.59, 100.22], name: '大理', rank: 0 },
    'gyu': { latLng: [32.45, 105.82], name: '广元', rank: 0 },
    'hdp': { latLng: [34.27, 104.23], name: '哈达铺', rank: 0 },
    'lzh': { latLng: [36.03, 103.85], name: '兰州', rank: 0 },
    // '': { latLng: [, ], name: '', rank: 1 },
    // '': { latLng: [, ], name: '', rank: 0 },
};
// setStationStyleByRank(station)

// 记录机场地理位置

// 记录路线
var lines = [
    // {
    //     information: '',
    //     time: '2024-01-21',
    //     route: []
    // },
    {
        information: 'G305',
        time: '2025-04-20',
        route: ['gzn', 'hme', 'szb']
    },
    {
        information: 'G6028',
        time: '2025-04-18',
        route: ['szb', 'hme', 'gzn']
    },
    {
        information: 'G2965',
        time: '2025-02-19',
        route: ['cqx', 'zyi', 'gyd', 'glx', 'gzn', 'hme', 'szb']
    },
    {
        information: 'D5160',
        time: '2024-02-19',
        route: ['tna', 'hch', 'cqx']
    },
    {
        information: 'G2882',
        time: '2025-01-18',
        route: ['gyb', 'zyi', 'cqx']
    },
    {
        information: 'G3708',
        time: '2025-01-18',
        route: ['gzn', 'glx', 'gyb']
    },
    {
        information: 'G2908',
        time: '2025-01-18',
        route: ['szb', 'hme', 'gzn']
    },
    {
        // 搭乘丽江至昆明的Y字头旅游专列
        information: 'Y754',
        time: '2024-09-17',
        route: ['lji', 'dli', 'kmi']
    },
    {
        information: 'C124',
        time: '2024-09-17',
        route: ['xgl', 'lji']
    },
    {
        // 搭乘昆明至丽江的Y字头旅游专列
        information: 'Y752',
        time: '2024-09-13',
        route: ['kmi', 'dli', 'lji']
    },
    {
        information: 'G2976',
        time: '2024-09-13',
        route: ['szb', 'hme', 'gzn', 'glx', 'gyb', 'kmi']
    },
    {
        information: 'G2965',
        time: '2024-08-24',
        route: ['cqx', 'zyi', 'gyb', 'glx', 'gzn', 'hme', 'szb']
    },
    {
        information: 'D5160',
        time: '2024-08-24',
        route: ['tna', 'hch', 'cqx']
    },
    {
        information: 'C78',
        time: '2024-08-21',
        route: ['cdd', 'sni', 'tna']
    },
    {
        // 非常吉利的高铁车次以及第一次经过成渝高铁全线
        information: 'G1888',
        time: '2024-08-20',
        route: ['cqx', 'ycd', 'rcb', 'njb', 'zyb', 'cdd', 'ghb']
    },
    {
        information: 'C80',
        time: '2024-08-18',
        route: ['hch', 'cqx']
    },
    {
        // 兰渝铁路全线返程
        information: 'K988',
        time: '2024-08-02',
        route: ['xni', 'lzh', 'hdp', 'gyu', 'hch', 'cqx']
    },
    {
        // 经过兰渝铁路全线
        information: 'D155',
        time: '2024-07-29',
        route: ['cqb', 'hch', 'gyu', 'hdp', 'lzh', 'xni']
    },
    {
        information: 'G2944',
        time: '2024-07-18',
        route: ['szb', 'hme', 'gzn', 'glx', 'gyb', 'zyi', 'cqx']
    },
    {
        information: 'G2943',
        time: '2024-03-02',
        route: ['cqx', 'zyi', 'gyb', 'glx', 'gzn', 'hme', 'szb']
    },
    {
        information: 'G2942',
        time: '2024-02-07',
        route: ['szb', 'hme', 'gzn', 'glx', 'gyb', 'zyi', 'cqx']
    },
    {
        information: 'G1021',
        time: '2024-01-19',
        route: ['gzn', 'hme', 'sxb']
    },
    {
        information: 'G6582',
        time: '2024-01-18',
        route: ['szb', 'hme', 'gzn']
    },
    // {
    //     information: '',
    //     time: '2024-01-21',
    //     route: []
    // },
]