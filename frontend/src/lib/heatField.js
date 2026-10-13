// The smooth heat map: forecast values interpolated between grid centers, then
// classified pixel by pixel, so risk boundaries curve between centers instead of
// following the cells' square edges. Values are interpolated, never levels: a blend of
// "High" and "Low" means nothing, a blend of 40 and 20 mph wind does.

import { LOADING_COLOR, NO_FORECAST_COLOR, RISK_LEVELS } from "./risk.js";

// Risk level (0-4) for an hour's values and the cargo weight, as forecast_level() in
// apps/trips/business/risk.py does: same thresholds (keep the two in step). Plain
// comparisons: it runs for every pixel.
export function classify(wind, rain, snow, weightLb) {
  let level = wind >= 55 ? 4 : wind >= 45 ? 3 : wind >= 35 ? 2 : wind >= 25 ? 1 : 0;
  if (weightLb > 30_000 && wind >= 45 && wind < 55) level = 4;
  else if (weightLb > 40_000 && wind >= 35 && wind < 45) level = Math.max(level, 3);
  const rainLevel = rain > 1.0 ? 4 : rain >= 0.5 ? 3 : rain >= 0.25 ? 2 : rain >= 0.1 ? 1 : 0;
  const snowLevel = snow > 3.0 ? 4 : snow >= 2.0 ? 3 : snow >= 1.0 ? 2 : snow >= 0.5 ? 1 : 0;
  return Math.max(level, rainLevel, snowLevel);
}

// Per grid point (weather.points order): the forecast its cells show, from the per-cell
// `forecasts` (gridForecasts). Pieces of one center in several counties can differ
// (routes reach them at different times); the center takes the worst of them.
//   { state: "loading" } | { state: "none" } | { state: "ok", wind, rain, snow }
export function centerValues(weather, forecasts) {
  const values = weather.points.map(() => null);
  const levels = weather.points.map(() => -2);
  weather.cells.forEach(({ point }, index) => {
    const forecast = forecasts[index];
    if (!forecast) return;
    if (forecast.loading) {
      values[point] ??= { state: "loading" };
      return;
    }
    const level = forecast.level ?? -1;
    if (values[point]?.state === "loading" || level > levels[point]) {
      levels[point] = level;
      values[point] =
        forecast.level == null
          ? { state: "none" }
          : { state: "ok", wind: forecast.wind, rain: forecast.rain, snow: forecast.snow };
    }
  });
  return values;
}

// The box the grid's cells cover, in degrees.
export function gridBounds(weather) {
  const half = weather.step / 2;
  const lats = weather.points.map((point) => point.lat);
  const lons = weather.points.map((point) => point.lon);
  return {
    south: Math.min(...lats) - half,
    north: Math.max(...lats) + half,
    west: Math.min(...lons) - half,
    east: Math.max(...lons) + half,
  };
}

// Web Mercator y of a latitude, and back: the map is linear in y, not in latitude, so
// rows are spaced in y for the image to line up with the map at any latitude.
export const mercatorY = (lat) => Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360));
const latitudeOf = (y) => (Math.atan(Math.exp(y)) * 360) / Math.PI - 90;

const rgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
const LEVEL_RGB = RISK_LEVELS.map(({ color }) => rgb(color));
const NO_FORECAST_RGB = rgb(NO_FORECAST_COLOR);
const LOADING_RGB = rgb(LOADING_COLOR);
// Same opacities as the square cells: loading cells stay light until colored.
const ALPHA = Math.round(0.7 * 255);
const LOADING_ALPHA = Math.round(0.35 * 255);

