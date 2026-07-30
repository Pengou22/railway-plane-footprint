"use strict";

(() => {
  const mapElement = document.getElementById("china-map");
  const loadingElement = document.getElementById("loading-status");
  const errorBanner = document.getElementById("error-banner");
  const errorMessage = document.getElementById("error-message");
  const summaryElement = document.getElementById("journey-summary");
  const railwayToggle = document.getElementById("railway-layer-toggle");
  const viaStationToggle = document.getElementById("via-station-toggle");
  const mapControls = document.getElementById("map-controls");
  const mapControlsToggle = document.getElementById("map-controls-toggle");
  const mapControlsContent = document.getElementById("map-controls-content");
  const journeyYearFilter = document.getElementById("journey-year-filter");
  const journeyMonthFilter = document.getElementById("journey-month-filter");
  const journeyFilterReset = document.getElementById("journey-filter-reset");
  const journeyHistoryList = document.getElementById("journey-history-list");
  const clearJourneyHighlightButton = document.getElementById(
    "clear-journey-highlight"
  );
  const mapZoomInButton = document.getElementById("map-zoom-in");
  const mapZoomOutButton = document.getElementById("map-zoom-out");

  const prefersReducedMotion = window.matchMedia(
    "(prefers-reduced-motion: reduce)"
  ).matches;
  const state = {
    mode: "all",
    showRailwayNetwork: true,
    showViaStations: false,
    year: "all",
    month: "all",
    selectedJourneyIds: new Set(),
    hoveredJourneyId: null,
  };
  const DATA_URLS = {
    stations: "data/generated/stations.json",
    airports: "data/generated/airports.json",
    railwayJourneys: "data/source/journeys-railway.json",
    flightJourneys: "data/source/journeys-flight.json",
    railways: "data/generated/railways.geojson",
    routes: "data/generated/routes.json",
    provinces: "data/generated/admin-boundaries-province.json",
  };
  const SOURCE_IDS = {
    provinces: "province-boundaries",
    railways: "railway-network",
    trainJourneys: "train-journeys",
    flightJourneys: "flight-journeys",
    hoveredJourney: "hovered-journey",
    selectedJourney: "selected-journey",
    movingTrains: "moving-trains",
    movingPlanes: "moving-planes",
  };
  const LAYER_IDS = {
    provinceFill: "province-fill",
    conventionalRailways: "railway-conventional",
    highspeedRailways: "railway-highspeed",
    trainJourneys: "train-journey-lines",
    trainHit: "train-journey-hit-area",
    flightJourneys: "flight-journey-lines",
    flightHit: "flight-journey-hit-area",
    hoveredJourney: "hovered-journey-line",
    selectedJourney: "selected-journey-line",
    movingTrains: "moving-trains",
    movingPlanes: "moving-planes",
  };
  const HOME_BOUNDS = [
    [73.2, 17.5],
    [135.3, 53.8],
  ];
  const EMPTY_COLLECTION = Object.freeze({
    type: "FeatureCollection",
    features: [],
  });
  const VEHICLE_UPDATE_INTERVAL_MS = 100;
  const REFERENCE_DISTANCE_KM = 1300;
  const PLANE_REFERENCE_PERIOD_MS = 15000;
  const UNIT_SPEED_REFERENCE_PERIOD_MS = PLANE_REFERENCE_PERIOD_MS * 5;
  const MAX_DEPARTURE_DELAY_MS = 10000;
  const sources = {};
  const journeyGeometryById = new Map();
  const journeyFeatureById = new Map();
  const markerGroups = { train: [], flight: [] };

  let map = null;
  let hoverPopup = null;
  let animationFrame = 0;
  let animationTimer = 0;
  let vehicleAnimationTime = 0;
  let lastVehicleAnimationTick = 0;
  let movementAnimations = { train: [], flight: [] };
  let mapRoaming = false;
  let mapHoveredJourneyId = null;
  let hoveredProvinceCode = null;
  let previewOrigin = null;
  let markerLayoutFrame = 0;
  let hoverQueryFrame = 0;
  let pendingHoverPoint = null;

  function emptyCollection() {
    return { type: "FeatureCollection", features: [] };
  }

  function featureCollection(features) {
    return { type: "FeatureCollection", features };
  }

  function loadJson(url) {
    return fetch(url, { cache: "no-cache" }).then((response) => {
      if (!response.ok) {
        throw new Error(`${url} 请求失败（${response.status}）`);
      }
      return response.json();
    });
  }

  function stationCatalog(document) {
    if (document.schemaVersion !== 1 || !Array.isArray(document.stations)) {
      throw new Error("stations.json 的数据版本不受支持");
    }
    return document.stations;
  }

  function airportCatalog(document) {
    if (document.schemaVersion !== 1 || !Array.isArray(document.airports)) {
      throw new Error("airports.json 的数据版本不受支持");
    }
    return document.airports;
  }

  function journeyCatalog(document, expectedMode, filename) {
    if (document.schemaVersion !== 3 || !Array.isArray(document.journeys)) {
      throw new Error(`${filename} 的数据版本不受支持`);
    }
    if (document.journeys.some((journey) => journey.mode !== expectedMode)) {
      throw new Error(`${filename} 包含错误的行程类型`);
    }
    return document.journeys;
  }

  function catalogLookup(items, normalizeName) {
    const lookup = new Map();
    items.forEach((item) => {
      const names = [item.name, ...(item.aliases || [])];
      names.forEach((name) => {
        const key = normalizeName(name);
        if (!lookup.has(key)) {
          lookup.set(key, []);
        }
        lookup.get(key).push(item);
      });
    });
    return lookup;
  }

  function passengerStationMatches(name) {
    const normalizedName = normalizeStationName(name);
    const matches = sources.stationLookup?.get(normalizedName) || [];
    const uniqueMatches = Array.from(
      new Map(matches.map((station) => [station.osmId, station])).values()
    );
    const primaryNameMatches = uniqueMatches.filter(
      (station) => normalizeStationName(station.name) === normalizedName
    );
    return primaryNameMatches.length ? primaryNameMatches : uniqueMatches;
  }

  function airportMatches(name) {
    const normalizedName = normalizeAirportName(name);
    const matches = sources.airportLookup?.get(normalizedName) || [];
    const uniqueMatches = Array.from(
      new Map(matches.map((airport) => [airport.iata, airport])).values()
    );
    const primaryNameMatches = uniqueMatches.filter(
      (airport) => normalizeAirportName(airport.name) === normalizedName
    );
    return primaryNameMatches.length ? primaryNameMatches : uniqueMatches;
  }

  function resolvePassengerStation(name) {
    const matches = passengerStationMatches(name);
    if (!matches.length) {
      throw new Error(`全国客运站目录中找不到 ${name}`);
    }
    if (matches.length > 1) {
      throw new Error(
        `${name} 存在 ${matches.length} 个同名站，请在行程中使用更明确的正式站名`
      );
    }
    return matches[0];
  }

  function resolvePassengerAirport(name) {
    const matches = airportMatches(name);
    if (!matches.length) {
      throw new Error(`全国客运机场目录中找不到 ${name}`);
    }
    if (matches.length > 1) {
      throw new Error(
        `${name} 存在 ${matches.length} 个同名机场，请在行程中使用更明确的正式机场名`
      );
    }
    return matches[0];
  }

  function passengerStationPlace(station, name = station.name) {
    return {
      id: `osm-${station.osmId.toLowerCase().replace(/[^a-z0-9-]/g, "-")}`,
      type: "station",
      name,
      coordinates: station.coordinates,
      osmId: station.osmId,
      osmName: station.name,
      stationLevel: station.level,
    };
  }

  function passengerAirportPlace(airport, name = airport.name) {
    return {
      id: `iata-${airport.iata.toLowerCase()}`,
      type: "airport",
      name,
      coordinates: airport.coordinates,
      osmId: airport.osmId,
      osmName: airport.name,
      iata: airport.iata,
    };
  }

  function resolveJourneyPlaces(journeys) {
    const stationNames = Array.from(
      new Set(
        journeys
          .filter((journey) => journey.mode === "train")
          .flatMap((journey) => journey.stops)
      )
    );
    stationNames.forEach((name) => {
      const station = resolvePassengerStation(name);
      sources.locations.set(name, passengerStationPlace(station, name));
    });
    const airportNames = Array.from(
      new Set(
        journeys
          .filter((journey) => journey.mode === "flight")
          .flatMap((journey) => journey.stops)
      )
    );
    airportNames.forEach((name) => {
      const airport = resolvePassengerAirport(name);
      sources.locations.set(name, passengerAirportPlace(airport, name));
    });
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

  function journeyCoordinates(journey) {
    if (journey.mode === "train") {
      const generatedRoute = sources.generatedRoutes.get(journey.id);
      if (!generatedRoute) {
        throw new Error(`铁路行程 ${journey.id} 缺少生成路线`);
      }
      return generatedRoute.coords;
    }
    return journey.stops.map((stopName) => {
      const location = sources.locations.get(stopName);
      if (!location) {
        throw new Error(`行程 ${journey.id} 引用了未知地点 ${stopName}`);
      }
      return location.coordinates;
    });
  }

  function routeKey(start, end) {
    return `${start.join(",")}->${end.join(",")}`;
  }

  function flightSegmentCoordinates(start, end, repetition) {
    const middleLatitude = ((start[1] + end[1]) / 2) * (Math.PI / 180);
    const longitudeScale = Math.max(0.2, Math.cos(middleLatitude));
    const dxKm = (end[0] - start[0]) * 111.32 * longitudeScale;
    const dyKm = (end[1] - start[1]) * 110.57;
    const lengthKm = Math.hypot(dxKm, dyKm);
    if (lengthKm < 0.01) {
      return [start, end];
    }

    const normalX = -dyKm / lengthKm;
    const normalY = dxKm / lengthKm;
    const bulgeKm = lengthKm * (0.105 + repetition * 0.035);
    const samples = clamp(Math.ceil(lengthKm / 18), 24, 96);
    const result = [];
    for (let index = 0; index <= samples; index += 1) {
      const progress = index / samples;
      const latitude =
        start[1] + (end[1] - start[1]) * progress;
      const latitudeScale = Math.max(
        0.2,
        Math.cos(latitude * (Math.PI / 180))
      );
      const offset = Math.sin(Math.PI * progress) * bulgeKm;
      result.push([
        start[0] +
          (end[0] - start[0]) * progress +
          (normalX * offset) / (111.32 * latitudeScale),
        latitude + (normalY * offset) / 110.57,
      ]);
    }
    return result;
  }

  function flightJourneyCoordinates(journey, repeatedRoutes) {
    const stops = journeyCoordinates(journey);
    const combined = [];
    for (let index = 0; index < stops.length - 1; index += 1) {
      const start = stops[index];
      const end = stops[index + 1];
      const key = routeKey(start, end);
      const repetition = repeatedRoutes.get(key) || 0;
      repeatedRoutes.set(key, repetition + 1);
      const segment = flightSegmentCoordinates(start, end, repetition);
      if (combined.length) {
        combined.push(...segment.slice(1));
      } else {
        combined.push(...segment);
      }
    }
    return combined;
  }

  function buildJourneyCollections(journeys) {
    const trainFeatures = [];
    const flightFeatures = [];
    const repeatedRoutes = new Map();
    journeyGeometryById.clear();
    journeyFeatureById.clear();

    journeys.forEach((journey) => {
      const generatedRoute = sources.generatedRoutes.get(journey.id);
      const coordinates =
        journey.mode === "flight"
          ? flightJourneyCoordinates(journey, repeatedRoutes)
          : journeyCoordinates(journey);
      const info = journeyInfo(journey, sources.locations, generatedRoute);
      const feature = {
        type: "Feature",
        id: journey.id,
        properties: {
          journeyId: journey.id,
          mode: journey.mode,
          code: journey.code,
          date: journey.date,
          start: info.start,
          end: info.end,
        },
        geometry: {
          type: "LineString",
          coordinates,
        },
      };
      journeyGeometryById.set(journey.id, coordinates);
      journeyFeatureById.set(journey.id, feature);
      if (journey.mode === "train") {
        trainFeatures.push(feature);
      } else {
        flightFeatures.push(feature);
      }
    });

    return {
      train: featureCollection(trainFeatures),
      flight: featureCollection(flightFeatures),
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

  function randomDepartureDelayMs() {
    return Math.random() * MAX_DEPARTURE_DELAY_MS;
  }

  function makeMovementAnimation(journey) {
    const coords = journeyGeometryById.get(journey.id);
    const cumulative = cumulativeRoute(coords);
    const start = sources.locations.get(journey.stops[0]);
    const end = sources.locations.get(
      journey.stops[journey.stops.length - 1]
    );
    const directDistanceKm = coordinateDistanceKm(
      start.coordinates,
      end.coordinates
    );
    const speedUnit =
      journey.mode === "train" ? getTrainSpeedUnit(journey.code) : 5;
    const travelDurationMs =
      (directDistanceKm / REFERENCE_DISTANCE_KM) *
      (UNIT_SPEED_REFERENCE_PERIOD_MS / speedUnit);
    return {
      id: journey.id,
      code: journey.code,
      coords,
      offsets: cumulative.offsets,
      total: cumulative.total,
      icon: journey.mode === "train" ? getTrainIconId(journey.code) : "plane",
      directDistanceKm,
      speedUnit,
      travelDurationMs,
      departureAt: vehicleAnimationTime + randomDepartureDelayMs(),
      visible: false,
    };
  }

  function buildMovementAnimations(journeys) {
    const trainJourneys = journeys.filter(
      (journey) => journey.mode === "train"
    );
    const flightJourneys = journeys.filter(
      (journey) => journey.mode === "flight"
    );
    movementAnimations = {
      train: trainJourneys.map(makeMovementAnimation),
      flight: flightJourneys.map(makeMovementAnimation),
    };
  }

  function routePosition(animation, progress) {
    if (!animation.coords.length) {
      return { coordinates: [0, 0] };
    }
    if (animation.coords.length === 1 || animation.total <= 0) {
      return { coordinates: animation.coords[0] };
    }

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
    const coordinates = [
      start[0] + (end[0] - start[0]) * segmentProgress,
      start[1] + (end[1] - start[1]) * segmentProgress,
    ];
    return { coordinates };
  }

  function movementProgress(animation, timestamp) {
    if (prefersReducedMotion) {
      return 0.5;
    }
    if (timestamp < animation.departureAt) {
      return null;
    }

    const elapsed = timestamp - animation.departureAt;
    if (elapsed >= animation.travelDurationMs) {
      animation.departureAt = timestamp + randomDepartureDelayMs();
      return null;
    }
    return elapsed / animation.travelDurationMs;
  }

  function movingVehicleFeature(animation, progress) {
    const position = routePosition(animation, progress);
    return {
      type: "Feature",
      id: animation.id,
      properties: {
        journeyId: animation.id,
        code: animation.code,
        icon: animation.icon,
      },
      geometry: {
        type: "Point",
        coordinates: position.coordinates,
      },
    };
  }

  function movingVehicleCollection(animations, timestamp) {
    return featureCollection(
      animations
        .map((animation) => {
          const progress = movementProgress(animation, timestamp);
          animation.visible = progress !== null;
          return progress === null
            ? null
            : movingVehicleFeature(animation, progress);
        })
        .filter(Boolean)
    );
  }

  function setSourceData(sourceId, data) {
    const source = map && map.getSource(sourceId);
    if (source && typeof source.setData === "function") {
      source.setData(data);
    }
  }

  function updateMovingVehicles(timestamp) {
    if (!map) {
      return;
    }
    if (state.mode !== "flight") {
      updateMovingVehicleSource(
        SOURCE_IDS.movingTrains,
        movementAnimations.train,
        timestamp
      );
    }
    if (state.mode !== "train") {
      updateMovingVehicleSource(
        SOURCE_IDS.movingPlanes,
        movementAnimations.flight,
        timestamp
      );
    }
  }

  function updateMovingVehicleSource(sourceId, animations, timestamp) {
    const source = map && map.getSource(sourceId);
    if (!source || !animations.length) {
      return;
    }
    if (typeof source.loaded === "function" && !source.loaded()) {
      return;
    }
    if (typeof source.updateData !== "function") {
      source.setData(movingVehicleCollection(animations, timestamp));
      return;
    }

    const add = [];
    const update = [];
    const remove = [];
    animations.forEach((animation) => {
      const progress = movementProgress(animation, timestamp);
      if (progress === null) {
        if (animation.visible) {
          remove.push(animation.id);
          animation.visible = false;
        }
        return;
      }

      const feature = movingVehicleFeature(animation, progress);
      if (animation.visible) {
        update.push({
          id: animation.id,
          newGeometry: feature.geometry,
        });
      } else {
        add.push(feature);
        animation.visible = true;
      }
    });
    source.updateData({ add, update, remove });
  }

  function resetMovingVehicles(timestamp) {
    setSourceData(
      SOURCE_IDS.movingTrains,
      movingVehicleCollection(movementAnimations.train, timestamp)
    );
    setSourceData(
      SOURCE_IDS.movingPlanes,
      movingVehicleCollection(movementAnimations.flight, timestamp)
    );
  }

  function stopVehicleAnimation() {
    window.clearTimeout(animationTimer);
    cancelAnimationFrame(animationFrame);
    animationTimer = 0;
    animationFrame = 0;
    lastVehicleAnimationTick = 0;
  }

  function scheduleVehicleAnimation(delay = VEHICLE_UPDATE_INTERVAL_MS) {
    if (
      prefersReducedMotion ||
      !map ||
      mapRoaming ||
      document.hidden ||
      animationTimer ||
      animationFrame
    ) {
      return;
    }
    animationTimer = window.setTimeout(() => {
      animationTimer = 0;
      animationFrame = requestAnimationFrame((timestamp) => {
        animationFrame = 0;
        if (!mapRoaming && !document.hidden) {
          if (lastVehicleAnimationTick) {
            vehicleAnimationTime += Math.min(
              timestamp - lastVehicleAnimationTick,
              VEHICLE_UPDATE_INTERVAL_MS * 2
            );
          }
          lastVehicleAnimationTick = timestamp;
          updateMovingVehicles(vehicleAnimationTime);
        }
        scheduleVehicleAnimation();
      });
    }, delay);
  }

  function placeUsageCounts(journeys, mode) {
    const usage = new Map();
    journeys
      .filter((journey) => journey.mode === mode)
      .forEach((journey) => {
        journey.stops.forEach((locationName, index) => {
          if (!usage.has(locationName)) {
            usage.set(locationName, { endpointCount: 0, viaCount: 0 });
          }
          const counts = usage.get(locationName);
          if (index === 0 || index === journey.stops.length - 1) {
            counts.endpointCount += 1;
          } else {
            counts.viaCount += 1;
          }
        });
      });
    return usage;
  }

  function endpointCounts(journeys, mode) {
    return new Map(
      Array.from(placeUsageCounts(journeys, mode))
        .filter(([_name, usage]) => usage.endpointCount > 0)
        .map(([name, usage]) => [name, usage.endpointCount])
    );
  }

  function stationSymbolSize(level) {
    const sizes = { major: 23, station: 18, halt: 14 };
    return sizes[level] || sizes.station;
  }

  function stationLevelLabel(level) {
    return {
      major: "主要站",
      station: "普通站",
      halt: "乘降所",
    }[level] || "客运站";
  }

  function placeTooltipHtml(place, usage, mode) {
    const isAirport = mode === "flight";
    const endpointUsage = usage.endpointCount
      ? `<div><span>${
          isAirport ? "到达或出发" : "作为起点或终点"
        }</span>${usage.endpointCount} 次</div>`
      : "";
    const viaUsage =
      !isAirport && usage.viaCount
        ? `<div><span>作为途经站</span>${usage.viaCount} 次</div>`
        : "";
    return `
      <div class="journey-tooltip">
        <strong>${escapeHtml(place.name)}</strong>
        ${endpointUsage}
        ${viaUsage}
        ${
          !isAirport
            ? `<div><span>类别</span>${stationLevelLabel(place.stationLevel)}</div>`
            : ""
        }
      </div>
    `;
  }

  function removePlaceMarkers(mode) {
    markerGroups[mode].forEach((entry) => entry.marker.remove());
    markerGroups[mode] = [];
  }

  function createPlaceMarker(place, usage, mode) {
    const isAirport = mode === "flight";
    const viaOnly = !isAirport && usage.endpointCount === 0;
    const baseSize = isAirport ? 22 : stationSymbolSize(place.stationLevel);
    const size = viaOnly ? Math.max(12, baseSize - 4) : baseSize;
    const element = document.createElement("button");
    element.type = "button";
    element.className =
      `place-marker ${isAirport ? "airport" : "station"}` +
      `${viaOnly ? " via-station" : ""}`;
    element.style.setProperty("--marker-size", `${size}px`);
    const usageLabel = viaOnly
      ? `作为途经站 ${usage.viaCount} 次`
      : `${isAirport ? "到达或出发" : "作为起点或终点"} ${usage.endpointCount} 次`;
    element.setAttribute(
      "aria-label",
      `${place.name}，${usageLabel}`
    );

    const image = document.createElement("img");
    image.alt = "";
    image.src = isAirport
      ? "assets/images/airport.png"
      : "assets/images/station.png";
    const label = document.createElement("span");
    label.className = "place-marker-label";
    label.textContent = place.name;
    element.append(image, label);

    const marker = new maplibregl.Marker({
      element,
      anchor: "center",
    })
      .setLngLat(place.coordinates)
      .addTo(map);
    const showMarkerPopup = () => {
      showPopup(
        place.coordinates,
        placeTooltipHtml(place, usage, mode)
      );
    };
    element.addEventListener("mouseenter", showMarkerPopup);
    element.addEventListener("focus", showMarkerPopup);
    element.addEventListener("mouseleave", removePopup);
    element.addEventListener("blur", removePopup);

    return {
      marker,
      element,
      label,
      place,
      count: usage.endpointCount + usage.viaCount,
      usage,
      viaOnly,
      mode,
      size,
    };
  }

  function rebuildPlaceMarkers(journeys) {
    ["train", "flight"].forEach((mode) => {
      removePlaceMarkers(mode);
      const usage = placeUsageCounts(journeys, mode);
      markerGroups[mode] = Array.from(usage.entries())
        .filter(
          ([_locationName, counts]) =>
            mode === "train" || counts.endpointCount > 0
        )
        .map(([locationName, counts]) => {
          const place = sources.locations.get(locationName);
          if (!place) {
            throw new Error(`行程引用了未知地点 ${locationName}`);
          }
          return createPlaceMarker(place, counts, mode);
        });
    });
    applyMarkerVisibility();
    scheduleMarkerLabelLayout();
  }

  function visibleMarkerEntries() {
    const result = [];
    if (state.mode === "all" || state.mode === "train") {
      result.push(
        ...markerGroups.train.filter((entry) => !entry.element.hidden)
      );
    }
    if (state.mode === "all" || state.mode === "flight") {
      result.push(
        ...markerGroups.flight.filter((entry) => !entry.element.hidden)
      );
    }
    return result;
  }

  function updateMarkerLabelLayout() {
    markerLayoutFrame = 0;
    if (!map) {
      return;
    }
    const entries = visibleMarkerEntries().sort((first, second) => {
      const priorities = { major: 3, station: 2, halt: 1 };
      return (
        Number(first.viaOnly) - Number(second.viaOnly) ||
        (priorities[second.place.stationLevel] || 0) -
          (priorities[first.place.stationLevel] || 0) ||
        second.count - first.count
      );
    });
    if (map.getZoom() >= 8) {
      entries.forEach((entry) =>
        entry.label.classList.remove("label-collided")
      );
      return;
    }

    const occupied = [];
    entries.forEach((entry) => {
      const point = map.project(entry.place.coordinates);
      const halfWidth = Math.max(16, entry.place.name.length * 5.5 + 5);
      const top = point.y + entry.size / 2 + 2;
      const rectangle = {
        left: point.x - halfWidth,
        right: point.x + halfWidth,
        top,
        bottom: top + 15,
      };
      const collision = occupied.some(
        (other) =>
          rectangle.left < other.right &&
          rectangle.right > other.left &&
          rectangle.top < other.bottom &&
          rectangle.bottom > other.top
      );
      entry.label.classList.toggle("label-collided", collision);
      if (!collision) {
        occupied.push(rectangle);
      }
    });
  }

  function scheduleMarkerLabelLayout() {
    cancelAnimationFrame(markerLayoutFrame);
    markerLayoutFrame = requestAnimationFrame(updateMarkerLabelLayout);
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

  function provinceGeoJson(document) {
    return {
      ...document.geoJSON,
      features: document.geoJSON.features.map((feature) => {
        const name = feature.properties?.name;
        const colors = provinceColors[name] || {
          normal: "#dfe5e6",
          hover: "#aebbc1",
        };
        return {
          ...feature,
          properties: {
            ...feature.properties,
            color: colors.normal,
            hoverColor: colors.hover,
          },
        };
      }),
    };
  }

  function loadScaledImage(url, size = 64) {
    return new Promise((resolve, reject) => {
      const image = new Image();
      image.decoding = "async";
      image.onload = () => {
        const canvas = document.createElement("canvas");
        canvas.width = size;
        canvas.height = size;
        const context = canvas.getContext("2d", {
          alpha: true,
          willReadFrequently: false,
        });
        context.clearRect(0, 0, size, size);
        const scale = Math.min(size / image.naturalWidth, size / image.naturalHeight);
        const width = image.naturalWidth * scale;
        const height = image.naturalHeight * scale;
        context.drawImage(
          image,
          (size - width) / 2,
          (size - height) / 2,
          width,
          height
        );
        resolve(context.getImageData(0, 0, size, size));
      };
      image.onerror = () => reject(new Error(`${url} 加载失败`));
      image.src = url;
    });
  }

  async function loadMapImages() {
    const definitions = [
      ["train-g", "assets/images/train-g.png"],
      ["train-cd", "assets/images/train-cd.png"],
      ["train-ktyz", "assets/images/train-ktyz.png"],
      ["plane", "assets/images/plane.png"],
    ];
    const images = await Promise.all(
      definitions.map(async ([id, url]) => [id, await loadScaledImage(url)])
    );
    images.forEach(([id, image]) => {
      if (!map.hasImage(id)) {
        map.addImage(id, image, { pixelRatio: 2 });
      }
    });
  }

  function addGeoJsonSource(id, data, options = {}) {
    map.addSource(id, {
      type: "geojson",
      data,
      ...options,
    });
  }

  function addMapSources(provinceDocument) {
    addGeoJsonSource(
      SOURCE_IDS.provinces,
      provinceGeoJson(provinceDocument),
      {
        maxzoom: 10,
        tolerance: 0.35,
        promoteId: "adcode",
      }
    );
    addGeoJsonSource(SOURCE_IDS.railways, DATA_URLS.railways, {
      attribution:
        '<a href="https://www.openstreetmap.org/copyright" target="_blank">© OpenStreetMap contributors</a>',
      maxzoom: 14,
      tolerance: 0.45,
      buffer: 32,
    });
    addGeoJsonSource(SOURCE_IDS.trainJourneys, emptyCollection(), {
      maxzoom: 16,
      tolerance: 0.2,
      buffer: 32,
    });
    addGeoJsonSource(SOURCE_IDS.flightJourneys, emptyCollection(), {
      maxzoom: 16,
      tolerance: 0.2,
      buffer: 32,
    });
    addGeoJsonSource(SOURCE_IDS.hoveredJourney, emptyCollection(), {
      maxzoom: 18,
      tolerance: 0.1,
      buffer: 48,
    });
    addGeoJsonSource(SOURCE_IDS.selectedJourney, emptyCollection(), {
      maxzoom: 18,
      tolerance: 0.1,
      buffer: 48,
    });
    addGeoJsonSource(SOURCE_IDS.movingTrains, emptyCollection(), {
      maxzoom: 18,
    });
    addGeoJsonSource(SOURCE_IDS.movingPlanes, emptyCollection(), {
      maxzoom: 18,
    });
  }

  function addMapLayers() {
    map.addLayer({
      id: LAYER_IDS.provinceFill,
      type: "fill",
      source: SOURCE_IDS.provinces,
      paint: {
        "fill-antialias": true,
        "fill-color": [
          "case",
          ["boolean", ["feature-state", "hover"], false],
          ["coalesce", ["get", "hoverColor"], "#aebbc1"],
          ["coalesce", ["get", "color"], "#dfe5e6"],
        ],
        "fill-opacity": [
          "case",
          ["boolean", ["feature-state", "hover"], false],
          0.95,
          0.83,
        ],
        "fill-outline-color": "rgba(15, 23, 42, 0.96)",
      },
    });

    map.addLayer({
      id: LAYER_IDS.conventionalRailways,
      type: "line",
      source: SOURCE_IDS.railways,
      filter: ["==", ["get", "category"], "conventional"],
      layout: {
        "line-cap": "round",
        "line-join": "round",
      },
      paint: {
        "line-color": "#334155",
        "line-opacity": [
          "interpolate",
          ["linear"],
          ["zoom"],
          2,
          0.48,
          8,
          0.62,
          18,
          0.8,
        ],
        "line-width": [
          "interpolate",
          ["linear"],
          ["zoom"],
          2,
          0.72,
          8,
          1.18,
          18,
          2.5,
        ],
      },
    });
    map.addLayer({
      id: LAYER_IDS.highspeedRailways,
      type: "line",
      source: SOURCE_IDS.railways,
      filter: ["==", ["get", "category"], "highspeed"],
      layout: {
        "line-cap": "round",
        "line-join": "round",
      },
      paint: {
        "line-color": "#475569",
        "line-opacity": [
          "interpolate",
          ["linear"],
          ["zoom"],
          2,
          0.58,
          8,
          0.72,
          18,
          0.9,
        ],
        "line-width": [
          "interpolate",
          ["linear"],
          ["zoom"],
          2,
          0.9,
          8,
          1.45,
          18,
          3,
        ],
      },
    });

    addJourneyLineLayer(
      LAYER_IDS.trainJourneys,
      SOURCE_IDS.trainJourneys,
      "#0284c7"
    );
    addJourneyHitLayer(LAYER_IDS.trainHit, SOURCE_IDS.trainJourneys);
    addJourneyLineLayer(
      LAYER_IDS.flightJourneys,
      SOURCE_IDS.flightJourneys,
      "#f97316"
    );
    addJourneyHitLayer(LAYER_IDS.flightHit, SOURCE_IDS.flightJourneys);

    map.addLayer({
      id: LAYER_IDS.hoveredJourney,
      type: "line",
      source: SOURCE_IDS.hoveredJourney,
      layout: {
        "line-cap": "round",
        "line-join": "round",
      },
      paint: {
        "line-color": [
          "match",
          ["get", "mode"],
          "flight",
          "#c2410c",
          "#075985",
        ],
        "line-width": [
          "interpolate",
          ["linear"],
          ["zoom"],
          2,
          4.2,
          10,
          6.2,
          18,
          8,
        ],
        "line-opacity": 1,
        "line-blur": 0.35,
      },
    });
    map.addLayer({
      id: LAYER_IDS.selectedJourney,
      type: "line",
      source: SOURCE_IDS.selectedJourney,
      layout: {
        "line-cap": "round",
        "line-join": "round",
      },
      paint: {
        "line-color": [
          "match",
          ["get", "mode"],
          "flight",
          "#c2410c",
          "#075985",
        ],
        "line-width": [
          "interpolate",
          ["linear"],
          ["zoom"],
          2,
          5.4,
          10,
          7.5,
          18,
          9,
        ],
        "line-opacity": 1,
        "line-blur": 0.25,
      },
    });

    map.addLayer({
      id: LAYER_IDS.movingTrains,
      type: "symbol",
      source: SOURCE_IDS.movingTrains,
      layout: {
        "icon-image": ["get", "icon"],
        "icon-size": 1,
        "icon-allow-overlap": true,
        "icon-ignore-placement": true,
        "icon-rotation-alignment": "viewport",
      },
    });
    map.addLayer({
      id: LAYER_IDS.movingPlanes,
      type: "symbol",
      source: SOURCE_IDS.movingPlanes,
      layout: {
        "icon-image": "plane",
        "icon-size": 1,
        "icon-allow-overlap": true,
        "icon-ignore-placement": true,
        "icon-rotation-alignment": "viewport",
      },
    });
  }

  function addJourneyLineLayer(id, source, color) {
    map.addLayer({
      id,
      type: "line",
      source,
      layout: {
        "line-cap": "round",
        "line-join": "round",
      },
      paint: {
        "line-color": color,
        "line-opacity": 0.9,
        "line-width": [
          "interpolate",
          ["linear"],
          ["zoom"],
          2,
          1.9,
          10,
          3,
          18,
          4.5,
        ],
      },
    });
  }

  function addJourneyHitLayer(id, source) {
    map.addLayer({
      id,
      type: "line",
      source,
      paint: {
        "line-color": "rgba(0, 0, 0, 0.01)",
        "line-opacity": 0.01,
        "line-width": 14,
      },
    });
  }

  function homePadding() {
    if (window.innerWidth <= 680) {
      return { top: 110, right: 24, bottom: 90, left: 24 };
    }
    return { top: 56, right: 64, bottom: 78, left: 64 };
  }

  function createMap() {
    if (
      typeof maplibregl === "undefined" ||
      (typeof maplibregl.supported === "function" && !maplibregl.supported())
    ) {
      throw new Error("当前浏览器不支持 WebGL，无法启动地图");
    }

    map = new maplibregl.Map({
      container: mapElement,
      style: {
        version: 8,
        sources: {},
        layers: [
          {
            id: "background",
            type: "background",
            paint: {
              "background-color": "rgba(255, 255, 255, 0)",
            },
          },
        ],
        transition: {
          duration: 0,
          delay: 0,
        },
      },
      center: [104.2, 35.5],
      zoom: 3,
      minZoom: 2.25,
      maxZoom: 18,
      maxBounds: [
        [63, -5],
        [146, 63],
      ],
      renderWorldCopies: false,
      dragRotate: false,
      pitchWithRotate: false,
      touchPitch: false,
      maxPitch: 0,
      attributionControl: false,
      maplibreLogo: false,
      fadeDuration: 0,
      maxTileCacheZoomLevels: 3,
      localIdeographFontFamily:
        '"Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif',
      canvasContextAttributes: {
        powerPreference: "high-performance",
        antialias: false,
        preserveDrawingBuffer: false,
      },
    });
    map.getCanvas().setAttribute(
      "aria-label",
      "中国铁路与航空历史行程 WebGL 地图"
    );

    return new Promise((resolve, reject) => {
      let settled = false;
      map.once("load", () => {
        settled = true;
        resolve(map);
      });
      map.once("error", (event) => {
        if (!settled) {
          settled = true;
          reject(event.error || new Error("MapLibre 初始化失败"));
        }
      });
    });
  }

  function waitForMapIdle(timeoutMs = 20000) {
    return new Promise((resolve) => {
      let settled = false;
      const finish = () => {
        if (settled) {
          return;
        }
        settled = true;
        window.clearTimeout(timer);
        resolve();
      };
      const timer = window.setTimeout(finish, timeoutMs);
      map.once("idle", finish);
    });
  }

  function validateLoadedMapSources() {
    const provinceFeatures = map.querySourceFeatures(SOURCE_IDS.provinces);
    const railwayFeatures = map.querySourceFeatures(SOURCE_IDS.railways);
    const trainFeatures = map.querySourceFeatures(SOURCE_IDS.trainJourneys);
    mapElement.dataset.provinceFeatures = String(provinceFeatures.length);
    mapElement.dataset.railwayFeatures = String(railwayFeatures.length);
    mapElement.dataset.trainFeatures = String(trainFeatures.length);
    if (!provinceFeatures.length) {
      throw new Error("省域地图图层没有成功装入 WebGL");
    }
    if (!railwayFeatures.length) {
      throw new Error("全国铁路网图层没有成功装入 WebGL");
    }
    if (
      sources.journeys.some((journey) => journey.mode === "train") &&
      !trainFeatures.length
    ) {
      throw new Error("铁路足迹图层没有成功装入 WebGL");
    }
  }

  function setLayerVisibility(layerId, visible) {
    if (map && map.getLayer(layerId)) {
      map.setLayoutProperty(
        layerId,
        "visibility",
        visible ? "visible" : "none"
      );
    }
  }

  function applyMarkerVisibility() {
    const trainVisible = state.mode === "all" || state.mode === "train";
    const flightVisible = state.mode === "all" || state.mode === "flight";
    markerGroups.train.forEach((entry) => {
      entry.element.hidden =
        !trainVisible || (entry.viaOnly && !state.showViaStations);
    });
    markerGroups.flight.forEach((entry) => {
      entry.element.hidden = !flightVisible;
    });
    scheduleMarkerLabelLayout();
  }

  function applyLayerVisibility() {
    const trainVisible = state.mode === "all" || state.mode === "train";
    const flightVisible = state.mode === "all" || state.mode === "flight";
    [
      LAYER_IDS.conventionalRailways,
      LAYER_IDS.highspeedRailways,
    ].forEach((id) => setLayerVisibility(id, state.showRailwayNetwork));
    [
      LAYER_IDS.trainJourneys,
      LAYER_IDS.trainHit,
      LAYER_IDS.movingTrains,
    ].forEach((id) => setLayerVisibility(id, trainVisible));
    [
      LAYER_IDS.flightJourneys,
      LAYER_IDS.flightHit,
      LAYER_IDS.movingPlanes,
    ].forEach((id) => setLayerVisibility(id, flightVisible));
    applyMarkerVisibility();
    renderJourneyHighlights();
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

  function highlightCollection(journeyId) {
    const journey = findJourney(journeyId);
    const feature = journeyFeatureById.get(journeyId);
    if (!journey || !feature || !journeyIsVisible(journey)) {
      return emptyCollection();
    }
    return featureCollection([feature]);
  }

  function renderJourneyHighlights() {
    const hoverId =
      state.hoveredJourneyId &&
      !state.selectedJourneyIds.has(state.hoveredJourneyId)
        ? state.hoveredJourneyId
        : null;
    setSourceData(
      SOURCE_IDS.hoveredJourney,
      hoverId ? highlightCollection(hoverId) : emptyCollection()
    );
    setSourceData(
      SOURCE_IDS.selectedJourney,
      featureCollection(
        Array.from(state.selectedJourneyIds)
          .map((journeyId) => highlightCollection(journeyId).features[0])
          .filter(Boolean)
      )
    );
  }

  function rebuildJourneyData() {
    const journeys = filteredJourneys();
    const collections = buildJourneyCollections(journeys);
    setSourceData(SOURCE_IDS.trainJourneys, collections.train);
    setSourceData(SOURCE_IDS.flightJourneys, collections.flight);
    buildMovementAnimations(journeys);
    rebuildPlaceMarkers(journeys);
    resetMovingVehicles(vehicleAnimationTime);
    applyLayerVisibility();
  }

  function journeyTooltipHtml(journey) {
    const generatedRoute = sources.generatedRoutes.get(journey.id);
    const info = journeyInfo(journey, sources.locations, generatedRoute);
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

  function provinceTooltipHtml(properties) {
    return `
      <div class="journey-tooltip province-tooltip">
        <strong>${escapeHtml(properties.name || properties.fullName || "")}</strong>
        ${
          properties.fullName && properties.fullName !== properties.name
            ? `<div><span>行政区</span>${escapeHtml(properties.fullName)}</div>`
            : ""
        }
      </div>
    `;
  }

  function showPopup(coordinates, html) {
    if (!hoverPopup) {
      hoverPopup = new maplibregl.Popup({
        closeButton: false,
        closeOnClick: false,
        offset: 14,
        maxWidth: "360px",
      });
    }
    hoverPopup.setLngLat(coordinates).setHTML(html).addTo(map);
  }

  function removePopup() {
    if (hoverPopup) {
      hoverPopup.remove();
    }
  }

  function setProvinceHover(adcode) {
    const value = adcode || null;
    if (hoveredProvinceCode === value) {
      return;
    }
    if (hoveredProvinceCode) {
      map.setFeatureState(
        {
          source: SOURCE_IDS.provinces,
          id: hoveredProvinceCode,
        },
        { hover: false }
      );
    }
    if (value) {
      map.setFeatureState(
        {
          source: SOURCE_IDS.provinces,
          id: value,
        },
        { hover: true }
      );
    }
    hoveredProvinceCode = value;
  }

  function clearMapJourneyHover() {
    if (mapHoveredJourneyId) {
      clearJourneyPreview(mapHoveredJourneyId, "map");
      mapHoveredJourneyId = null;
    }
  }

  function runMapHoverQuery(point) {
    hoverQueryFrame = 0;
    if (mapRoaming || !point) {
      return;
    }

    const features = map.queryRenderedFeatures(point, {
      layers: [
        LAYER_IDS.flightHit,
        LAYER_IDS.trainHit,
        LAYER_IDS.provinceFill,
      ],
    });
    const journeyFeature = features.find(
      (feature) =>
        feature.layer.id === LAYER_IDS.flightHit ||
        feature.layer.id === LAYER_IDS.trainHit
    );
    const lngLat = map.unproject(point);
    if (journeyFeature) {
      const journeyId = journeyFeature.properties?.journeyId;
      const journey = findJourney(journeyId);
      if (journey) {
        setProvinceHover(null);
        map.getCanvas().style.cursor = "pointer";
        if (mapHoveredJourneyId !== journeyId) {
          clearMapJourneyHover();
          mapHoveredJourneyId = journeyId;
          previewJourney(journeyId, "map");
        }
        showPopup(lngLat, journeyTooltipHtml(journey));
        return;
      }
    }

    clearMapJourneyHover();
    const provinceFeature = features.find(
      (feature) => feature.layer.id === LAYER_IDS.provinceFill
    );
    if (provinceFeature) {
      const properties = provinceFeature.properties || {};
      setProvinceHover(properties.adcode);
      map.getCanvas().style.cursor = "pointer";
      showPopup(lngLat, provinceTooltipHtml(properties));
      return;
    }

    setProvinceHover(null);
    map.getCanvas().style.cursor = "";
    removePopup();
  }

  function cancelMapHoverQuery() {
    cancelAnimationFrame(hoverQueryFrame);
    hoverQueryFrame = 0;
    pendingHoverPoint = null;
  }

  function handleMapMouseMove(event) {
    if (mapRoaming) {
      return;
    }
    pendingHoverPoint = [event.point.x, event.point.y];
    if (hoverQueryFrame) {
      return;
    }
    hoverQueryFrame = requestAnimationFrame(() => {
      const point = pendingHoverPoint;
      pendingHoverPoint = null;
      runMapHoverQuery(point);
    });
  }

  function handleMapMouseLeave() {
    cancelMapHoverQuery();
    clearMapJourneyHover();
    setProvinceHover(null);
    map.getCanvas().style.cursor = "";
    removePopup();
  }

  function handleMapClick(event) {
    if (mapRoaming) {
      return;
    }
    const features = map.queryRenderedFeatures(event.point, {
      layers: [LAYER_IDS.flightHit, LAYER_IDS.trainHit],
    });
    const journeyId = features[0]?.properties?.journeyId;
    if (journeyId) {
      selectJourney(journeyId);
    }
  }

  function bindMapInteractions() {
    map.on("mousemove", handleMapMouseMove);
    map.on("click", handleMapClick);
    map.getCanvas().addEventListener("mouseleave", handleMapMouseLeave);
    map.on("movestart", () => {
      mapRoaming = true;
      document.body.classList.add("map-roaming");
      stopVehicleAnimation();
      handleMapMouseLeave();
    });
    map.on("moveend", () => {
      mapRoaming = false;
      document.body.classList.remove("map-roaming");
      updateMovingVehicles(vehicleAnimationTime);
      scheduleVehicleAnimation();
      scheduleMarkerLabelLayout();
    });
    map.on("zoomend", scheduleMarkerLabelLayout);
    map.on("error", (event) => {
      console.error("MapLibre:", event.error || event);
    });
  }

  function historyJourneyItem(journey) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `history-journey-item ${journey.mode}`;
    const selected = state.selectedJourneyIds.has(journey.id);
    button.classList.toggle("selected", selected);
    button.setAttribute(
      "aria-pressed",
      String(selected)
    );

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

    const via = document.createElement("span");
    via.className = "history-via";
    via.textContent =
      journey.stops.length > 2
        ? `途经：${journey.stops.slice(1, -1).join("、")}`
        : "途经：—";
    main.append(via);

    button.append(main);
    button.addEventListener("mouseenter", () =>
      previewJourney(journey.id, "history")
    );
    button.addEventListener("mouseleave", () =>
      clearJourneyPreview(journey.id, "history")
    );
    button.addEventListener("focus", () =>
      previewJourney(journey.id, "history")
    );
    button.addEventListener("blur", () =>
      clearJourneyPreview(journey.id, "history")
    );
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

    clearJourneyHighlightButton.disabled = !state.selectedJourneyIds.size;
  }

  function findJourney(journeyId) {
    return sources.journeys.find(
      (journey) => journey.id === journeyId
    );
  }

  function previewJourney(journeyId, origin = "history") {
    const journey = findJourney(journeyId);
    if (!journey || !journeyIsVisible(journey)) {
      return;
    }
    state.hoveredJourneyId = journey.id;
    previewOrigin = origin;
    renderJourneyHighlights();
  }

  function clearJourneyPreview(journeyId, origin = "history") {
    if (
      state.hoveredJourneyId !== journeyId ||
      previewOrigin !== origin
    ) {
      return;
    }
    state.hoveredJourneyId = null;
    previewOrigin = null;
    renderJourneyHighlights();
  }

  function selectJourney(journeyId) {
    const journey = findJourney(journeyId);
    if (!journey) {
      return;
    }
    if (state.selectedJourneyIds.has(journey.id)) {
      state.selectedJourneyIds.delete(journey.id);
    } else {
      state.selectedJourneyIds.add(journey.id);
    }
    state.hoveredJourneyId = null;
    previewOrigin = null;
    mapHoveredJourneyId = null;
    renderJourneyHistory();
    renderJourneyHighlights();
  }

  function clearJourneySelection() {
    state.selectedJourneyIds.clear();
    state.hoveredJourneyId = null;
    previewOrigin = null;
    mapHoveredJourneyId = null;
    renderJourneyHistory();
    renderJourneyHighlights();
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
    previewOrigin = null;
    rebuildJourneyData();
    renderJourneyHistory();
    updateSummary(visibleJourneys());
  }

  function resetJourneyFilters() {
    journeyYearFilter.value = "all";
    journeyMonthFilter.value = "all";
    state.mode = "all";
    updateDateFilters();
  }

  function setControlDrawerExpanded(expanded) {
    mapControls.classList.toggle("expanded", expanded);
    mapControlsToggle.setAttribute("aria-expanded", String(expanded));
    mapControlsToggle.setAttribute(
      "aria-label",
      expanded ? "收起地图控制栏" : "展开地图控制栏"
    );
    mapControlsContent.setAttribute("aria-hidden", String(!expanded));
    mapControlsContent.inert = !expanded;
    if (!expanded && previewOrigin === "history") {
      state.hoveredJourneyId = null;
      previewOrigin = null;
      renderJourneyHighlights();
    }
  }

  function bindControls() {
    railwayToggle.addEventListener("change", () => {
      state.showRailwayNetwork = railwayToggle.checked;
      applyLayerVisibility();
    });
    viaStationToggle.addEventListener("change", () => {
      state.showViaStations = viaStationToggle.checked;
      applyMarkerVisibility();
    });

    mapControlsToggle.addEventListener("click", () => {
      const expanded =
        mapControlsToggle.getAttribute("aria-expanded") !== "true";
      setControlDrawerExpanded(expanded);
    });
    journeyYearFilter.addEventListener("change", updateDateFilters);
    journeyMonthFilter.addEventListener("change", updateDateFilters);
    journeyFilterReset.addEventListener("click", resetJourneyFilters);
    mapZoomInButton.addEventListener("click", () => {
      map.zoomIn({ duration: prefersReducedMotion ? 0 : 180 });
    });
    mapZoomOutButton.addEventListener("click", () => {
      map.zoomOut({ duration: prefersReducedMotion ? 0 : 180 });
    });
    clearJourneyHighlightButton.addEventListener(
      "click",
      clearJourneySelection
    );
    document.addEventListener("keydown", (event) => {
      if (
        event.key === "Escape" &&
        mapControlsToggle.getAttribute("aria-expanded") === "true"
      ) {
        setControlDrawerExpanded(false);
        mapControlsToggle.focus();
      }
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
    errorMessage.textContent =
      `${error.message || "未知错误"}${localHint}`;
  }

  async function initialize() {
    const [
      stationDocument,
      airportDocument,
      railwayJourneyDocument,
      flightJourneyDocument,
      routeDocument,
      provinceDocument,
    ] = await Promise.all([
      loadJson(DATA_URLS.stations),
      loadJson(DATA_URLS.airports),
      loadJson(DATA_URLS.railwayJourneys),
      loadJson(DATA_URLS.flightJourneys),
      loadJson(DATA_URLS.routes),
      loadJson(DATA_URLS.provinces),
    ]);

    if (
      routeDocument.schemaVersion !== 1 ||
      !Array.isArray(routeDocument.routes)
    ) {
      throw new Error("routes.json 的数据版本不受支持");
    }
    validateProvinceBoundary(provinceDocument);

    sources.railwayJourneyDocument = railwayJourneyDocument;
    sources.flightJourneyDocument = flightJourneyDocument;
    sources.locations = new Map();
    sources.journeys = [
      ...journeyCatalog(
        railwayJourneyDocument,
        "train",
        "journeys-railway.json"
      ),
      ...journeyCatalog(
        flightJourneyDocument,
        "flight",
        "journeys-flight.json"
      ),
    ];
    sources.stations = stationCatalog(stationDocument);
    sources.airports = airportCatalog(airportDocument);
    sources.stationLookup = catalogLookup(
      sources.stations,
      normalizeStationName
    );
    sources.airportLookup = catalogLookup(
      sources.airports,
      normalizeAirportName
    );
    sources.generatedRoutes = new Map(
      routeDocument.routes.map((route) => [route.journeyId, route])
    );
    resolveJourneyPlaces(sources.journeys);

    await createMap();
    await loadMapImages();
    addMapSources(provinceDocument);
    addMapLayers();
    bindMapInteractions();
    bindControls();
    populateDateFilters();
    rebuildJourneyData();
    renderJourneyHistory();
    updateSummary(visibleJourneys());
    map.fitBounds(HOME_BOUNDS, {
      padding: homePadding(),
      duration: 0,
      maxZoom: 4.15,
    });
    await waitForMapIdle();
    validateLoadedMapSources();
    loadingElement.hidden = true;
    scheduleVehicleAnimation(0);
  }

  initialize().catch(showError);

  window.addEventListener("resize", scheduleMarkerLabelLayout);
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      stopVehicleAnimation();
    } else {
      scheduleVehicleAnimation(0);
    }
  });
  window.addEventListener("beforeunload", () => {
    stopVehicleAnimation();
    cancelAnimationFrame(markerLayoutFrame);
    cancelMapHoverQuery();
    if (map) {
      map.remove();
    }
  });
})();
