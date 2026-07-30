"use strict";

function getTrainCategory(code) {
  const prefix = typeof code === "string" ? code.charAt(0).toUpperCase() : "";
  if (prefix === "G") {
    return "highspeed";
  }
  if (prefix === "D" || prefix === "C") {
    return "emu";
  }
  return "conventional";
}

function getTrainIconId(code) {
  return {
    highspeed: "train-g",
    emu: "train-cd",
    conventional: "train-ktyz",
  }[getTrainCategory(code)];
}

function getTrainSpeedUnit(code) {
  return {
    highspeed: 3,
    emu: 2,
    conventional: 1,
  }[getTrainCategory(code)];
}

function normalizeStationName(value) {
  return String(value ?? "")
    .normalize("NFKC")
    .toLocaleLowerCase("zh-CN")
    .replace(/[\s·•（）()\-—_/]/g, "")
    .replace(/(?:火车站|铁路车站|高铁站|railwaystation|station|站)$/i, "");
}

function normalizeAirportName(value) {
  return String(value ?? "")
    .normalize("NFKC")
    .toLocaleLowerCase("zh-CN")
    .replace(/[\s·•（）()\-—_/]/g, "")
    .replace(/(?:国际机场|机场|航空港|internationalairport|airport)$/i, "");
}

function coordinateDistanceKm(first, second) {
  const latitude = ((first[1] + second[1]) / 2) * (Math.PI / 180);
  const dx = (second[0] - first[0]) * 111.32 * Math.cos(latitude);
  const dy = (second[1] - first[1]) * 110.57;
  return Math.hypot(dx, dy);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, value));
}

const provinceColors = {
  北京: { normal: "#BECBD3", hover: "#8E9BAE" },
  天津: { normal: "#DCDDDF", hover: "#B6BBBE" },
  河北: { normal: "#DDD0C8", hover: "#A39183" },
  山西: { normal: "#EAE0D7", hover: "#CFC3BC" },
  内蒙古: { normal: "#C6CCC0", hover: "#8A9585" },
  辽宁: { normal: "#CCD2CC", hover: "#737C75" },
  吉林: { normal: "#D6E1D7", hover: "#A1B0AD" },
  黑龙江: { normal: "#BFD1C4", hover: "#82ABA3" },
  上海: { normal: "#E3E7EA", hover: "#9DA8AF" },
  江苏: { normal: "#DBD2C9", hover: "#A39087" },
  浙江: { normal: "#E3D0CC", hover: "#AB8C83" },
  安徽: { normal: "#F4EBE4", hover: "#D2CABF" },
  福建: { normal: "#F2DBD5", hover: "#CBA29E" },
  江西: { normal: "#EBC2C0", hover: "#B87F78" },
  山东: { normal: "#D7CDD5", hover: "#A392A2" },
  河南: { normal: "#E0DFE4", hover: "#8D8FA4" },
  湖北: { normal: "#CFC3BC", hover: "#A08887" },
  湖南: { normal: "#E6DEDC", hover: "#C0B0A2" },
  广东: { normal: "#D6DCDB", hover: "#82898D" },
  广西: { normal: "#C1CCC7", hover: "#93A3A0" },
  海南: { normal: "#E6F1ED", hover: "#A8B2AA" },
  重庆: { normal: "#D4C3AA", hover: "#A39183" },
  四川: { normal: "#EDDFC4", hover: "#B5AF5A" },
  贵州: { normal: "#D1D3C5", hover: "#737C75" },
  云南: { normal: "#DEE1CB", hover: "#93A3A0" },
  西藏: { normal: "#EEF1EA", hover: "#ADB5AB" },
  陕西: { normal: "#C5BDB2", hover: "#908982" },
  甘肃: { normal: "#D2CABF", hover: "#A09952" },
  青海: { normal: "#EEDAC0", hover: "#BFBC9D" },
  宁夏: { normal: "#D6D9B9", hover: "#C0C182" },
  新疆: { normal: "#F3F4D5", hover: "#CDDAA5" },
  香港: { normal: "#E8D8D7", hover: "#B87F78" },
  澳门: { normal: "#F9ECE4", hover: "#CBA29E" },
  台湾: { normal: "#E0DFE4", hover: "#8D8FA4" },
};