// RGBA pixels (width x height, north-west first) of the field over `bounds`. Each pixel
// takes the state of the cell it falls in: loading and no-forecast cells are flat, and
// forecast cells blend the values of the (up to 4) surrounding centers that have one,
// bilinearly. Pixels outside every cell stay transparent.
export function renderField(weather, values, bounds, width, height) {
  const { step, weight_lb: weightLb } = weather;

  // The points as a dense (row i, column j) table, one slot per grid square of the box
  // plus a border, so neighbor lookups are array reads. STATE: 0 no cell, 1 loading,
  // 2 no forecast, 3 forecast (then WIND / RAIN / SNOW hold its values).
  const i0 = Math.floor(bounds.south / step + 0.5) - 1;
  const j0 = Math.floor(bounds.west / step + 0.5) - 1;
  const rows = Math.round((bounds.north - bounds.south) / step) + 3;
  const columns = Math.round((bounds.east - bounds.west) / step) + 3;
  const STATE = new Uint8Array(rows * columns);
  const WIND = new Float64Array(rows * columns);
  const RAIN = new Float64Array(rows * columns);
  const SNOW = new Float64Array(rows * columns);
  weather.points.forEach(({ lat, lon }, index) => {
    const value = values[index];
    if (!value) return;
    const slot =
      (Math.round(lat / step - 0.5) - i0) * columns + (Math.round(lon / step - 0.5) - j0);
    STATE[slot] = { loading: 1, none: 2, ok: 3 }[value.state];
    if (value.state === "ok") {
      WIND[slot] = value.wind;
      RAIN[slot] = value.rain;
      SNOW[slot] = value.snow;
    }
  });

  // Per column: the cell it falls in, the centers west of it, and how far past them (0-1).
  const cellColumn = new Int32Array(width);
  const westColumn = new Int32Array(width);
  const tx = new Float64Array(width);
  for (let c = 0; c < width; c += 1) {
    const lon = bounds.west + ((c + 0.5) / width) * (bounds.east - bounds.west);
    const f = lon / step - 0.5;
    cellColumn[c] = Math.floor(lon / step) - j0;
    westColumn[c] = Math.floor(f) - j0;
    tx[c] = f - Math.floor(f);
  }

  const yNorth = mercatorY(bounds.north);
  const ySouth = mercatorY(bounds.south);
  const pixels = new Uint8ClampedArray(width * height * 4);
  const corners = new Int32Array(4);
  const shares = new Float64Array(4);

  for (let r = 0; r < height; r += 1) {
    const lat = latitudeOf(yNorth - ((r + 0.5) / height) * (yNorth - ySouth));
    const f = lat / step - 0.5;
    const ty = f - Math.floor(f);
    const cellRow = (Math.floor(lat / step) - i0) * columns;
    const southRow = (Math.floor(f) - i0) * columns;
    for (let c = 0; c < width; c += 1) {
      const state = STATE[cellRow + cellColumn[c]];
      if (state === 0) continue;
      let color = NO_FORECAST_RGB;
      let alpha = ALPHA;
      if (state === 1) {
        color = LOADING_RGB;
        alpha = LOADING_ALPHA;
      } else if (state === 3) {
        // Blend the surrounding centers that have a forecast. The pixel's own center is
        // one of them, weighted at least 1/4, so weight > 0.
        const t = tx[c];
        corners[0] = southRow + westColumn[c];
        corners[1] = corners[0] + 1;
        corners[2] = corners[0] + columns;
        corners[3] = corners[2] + 1;
        shares[0] = (1 - ty) * (1 - t);
        shares[1] = (1 - ty) * t;
        shares[2] = ty * (1 - t);
        shares[3] = ty * t;
        let weight = 0;
        let wind = 0;
        let rain = 0;
        let snow = 0;
        for (let k = 0; k < 4; k += 1) {
          const slot = corners[k];
          if (STATE[slot] !== 3) continue;
          const share = shares[k];
          weight += share;
          wind += share * WIND[slot];
          rain += share * RAIN[slot];
          snow += share * SNOW[slot];
        }
        color = LEVEL_RGB[classify(wind / weight, rain / weight, snow / weight, weightLb)];
      }
      const at = (r * width + c) * 4;
      pixels[at] = color[0];
      pixels[at + 1] = color[1];
      pixels[at + 2] = color[2];
      pixels[at + 3] = alpha;
    }
  }
  return pixels;
}
