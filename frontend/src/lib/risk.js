// Risk levels (0-4, as in apps/trips/risk.py) and how a route reads them from the
// shared weather grid.

// Heat ramp for risk level (pale yellow -> dark red), indexed by level.
export const RISK_LEVELS = [
  { label: "Low", color: "#fff1a8" },
  { label: "Moderate", color: "#fdc24e" },
  { label: "High", color: "#f5832a" },
  { label: "Severe", color: "#d6381f" },
  { label: "No Travel", color: "#7d0f14" },
];
export const NO_FORECAST_COLOR = "#c9ced6";
export const LOADING_COLOR = "#e4e7ec"; // a cell whose forecast has not streamed in yet

export const levelColor = (level) =>
  level == null ? NO_FORECAST_COLOR : RISK_LEVELS[level].color;

// Forecast at a grid point for the hour the truck gets there (`loading` until the
// point's forecast has streamed in): it passes nearest the
// point `offsetS` after departure, and departs `departureHour` h from now. Levels
// already account for the cargo weight sent with the request.
export function forecastAt(weather, point, offsetS, departureHour) {
  const eta = weather.now + departureHour * 3600 + offsetS;
  if (!point.levels) return { eta, level: null, loading: true }; // not streamed in yet
  const hour = Math.floor((eta - weather.start) / 3600);
  const inWindow = eta < weather.now + weather.hours * 3600 && point.levels[hour] != null;
  if (!inWindow) return { eta, level: null };
  return {
    eta,
    level: point.levels[hour],
    wind: point.wind_mph[hour],
    rain: point.rain_in_hr[hour],
    snow: point.snow_in_hr[hour],
  };
}

// Forecast for every cell of the grid (same order as weather.cells), covering all
// routes. A cell several routes cross is reached at a different time on each; it shows
// the worst of those forecasts (no forecast counts as better than any level).
export function gridForecasts(weather, routes, departureHour) {
  const worst = weather.cells.map(() => null);
  for (const route of routes) {
    for (const { cell, offset_s } of route.cells) {
      const point = weather.points[weather.cells[cell].point];
      const forecast = forecastAt(weather, point, offset_s, departureHour);
      if (!worst[cell] || (forecast.level ?? -1) > (worst[cell].level ?? -1)) {
        worst[cell] = forecast;
      }
    }
  }
  return worst;
}
