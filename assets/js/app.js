"use strict";

(() => {
  const mapElement = document.getElementById("china-map");
  const loadingElement = document.getElementById("loading-status");
  const errorBanner = document.getElementById("error-banner");
  const errorMessage = document.getElementById("error-message");
  const summaryElement = document.getElementById("journey-summary");
  const railwayToggle = document.getElementById("railway-layer-toggle");
  const journeyFilterToggle = document.getElementById(
    "journey-filter-toggle"
  );
  const journeyFilterPanel = document.getElementById("journey-filter-panel");
  const journeyYearFilter = document.getElementById("journey-year-filter");
  const journeyMonthFilter = document.getElementById("journey-month-filter");
  const historyJourneyButton = document.getElementById(
    "history-journey-button"
  );
  const addJourneyButton = document.getElementById("add-journey-button");
  const journeyDialog = document.getElementById("journey-dialog");
  const journeyHistoryPanel = document.getElementById(
    "journey-history-panel"
  );
  const journeyHistoryList = document.getElementById("journey-history-list");
  const historyFilterSummary = document.getElementById(
    "history-filter-summary"
  );
  const clearJourneyHighlightButton = document.getElementById(
    "clear-journey-highlight"
  );
  const journeyForm = document.getElementById("journey-form");
  const journeyModeInput = document.getElementById("journey-mode");
  const journeyStartInput = document.getElementById("journey-start");
  const journeyViaInput = document.getElementById("journey-via");
  const journeyEndInput = document.getElementById("journey-end");
  const journeyLocationOptions = document.getElementById(
    "journey-location-options"
  );
  const journeyFormStatus = document.getElementById("journey-form-status");
  const modeButtons = Array.from(
    document.querySelectorAll("#mode-switch [data-mode]")
  );

  const chart = echarts.init(mapElement, null, {
    renderer: "canvas",
    useDirtyRect: true,
  });
  const prefersReducedMotion = window.matchMedia(
    "(prefers-reduced-motion: reduce)"
  ).matches;
  const state = {
    mode: "all",
    showRailwayNetwork: true,
    year: "all",
    month: "all",
    selectedJourneyId: null,
    hoveredJourneyId: null,
  };
  const provinceBoundary = {
    url: "data/generated/admin-boundaries-province.json",
    mapName: "china-province-detailed",
  };
  const sources = {};
  let provinceBoundaryPromise = null;
  let layers = null;
  let trainAnimations = [];
  let animationFrame = 0;
  let lastAnimationUpdate = 0;
  let mapRoaming = false;
  let mapPointerDown = false;
  let roamResumeTimer = 0;
  let flightEffectsPaused = false;

  function loadJson(url) {
    return fetch(url, { cache: "no-cache" }).then((response) => {
      if (!response.ok) {
        throw new Error(`${url} 请求失败（${response.status}）`);
      }
      return response.json();
    });
  }

  function downloadJson(filename, value) {
    const blob = new Blob([`${JSON.stringify(value, null, 2)}\n`], {
      type: "application/json;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }

  function placeIndex(document) {
    if (document.schemaVersion !== 1 || !Array.isArray(document.places)) {
      throw new Error("places.json 的数据版本不受支持");
    }
    const locations = new Map();
    document.places.forEach((location) => {
      if (locations.has(location.name)) {
        throw new Error(`地点名称 ${location.name} 重复，无法解析行程`);
      }
      locations.set(location.name, location);
    });
    return locations;
  }

  function stationCatalog(document) {
    if (document.schemaVersion !== 1 || !Array.isArray(document.stations)) {
      throw new Error("passenger-stations.json 的数据版本不受支持");
    }
    return document.stations;
  }

  function stationLookup(stations) {
    const lookup = new Map();
    stations.forEach((station) => {
      const names = [station.name, ...(station.aliases || [])];
      names.forEach((name) => {
        const key = normalizeStationName(name);
        if (!lookup.has(key)) {
          lookup.set(key, []);
        }
        lookup.get(key).push(station);
      });
    });
    return lookup;
  }

  function nearestCatalogStation(location, lookup, maximumDistanceKm = 8) {
    const candidates = lookup.get(normalizeStationName(location.name)) || [];
    let best = null;
    let bestDistance = Infinity;
    candidates.forEach((candidate) => {
      const distance = coordinateDistanceKm(
        location.coordinates,
        candidate.coordinates
      );
      if (distance < bestDistance) {
        best = candidate;
        bestDistance = distance;
      }
    });
    return bestDistance <= maximumDistanceKm ? best : null;
  }

  function journeyInfo(journey, locations, generatedRoute) {
    const stopNames = journey.stops.map((stopName) => {
      const location = locations.get(stopName);
      if (!location) {
        throw new Error(`行程 ${journey.id} 引用了未知地点 ${stopName}`);
      }
      return location.name;
    });
    return {
      code: journey.code,
      date: journey.date,
      start: stopNames[0],
      end: stopNames[stopNames.length - 1],
      via: stopNames.slice(1, -1),
      note: journey.note || "",
      distanceKm: generatedRoute ? generatedRoute.distanceKm : null,
    };
  }

  function routeKey(start, end) {
    return `${start.join(",")}->${end.join(",")}`;
  }

  function journeyCoordinates(journey, locations, generatedRoutes) {
    if (journey.mode === "train") {
      const generatedRoute = generatedRoutes.get(journey.id);
      if (!generatedRoute) {
        throw new Error(`铁路行程 ${journey.id} 缺少生成路线`);
      }
      return generatedRoute.coords;
    }
    return journey.stops.map((stopName) => {
      const location = locations.get(stopName);
      if (!location) {
        throw new Error(`行程 ${journey.id} 引用了未知地点 ${stopName}`);
      }
      return location.coordinates;
    });
  }

  function buildJourneyLayers(journeys, locations, mode, generatedRoutes) {
    const groups = new Map();
    const repeatedRoutes = new Map();
    const isFlight = mode === "flight";

    journeys
      .filter((journey) => journey.mode === mode)
      .forEach((journey) => {
        const generatedRoute = generatedRoutes.get(journey.id);
        if (!isFlight && !generatedRoute) {
          throw new Error(`铁路行程 ${journey.id} 缺少生成路线`);
        }
        const coordinates = journeyCoordinates(
          journey,
          locations,
          generatedRoutes
        );
        const start = coordinates[0];
        const end = coordinates[coordinates.length - 1];
        const symbol = isFlight
          ? getJourneySymbol(mode, journey.code, start, end)
          : "none";
        const symbolSize = getJourneySymbolSize(mode, journey.code);
        const key = isFlight
          ? `curve|${symbol}|${symbolSize.join(",")}`
          : "polyline";

        if (!groups.has(key)) {
          groups.set(key, {
            polyline: !isFlight,
            symbol,
            symbolSize,
            data: [],
          });
        }

        const repetitionKey = routeKey(start, end);
        const repetition = repeatedRoutes.get(repetitionKey) || 0;
        repeatedRoutes.set(repetitionKey, repetition + 1);

        groups.get(key).data.push({
          journeyId: journey.id,
          name: journey.code,
          coords: coordinates,
          info: journeyInfo(journey, locations, generatedRoute),
          lineStyle: {
            curveness: isFlight ? 0.18 + repetition * 0.055 : 0,
          },
        });
      });

    return Array.from(groups.values()).map((group, index) => ({
      id: `journey-${mode}-${index}`,
      name: isFlight ? "航空足迹" : "铁路足迹",
      type: "lines",
      coordinateSystem: "geo",
      polyline: group.polyline,
      data: group.data,
      z: 6,
      effect: {
        show:
          isFlight && !prefersReducedMotion && !flightEffectsPaused,
        period: 7.5,
        trailLength: 0,
        symbol: group.symbol,
        symbolSize: group.symbolSize,
      },
      lineStyle: {
        width: isFlight ? 2.1 : 2.4,
        opacity: 0.9,
        color: isFlight ? "#f97316" : "#0284c7",
      },
      emphasis: {
        lineStyle: {
          width: isFlight ? 3.5 : 4,
          opacity: 1,
        },
      },
    }));
  }

  function selectedJourneyCurveness(journeyId) {
    for (const layer of layers.flightJourneys) {
      const item = layer.data.find(
        (candidate) => candidate.journeyId === journeyId
      );
      if (item) {
        return item.lineStyle.curveness;
      }
    }
    return 0.18;
  }

  function buildJourneyHighlightLayer(journey, kind) {
    const isFlight = journey.mode === "flight";
    const persistent = kind === "selected";
    const generatedRoute = sources.generatedRoutes.get(journey.id);
    const coordinates = journeyCoordinates(
      journey,
      sources.locations,
      sources.generatedRoutes
    );
    const color = isFlight ? "#c2410c" : "#075985";
    return {
      id: `${kind}-journey-highlight`,
      name: persistent ? "选中行程" : "预览行程",
      type: "lines",
      coordinateSystem: "geo",
      polyline: !isFlight,
      data: [
        {
          journeyId: journey.id,
          name: journey.code,
          coords: coordinates,
          info: journeyInfo(journey, sources.locations, generatedRoute),
          lineStyle: {
            curveness: isFlight
              ? selectedJourneyCurveness(journey.id)
              : 0,
          },
        },
      ],
      z: persistent ? 12 : 11,
      silent: false,
      animation: false,
      lineStyle: {
        color,
        width: isFlight
          ? persistent
            ? 5.5
            : 4.5
          : persistent
            ? 6
            : 5,
        opacity: 1,
        shadowBlur: 8,
        shadowColor: isFlight
          ? "rgba(249, 115, 22, 0.5)"
          : "rgba(14, 165, 233, 0.55)",
      },
      emphasis: {
        lineStyle: {
          width: isFlight ? 7 : 7.5,
          opacity: 1,
        },
      },
    };
  }

  function cumulativeRoute(coords) {
    const offsets = [0];
    let total = 0;
    for (let index = 1; index < coords.length; index += 1) {
      total += coordinateDistanceKm(coords[index - 1], coords[index]);
      offsets.push(total);
    }
    return { offsets, total };
  }

  function buildTrainAnimations(journeys, locations, generatedRoutes) {
    return journeys
      .filter((journey) => journey.mode === "train")
      .map((journey, index) => {
        const route = generatedRoutes.get(journey.id);
        if (!route) {
          throw new Error(`铁路行程 ${journey.id} 缺少生成路线`);
        }
        const start = route.coords[0];
        const end = route.coords[route.coords.length - 1];
        const cumulative = cumulativeRoute(route.coords);
        return {
          id: journey.id,
          code: journey.code,
          coords: route.coords,
          offsets: cumulative.offsets,
          total: cumulative.total,
          phase: index / Math.max(1, journeys.length),
          symbol: getJourneySymbol("train", journey.code, start, end),
          symbolSize: getJourneySymbolSize("train", journey.code),
          info: journeyInfo(journey, locations, route),
        };
      });
  }

  function routePosition(animation, progress) {
    const target = progress * animation.total;
    let low = 0;
    let high = animation.offsets.length - 1;
    while (low < high) {
      const middle = Math.floor((low + high + 1) / 2);
      if (animation.offsets[middle] <= target) {
        low = middle;
      } else {
        high = middle - 1;
      }
    }
    const index = Math.min(low, animation.coords.length - 2);
    const segmentStart = animation.offsets[index];
    const segmentEnd = animation.offsets[index + 1];
    const segmentProgress =
      segmentEnd > segmentStart
        ? (target - segmentStart) / (segmentEnd - segmentStart)
        : 0;
    const start = animation.coords[index];
    const end = animation.coords[index + 1];
    return [
      start[0] + (end[0] - start[0]) * segmentProgress,
      start[1] + (end[1] - start[1]) * segmentProgress,
    ];
  }

  function movingTrainData(timestamp) {
    const period = 18000;
    return trainAnimations.map((animation) => {
      const progress = prefersReducedMotion
        ? 0.5
        : ((timestamp / period + animation.phase) % 1 + 1) % 1;
      return {
        id: animation.id,
        name: animation.code,
        value: routePosition(animation, progress),
        symbol: animation.symbol,
        symbolSize: animation.symbolSize,
        info: animation.info,
      };
    });
  }

  function buildMovingTrainLayer() {
    return {
      id: "moving-train-markers",
      name: "运行列车",
      type: "scatter",
      coordinateSystem: "geo",
      data: movingTrainData(0),
      silent: true,
      animation: false,
      z: 9,
      tooltip: {
        show: false,
      },
    };
  }

  function animateTrains(timestamp) {
    if (
      !prefersReducedMotion &&
      layers &&
      state.mode !== "flight" &&
      !mapRoaming &&
      !document.hidden &&
      timestamp - lastAnimationUpdate >= 140
    ) {
      lastAnimationUpdate = timestamp;
      chart.setOption(
        {
          series: [
            {
              id: "moving-train-markers",
              data: movingTrainData(timestamp),
            },
          ],
        },
        {
          lazyUpdate: true,
          silent: true,
        }
      );
    }
    animationFrame = requestAnimationFrame(animateTrains);
  }

  function endpointCounts(journeys, mode) {
    const counts = new Map();
    journeys
      .filter((journey) => journey.mode === mode)
      .forEach((journey) => {
        const endpoints = [
          journey.stops[0],
          journey.stops[journey.stops.length - 1],
        ];
        endpoints.forEach((locationName) => {
          counts.set(locationName, (counts.get(locationName) || 0) + 1);
        });
      });
    return counts;
  }

  function stationSymbolSize(level) {
    const sizes = { major: 22, station: 17, halt: 13 };
    return sizes[level] || sizes.station;
  }

  function buildLocationLayer(journeys, locations, mode, catalogLookup) {
    const counts = endpointCounts(journeys, mode);
    const locationType = mode === "train" ? "station" : "airport";
    const isAirport = locationType === "airport";
    const data = Array.from(counts.entries()).map(([locationName, count]) => {
      const location = locations.get(locationName);
      const catalogStation = isAirport
        ? null
        : nearestCatalogStation(location, catalogLookup);
      const level = catalogStation ? catalogStation.level : "station";
      return {
        name: location.name,
        value: [...location.coordinates, count],
        visitCount: count,
        stationLevel: level,
        stationStatus: isAirport ? "visited-airport" : "visited",
        symbolSize: isAirport ? 21 : stationSymbolSize(level),
        catalogOsmId: catalogStation ? catalogStation.osmId : null,
      };
    });

    return {
      id: `${locationType}-markers`,
      name: isAirport ? "到访机场" : "到访车站",
      type: "scatter",
      coordinateSystem: "geo",
      data,
      symbol: isAirport
        ? "image://./assets/images/airport.png"
        : "image://./assets/images/station-visited.png",
      z: 10,
      label: {
        formatter: "{b}",
        position: "bottom",
        distance: 3,
        show: true,
        color: "#172033",
        fontSize: 10,
        fontWeight: 600,
        textBorderColor: "rgba(255,255,255,0.9)",
        textBorderWidth: 3,
      },
      labelLayout: {
        hideOverlap: true,
      },
      itemStyle: {
        shadowBlur: 8,
        shadowColor: "rgba(15, 23, 42, 0.3)",
      },
      emphasis: {
        scale: 1.45,
        label: {
          show: true,
        },
      },
    };
  }

  function buildRailwayLayers(document) {
    if (document.schemaVersion !== 1 || !Array.isArray(document.lines)) {
      throw new Error("railways.json 的数据版本不受支持");
    }
    const styles = {
      conventional: {
        name: "普速铁路网",
        color: "#475569",
        width: 0.65,
        opacity: 0.32,
      },
      highspeed: {
        name: "高速铁路网",
        color: "#64748b",
        width: 0.85,
        opacity: 0.42,
      },
    };
    return Object.entries(styles).map(([category, style]) => ({
      id: `railway-network-${category}`,
      name: style.name,
      type: "lines",
      coordinateSystem: "geo",
      polyline: true,
      large: true,
      largeThreshold: 1200,
      progressive: 5000,
      progressiveThreshold: 3000,
      silent: true,
      animation: false,
      data: document.lines
        .filter((line) => line.category === category)
        .map((line) => ({
          name: line.name || "",
          coords: line.coords,
        })),
      lineStyle: {
        color: style.color,
        width: style.width,
        opacity: style.opacity,
      },
      z: 1,
    }));
  }

  function validateProvinceBoundary(document) {
    if (
      document.schemaVersion !== 2 ||
      document.level !== "province" ||
      document.geoJSON?.type !== "FeatureCollection" ||
      !Array.isArray(document.geoJSON.features)
    ) {
      throw new Error("行政边界数据版本不受支持");
    }
  }

  function loadProvinceBoundary() {
    if (!provinceBoundaryPromise) {
      provinceBoundaryPromise = loadJson(provinceBoundary.url).then(
        (document) => {
          validateProvinceBoundary(document);
          echarts.registerMap(provinceBoundary.mapName, document.geoJSON);
          return document;
        }
      );
    }
    return provinceBoundaryPromise;
  }

  function provinceGeoOption() {
    return {
      map: provinceBoundary.mapName,
      roam: true,
      zoom: 1.18,
      scaleLimit: {
        min: 1,
        max: 24,
      },
      itemStyle: {
        areaColor: "#dfe5e6",
        opacity: 0.83,
        borderColor: "rgba(42, 55, 72, 0.62)",
        borderWidth: 0.8,
      },
      regions: Object.entries(provinceColors).map(([name, colors]) => ({
        name,
        itemStyle: {
          areaColor: colors.normal,
          opacity: 0.83,
        },
        emphasis: {
          itemStyle: {
            areaColor: colors.hover,
            opacity: 0.96,
          },
        },
      })),
      emphasis: {
        label: {
          show: true,
          color: "#0f172a",
          fontSize: 12,
          fontWeight: 600,
          backgroundColor: "rgba(255, 255, 255, 0.9)",
          borderRadius: 4,
          padding: [3, 5],
        },
        itemStyle: {
          areaColor: "#aebbc1",
          opacity: 0.98,
          shadowBlur: 14,
          shadowColor: "rgba(15, 23, 42, 0.28)",
          borderColor: "rgba(15, 23, 42, 0.78)",
          borderWidth: 1.2,
        },
      },
      tooltip: {
        show: false,
      },
    };
  }

  function stationLevelLabel(level) {
    return {
      major: "主要站",
      station: "普通站",
      halt: "乘降所",
    }[level] || "客运站";
  }

  function tooltipFormatter(params) {
    if (params.seriesType === "lines" && params.data && params.data.info) {
      const info = params.data.info;
      const via = info.via.length
        ? `<div><span>途经</span>${escapeHtml(info.via.join(" · "))}</div>`
        : "";
      const note = info.note
        ? `<div class="tooltip-note">${escapeHtml(info.note)}</div>`
        : "";
      const distance =
        info.distanceKm !== null
          ? `<div><span>轨道里程</span>${escapeHtml(info.distanceKm)} km</div>`
          : "";
      return `
        <div class="journey-tooltip">
          <strong>${escapeHtml(info.code)}</strong>
          <div><span>日期</span>${escapeHtml(info.date)}</div>
          <div><span>行程</span>${escapeHtml(info.start)} → ${escapeHtml(info.end)}</div>
          ${via}
          ${distance}
          ${note}
        </div>
      `;
    }

    if (params.seriesType === "scatter" && params.data) {
      const visitText =
        params.data.stationStatus === "visited-airport"
          ? "到达或出发"
          : "作为起点或终点";
      return `
        <div class="journey-tooltip">
          <strong>${escapeHtml(params.name)}</strong>
          <div><span>${visitText}</span>${params.data.visitCount} 次</div>
          ${
            params.data.stationLevel
              ? `<div><span>类别</span>${stationLevelLabel(params.data.stationLevel)}</div>`
              : ""
          }
        </div>
      `;
    }
    return escapeHtml(params.name);
  }

  function baseOption() {
    return {
      backgroundColor: "transparent",
      animation: false,
      animationDurationUpdate: 0,
      geo: provinceGeoOption(),
      tooltip: {
        trigger: "item",
        confine: true,
        borderWidth: 0,
        padding: 0,
        backgroundColor: "transparent",
        formatter: tooltipFormatter,
        extraCssText: "box-shadow:none;",
      },
      series: [],
    };
  }

  function journeyMatchesDateFilter(journey) {
    const [year, month] = journey.date.split("-");
    return (
      (state.year === "all" || year === state.year) &&
      (state.month === "all" || month === state.month)
    );
  }

  function filteredJourneys() {
    return sources.journeys.filter(journeyMatchesDateFilter);
  }

  function visibleJourneys() {
    return filteredJourneys().filter(
      (journey) => state.mode === "all" || journey.mode === state.mode
    );
  }

  function journeyIsVisible(journey) {
    return (
      journeyMatchesDateFilter(journey) &&
      (state.mode === "all" || journey.mode === state.mode)
    );
  }

  function rebuildJourneyLayers() {
    const journeys = filteredJourneys();
    trainAnimations = buildTrainAnimations(
      journeys,
      sources.locations,
      sources.generatedRoutes
    );
    layers.trainJourneys = buildJourneyLayers(
      journeys,
      sources.locations,
      "train",
      sources.generatedRoutes
    );
    layers.flightJourneys = buildJourneyLayers(
      journeys,
      sources.locations,
      "flight",
      sources.generatedRoutes
    );
    layers.movingTrains = buildMovingTrainLayer();
    layers.stationMarkers = buildLocationLayer(
      journeys,
      sources.locations,
      "train",
      sources.stationLookup
    );
    layers.airportMarkers = buildLocationLayer(
      journeys,
      sources.locations,
      "flight",
      sources.stationLookup
    );

    const selectedJourney = sources.journeys.find(
      (journey) => journey.id === state.selectedJourneyId
    );
    layers.selectedJourney = selectedJourney
      ? buildJourneyHighlightLayer(selectedJourney, "selected")
      : null;
    const hoveredJourney = sources.journeys.find(
      (journey) => journey.id === state.hoveredJourneyId
    );
    layers.hoveredJourney =
      hoveredJourney && hoveredJourney.id !== state.selectedJourneyId
        ? buildJourneyHighlightLayer(hoveredJourney, "hovered")
        : null;
  }

  function visibleSeries() {
    const series = [];
    if (state.showRailwayNetwork) {
      series.push(...layers.railwayNetwork);
    }
    if (state.mode === "all" || state.mode === "train") {
      series.push(
        ...layers.trainJourneys,
        layers.stationMarkers,
        layers.movingTrains
      );
    }
    if (state.mode === "all" || state.mode === "flight") {
      series.push(...layers.flightJourneys, layers.airportMarkers);
    }
    const selectedJourney = sources.journeys?.find(
      (journey) => journey.id === state.selectedJourneyId
    );
    const hoveredJourney = sources.journeys?.find(
      (journey) => journey.id === state.hoveredJourneyId
    );
    if (
      layers.hoveredJourney &&
      hoveredJourney &&
      hoveredJourney.id !== state.selectedJourneyId &&
      journeyIsVisible(hoveredJourney)
    ) {
      series.push(layers.hoveredJourney);
    }
    if (
      layers.selectedJourney &&
      selectedJourney &&
      journeyIsVisible(selectedJourney)
    ) {
      series.push(layers.selectedJourney);
    }
    return series;
  }

  function renderLayers() {
    chart.setOption(
      {
        series: visibleSeries(),
      },
      {
        lazyUpdate: true,
        replaceMerge: ["series"],
      }
    );
  }

  function renderHoverHighlight() {
    const journey = sources.journeys?.find(
      (candidate) => candidate.id === state.hoveredJourneyId
    );
    const series =
      layers.hoveredJourney && journey && journeyIsVisible(journey)
        ? layers.hoveredJourney
        : {
            id: "hovered-journey-highlight",
            name: "预览行程",
            type: "lines",
            coordinateSystem: "geo",
            data: [],
            silent: true,
            animation: false,
          };
    chart.setOption(
      { series: [series] },
      {
        lazyUpdate: true,
        silent: true,
      }
    );
  }

  function updateMode(mode) {
    state.mode = mode;
    modeButtons.forEach((button) => {
      const active = button.dataset.mode === mode;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    renderLayers();
    renderJourneyHistory();
    updateSummary(visibleJourneys());
  }

  function locationOptionsForMode(mode) {
    if (mode === "flight") {
      return sources.locationDocument.locations
        .filter((location) => location.type === "airport")
        .map((location) => location.name)
        .sort((first, second) => first.localeCompare(second, "zh-CN"));
    }
    return Array.from(
      new Set(sources.passengerStations.map((station) => station.name))
    ).sort((first, second) => first.localeCompare(second, "zh-CN"));
  }

  function refreshLocationOptions(query = "") {
    const normalizedQuery = normalizeStationName(query);
    const options = locationOptionsForMode(journeyModeInput.value)
      .filter(
        (name) =>
          !normalizedQuery ||
          normalizeStationName(name).includes(normalizedQuery)
      )
      .slice(0, 120);
    journeyLocationOptions.replaceChildren(
      ...options.map((name) => {
        const option = document.createElement("option");
        option.value = name;
        return option;
      })
    );
  }

  function splitViaStops(value) {
    return value
      .split(/[\n,，;；→>]+/)
      .map((name) => name.trim())
      .filter(Boolean);
  }

  function copyDocument(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function resolveFormLocation(name, mode, locationsByName) {
    const existing = locationsByName.get(name);
    if (existing) {
      const expectedType = mode === "train" ? "station" : "airport";
      if (existing.type !== expectedType) {
        throw new Error(`${name} 不是${expectedType === "station" ? "火车站" : "机场"}`);
      }
      return existing;
    }
    if (mode === "flight") {
      throw new Error(`机场 ${name} 尚未收录，请先在 locations.json 中添加`);
    }

    const matches =
      sources.stationLookup.get(normalizeStationName(name)) || [];
    const distinctMatches = Array.from(
      new Map(matches.map((station) => [station.osmId, station])).values()
    );
    if (!distinctMatches.length) {
      throw new Error(`全国客运站目录中找不到 ${name}`);
    }
    if (distinctMatches.length > 1) {
      throw new Error(
        `${name} 存在 ${distinctMatches.length} 个同名站，请先在 locations.json 中用 osmId 指定`
      );
    }
    const station = distinctMatches[0];
    return {
      id: `osm-${station.osmId.toLowerCase().replace(/[^a-z0-9-]/g, "-")}`,
      type: "station",
      name: station.name,
      osmId: station.osmId,
    };
  }

  function uniqueJourneyId(journeys, mode, date, code) {
    const base = `${mode}-${date}-${code}`
      .toLowerCase()
      .replace(/[^a-z0-9-]+/g, "-")
      .replace(/^-+|-+$/g, "");
    const ids = new Set(journeys.map((journey) => journey.id));
    if (!ids.has(base)) {
      return base;
    }
    let suffix = 2;
    while (ids.has(`${base}-${suffix}`)) {
      suffix += 1;
    }
    return `${base}-${suffix}`;
  }

  function submitJourneyForm(event) {
    event.preventDefault();
    journeyFormStatus.textContent = "";
    try {
      const formData = new FormData(journeyForm);
      const mode = String(formData.get("mode") || "");
      const code = String(formData.get("code") || "").trim().toUpperCase();
      const date = String(formData.get("date") || "");
      const start = String(formData.get("start") || "").trim();
      const end = String(formData.get("end") || "").trim();
      const note = String(formData.get("note") || "").trim();
      const requestedStops = [
        start,
        ...splitViaStops(String(formData.get("via") || "")),
        end,
      ];
      if (!code || !date || !start || !end) {
        throw new Error("请完整填写日期、班次、起点和终点");
      }

      const locationDocument = copyDocument(sources.locationDocument);
      const journeyDocument = copyDocument(sources.journeyDocument);
      const locationsByName = new Map(
        locationDocument.locations.map((location) => [
          location.name,
          location,
        ])
      );
      const resolvedStops = requestedStops.map((name) => {
        const location = resolveFormLocation(name, mode, locationsByName);
        if (!locationsByName.has(location.name)) {
          locationDocument.locations.push(location);
          locationsByName.set(location.name, location);
        }
        return location.name;
      });
      const journey = {
        id: uniqueJourneyId(
          journeyDocument.journeys,
          mode,
          date,
          code
        ),
        mode,
        code,
        date,
        stops: resolvedStops,
      };
      if (note) {
        journey.note = note;
      }
      journeyDocument.journeys.push(journey);
      journeyDocument.journeys.sort(
        (first, second) =>
          second.date.localeCompare(first.date) ||
          first.id.localeCompare(second.id)
      );

      const bundle = {
        schemaVersion: 1,
        generatedAt: new Date().toISOString(),
        locations: locationDocument,
        journeys: journeyDocument,
      };
      const filename = `footprint-update-${date}-${code.toLowerCase()}.json`;
      downloadJson(filename, bundle);
      const addedLocations =
        locationDocument.locations.length -
        sources.locationDocument.locations.length;
      journeyFormStatus.textContent =
        `已下载 ${filename}。新增 ${addedLocations} 个地点；导入并重建后路线才会出现在地图上。`;
      journeyFormStatus.classList.add("success");
    } catch (error) {
      journeyFormStatus.textContent = error.message || "无法生成行程更新包";
      journeyFormStatus.classList.remove("success");
    }
  }

  function historyJourneyItem(journey) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "history-journey-item";
    button.classList.toggle("selected", journey.id === state.selectedJourneyId);
    button.setAttribute(
      "aria-pressed",
      String(journey.id === state.selectedJourneyId)
    );

    const badge = document.createElement("span");
    badge.className = `history-mode-badge ${journey.mode}`;
    badge.textContent = journey.mode === "train" ? "铁路" : "航空";

    const main = document.createElement("span");
    main.className = "history-journey-main";

    const heading = document.createElement("span");
    heading.className = "history-journey-heading";
    const code = document.createElement("strong");
    code.textContent = journey.code;
    const date = document.createElement("time");
    date.dateTime = journey.date;
    date.textContent = journey.date;
    heading.append(code, date);

    const route = document.createElement("span");
    route.className = "history-route";
    route.textContent =
      `${journey.stops[0]} → ${journey.stops[journey.stops.length - 1]}`;
    main.append(heading, route);

    if (journey.stops.length > 2) {
      const via = document.createElement("span");
      via.className = "history-via";
      via.textContent = `途经：${journey.stops.slice(1, -1).join("、")}`;
      main.append(via);
    }

    button.append(badge, main);
    button.addEventListener("mouseenter", () => previewJourney(journey.id));
    button.addEventListener("mouseleave", () => clearJourneyPreview(journey.id));
    button.addEventListener("focus", () => previewJourney(journey.id));
    button.addEventListener("blur", () => clearJourneyPreview(journey.id));
    button.addEventListener("click", () => selectJourney(journey.id));
    return button;
  }

  function renderJourneyHistory() {
    const journeys = visibleJourneys()
      .slice()
      .sort(
        (first, second) =>
          second.date.localeCompare(first.date) ||
          first.code.localeCompare(second.code, "zh-CN")
      );
    if (journeys.length) {
      journeyHistoryList.replaceChildren(...journeys.map(historyJourneyItem));
    } else {
      const empty = document.createElement("p");
      empty.className = "history-empty";
      empty.textContent = "这个分类下还没有历史行程。";
      journeyHistoryList.replaceChildren(empty);
    }

    clearJourneyHighlightButton.disabled = !state.selectedJourneyId;
    const modeLabel = {
      all: "全部方式",
      train: "铁路",
      flight: "航空",
    }[state.mode];
    const yearLabel = state.year === "all" ? "全部年份" : `${state.year} 年`;
    const monthLabel =
      state.month === "all" ? "全部月份" : `${Number(state.month)} 月`;
    historyFilterSummary.textContent =
      `${modeLabel} · ${yearLabel} · ${monthLabel} · ${journeys.length} 段` +
      "；悬停预览，点击固定加粗。";
    historyJourneyButton.textContent = "历史行程";
  }

  function findJourney(journeyId) {
    return sources.journeys.find(
      (journey) => journey.id === journeyId
    );
  }

  function previewJourney(journeyId) {
    const journey = findJourney(journeyId);
    if (!journey || !journeyIsVisible(journey)) {
      return;
    }
    state.hoveredJourneyId = journey.id;
    layers.hoveredJourney =
      journey.id === state.selectedJourneyId
        ? null
        : buildJourneyHighlightLayer(journey, "hovered");
    renderHoverHighlight();
  }

  function clearJourneyPreview(journeyId) {
    if (state.hoveredJourneyId !== journeyId) {
      return;
    }
    state.hoveredJourneyId = null;
    layers.hoveredJourney = null;
    renderHoverHighlight();
  }

  function selectJourney(journeyId) {
    const journey = sources.journeys.find(
      (candidate) => candidate.id === journeyId
    );
    if (!journey) {
      return;
    }
    state.selectedJourneyId = journey.id;
    state.hoveredJourneyId = null;
    layers.hoveredJourney = null;
    layers.selectedJourney = buildJourneyHighlightLayer(
      journey,
      "selected"
    );
    renderJourneyHistory();
    renderLayers();
  }

  function clearJourneySelection() {
    state.selectedJourneyId = null;
    layers.selectedJourney = null;
    renderJourneyHistory();
    renderLayers();
  }

  function setFlightEffectsPaused(paused) {
    if (flightEffectsPaused === paused) {
      return;
    }
    flightEffectsPaused = paused;
    if (!layers) {
      return;
    }
    const show = !paused && !prefersReducedMotion;
    layers.flightJourneys.forEach((layer) => {
      layer.effect.show = show;
    });
    if (state.mode !== "train" && layers.flightJourneys.length) {
      chart.setOption(
        {
          series: layers.flightJourneys.map((layer) => ({
            id: layer.id,
            effect: { show },
          })),
        },
        {
          lazyUpdate: false,
          silent: true,
        }
      );
    }
  }

  function beginMapInteraction() {
    window.clearTimeout(roamResumeTimer);
    mapRoaming = true;
    setFlightEffectsPaused(true);
  }

  function scheduleMapAnimationResume(delay = 220) {
    window.clearTimeout(roamResumeTimer);
    if (mapPointerDown) {
      return;
    }
    roamResumeTimer = window.setTimeout(() => {
      mapRoaming = false;
      setFlightEffectsPaused(false);
    }, delay);
  }

  function handleGeoRoam() {
    beginMapInteraction();
    scheduleMapAnimationResume();
  }

  function populateDateFilters() {
    const years = Array.from(
      new Set(sources.journeys.map((journey) => journey.date.slice(0, 4)))
    ).sort((first, second) => second.localeCompare(first));
    journeyYearFilter.append(
      ...years.map((year) => {
        const option = document.createElement("option");
        option.value = year;
        option.textContent = `${year} 年`;
        return option;
      })
    );
    journeyMonthFilter.append(
      ...Array.from({ length: 12 }, (_value, index) => {
        const month = String(index + 1).padStart(2, "0");
        const option = document.createElement("option");
        option.value = month;
        option.textContent = `${index + 1} 月`;
        return option;
      })
    );
  }

  function updateDateFilters() {
    state.year = journeyYearFilter.value;
    state.month = journeyMonthFilter.value;
    state.hoveredJourneyId = null;
    rebuildJourneyLayers();
    renderLayers();
    renderJourneyHistory();
    updateSummary(visibleJourneys());
  }

  function toggleHistoryPanel(forceOpen) {
    const open =
      typeof forceOpen === "boolean"
        ? forceOpen
        : !journeyHistoryPanel.classList.contains("open");
    if (!open) {
      state.hoveredJourneyId = null;
      layers.hoveredJourney = null;
      renderLayers();
    } else {
      renderJourneyHistory();
    }
    journeyHistoryPanel.classList.toggle("open", open);
    journeyHistoryPanel.setAttribute("aria-hidden", String(!open));
    journeyHistoryPanel.inert = !open;
    historyJourneyButton.classList.toggle("active", open);
    historyJourneyButton.setAttribute("aria-expanded", String(open));
  }

  function bindControls() {
    modeButtons.forEach((button) => {
      button.addEventListener("click", () => updateMode(button.dataset.mode));
    });
    railwayToggle.addEventListener("change", () => {
      state.showRailwayNetwork = railwayToggle.checked;
      renderLayers();
    });

    journeyFilterToggle.addEventListener("click", () => {
      const expanded =
        journeyFilterToggle.getAttribute("aria-expanded") !== "true";
      journeyFilterToggle.setAttribute("aria-expanded", String(expanded));
      journeyFilterPanel.hidden = !expanded;
    });
    journeyYearFilter.addEventListener("change", updateDateFilters);
    journeyMonthFilter.addEventListener("change", updateDateFilters);

    historyJourneyButton.addEventListener("click", () => {
      toggleHistoryPanel();
    });
    clearJourneyHighlightButton.addEventListener(
      "click",
      clearJourneySelection
    );
    journeyHistoryPanel
      .querySelectorAll("[data-close-history]")
      .forEach((button) => {
        button.addEventListener("click", () => toggleHistoryPanel(false));
      });

    addJourneyButton.addEventListener("click", () => {
      journeyFormStatus.textContent = "";
      journeyFormStatus.classList.remove("success");
      refreshLocationOptions();
      journeyDialog.showModal();
    });
    journeyDialog.querySelectorAll("[data-close-dialog]").forEach((button) => {
      button.addEventListener("click", () => journeyDialog.close());
    });
    journeyDialog.addEventListener("click", (event) => {
      if (event.target === journeyDialog) {
        journeyDialog.close();
      }
    });
    journeyModeInput.addEventListener("change", () => refreshLocationOptions());
    [journeyStartInput, journeyEndInput].forEach((input) => {
      input.addEventListener("focus", () => refreshLocationOptions(input.value));
      input.addEventListener("input", () => refreshLocationOptions(input.value));
    });
    journeyForm.addEventListener("submit", submitJourneyForm);
    chart.on("georoam", handleGeoRoam);
    mapElement.addEventListener("pointerdown", () => {
      mapPointerDown = true;
      beginMapInteraction();
    });
    window.addEventListener("pointerup", () => {
      if (!mapPointerDown) {
        return;
      }
      mapPointerDown = false;
      scheduleMapAnimationResume(100);
    });
    window.addEventListener("pointercancel", () => {
      mapPointerDown = false;
      scheduleMapAnimationResume(100);
    });
  }

  function updateSummary(journeys) {
    const stations = endpointCounts(journeys, "train");
    const airports = endpointCounts(journeys, "flight");
    summaryElement.textContent =
      `${journeys.length} 段旅程 · ` +
      `${stations.size} 座到访车站 · ` +
      `${airports.size} 座机场`;
  }

  function showError(error) {
    console.error(error);
    loadingElement.hidden = true;
    errorBanner.hidden = false;
    const localHint =
      window.location.protocol === "file:"
        ? " 请通过本地服务器或 GitHub Pages 访问，不能直接双击 HTML。"
        : "";
    errorMessage.textContent = `${error.message || "未知错误"}${localHint}`;
  }

  Promise.all([
    loadJson("data/generated/places.json"),
    loadJson("data/source/locations.json"),
    loadJson("data/source/journeys.json"),
    loadJson("data/generated/railways.json"),
    loadJson("data/generated/journey-routes.json"),
    loadJson("data/generated/passenger-stations.json"),
    loadProvinceBoundary(),
  ])
    .then(
      ([
        placeDocument,
        locationDocument,
        journeyDocument,
        railwayDocument,
        routeDocument,
        passengerStationDocument,
      ]) => {
        if (
          locationDocument.schemaVersion !== 3 ||
          !Array.isArray(locationDocument.locations)
        ) {
          throw new Error("locations.json 的数据版本不受支持");
        }
        if (
          journeyDocument.schemaVersion !== 3 ||
          !Array.isArray(journeyDocument.journeys)
        ) {
          throw new Error("journeys.json 的数据版本不受支持");
        }
        if (
          routeDocument.schemaVersion !== 1 ||
          !Array.isArray(routeDocument.routes)
        ) {
          throw new Error("journey-routes.json 的数据版本不受支持");
        }

        const locations = placeIndex(placeDocument);
        const journeys = journeyDocument.journeys;
        const passengerStations = stationCatalog(passengerStationDocument);
        const catalogLookup = stationLookup(passengerStations);
        const generatedRoutes = new Map(
          routeDocument.routes.map((route) => [route.journeyId, route])
        );
        sources.locationDocument = locationDocument;
        sources.journeyDocument = journeyDocument;
        sources.passengerStations = passengerStations;
        sources.stationLookup = catalogLookup;
        sources.locations = locations;
        sources.journeys = journeys;
        sources.generatedRoutes = generatedRoutes;

        layers = {
          railwayNetwork: buildRailwayLayers(railwayDocument),
          trainJourneys: [],
          flightJourneys: [],
          movingTrains: null,
          stationMarkers: null,
          airportMarkers: null,
          selectedJourney: null,
          hoveredJourney: null,
        };
        populateDateFilters();
        rebuildJourneyLayers();

        chart.setOption(baseOption());
        renderLayers();
        bindControls();
        renderJourneyHistory();
        updateSummary(visibleJourneys());
        loadingElement.hidden = true;
        animationFrame = requestAnimationFrame(animateTrains);
      }
    )
    .catch(showError);

  let resizeFrame = 0;
  window.addEventListener("resize", () => {
    cancelAnimationFrame(resizeFrame);
    resizeFrame = requestAnimationFrame(() => chart.resize());
  });
  window.addEventListener("beforeunload", () => {
    cancelAnimationFrame(animationFrame);
    window.clearTimeout(roamResumeTimer);
  });
})();
