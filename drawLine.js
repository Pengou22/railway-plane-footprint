/**
 * 画多条路线，每条路线可整体选中，鼠标悬停显示信息
 * @param {Array} lines - 路线数组
 * @param {Object} station - 城市名到经纬度的映射
 */
function drawAllLines(lines, station) {
    var mapObj = $('#map').vectorMap('get', 'mapObject');
    var svg = $('#map svg');

    // 先移除所有旧路线
    svg.find('.custom-route-group').remove();

    lines.forEach(function (line, idx) {
        // 创建一个分组 <g>
        var group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        group.setAttribute('class', 'custom-route-group');
        group.setAttribute('data-info', line.information);
        group.setAttribute('data-time', line.time);

        // 依次画线
        for (var i = 0; i < line.route.length - 1; i++) {
            var cityA = line.route[i];
            var cityB = line.route[i + 1];
            if (!station[cityA] || !station[cityB]) continue;
            var p1 = mapObj.latLngToPoint(station[cityA].latLng[0], station[cityA].latLng[1]);
            var p2 = mapObj.latLngToPoint(station[cityB].latLng[0], station[cityB].latLng[1]);
            var lineElem = document.createElementNS('http://www.w3.org/2000/svg', 'line');
            lineElem.setAttribute('x1', p1.x);
            lineElem.setAttribute('y1', p1.y);
            lineElem.setAttribute('x2', p2.x);
            lineElem.setAttribute('y2', p2.y);
            lineElem.setAttribute('stroke', 'blue');
            lineElem.setAttribute('stroke-width', 3);
            lineElem.setAttribute('opacity', 0.7);
            group.appendChild(lineElem);
        }

        // 鼠标事件
        group.addEventListener('mouseenter', function (e) {
            this.setAttribute('opacity', 1);
            // 显示信息（可用自定义弹窗或tooltip）
            var info = this.getAttribute('data-info');
            var time = this.getAttribute('data-time');
            showTooltip(e, info + ' ' + time);
        });
        group.addEventListener('mouseleave', function (e) {
            this.setAttribute('opacity', 0.7);
            hideTooltip();
        });
        group.addEventListener('click', function (e) {
            // 选中效果
            $('.custom-route-group').attr('stroke', 'blue');
            $(this).find('line').attr('stroke', 'red');
        });

        svg[0].appendChild(group);
    });
}

// 简单的tooltip实现
function showTooltip(e, text) {
    var tooltip = $('#custom-tooltip');
    if (tooltip.length === 0) {
        tooltip = $('<div id="custom-tooltip"></div>').css({
            position: 'absolute',
            background: '#fff',
            border: '1px solid #333',
            padding: '4px 8px',
            'border-radius': '4px',
            'pointer-events': 'none',
            'z-index': 9999
        }).appendTo('body');
    }
    tooltip.text(text).show().css({
        left: e.clientX + 10,
        top: e.clientY + 10
    });
}
function hideTooltip() {
    $('#custom-tooltip').hide();
}



function setStationStyleByRank(station) {
    Object.values(station).forEach(function (item) {
        // 根据 rank 设置 style
        if (item.rank === 0) {
            item.style = { r: 0, fill: '#fd2020', stroke: '#000' };
        } else if (item.rank === 1) {
            item.style = { r: 6, fill: '#fd2020', stroke: '#000' };
        } else if (item.rank === 2) {
            item.style = { r: 8, fill: '#fd8888', stroke: '#333' };
        } else {
            item.style = { r: 6, fill: '#aaa', stroke: '#666' };
        }
    });
}