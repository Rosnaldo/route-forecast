import { useEffect, useMemo, useRef, useState } from "react";

import { loadGoogleMaps } from "../lib/googleMaps.js";

// Heat ramp for risk level (pale yellow -> dark red), indexed by level 0-4.
const RISK_LEVELS = [
  { label: "Low", color: "#fff1a8" },
  { label: "Moderate", color: "#fdc24e" },
  { label: "High", color: "#f5832a" },
  { label: "Severe", color: "#d6381f" },
  { label: "No Travel", color: "#7d0f14" },
];
const NO_FORECAST_COLOR = "#c9ced6";
const ROUTE_COLOR = "#1d2433";
const CASING_COLOR = "#ffffff";
const COUNTY_COLOR = "#5b6472";

const levelColor = (level) => (level == null ? NO_FORECAST_COLOR : RISK_LEVELS[level].color);

const timeFormat = new Intl.DateTimeFormat(undefined, {
  weekday: "short",
  hour: "numeric",
  minute: "2-digit",
});

// Forecast at a grid point for the hour the truck gets there, leaving `departureHour` h
// from now. Levels already account for the cargo weight sent with the request.
function forecastAt(weather, point, departureHour) {
  const { levels } = point;
  const eta = weather.now + departureHour * 3600 + point.offset_s;
  const hour = Math.floor((eta - weather.start) / 3600);
  const inWindow = eta < weather.now + weather.hours * 3600 && levels[hour] != null;
  if (!inWindow) return { eta, level: null };
  return {
    eta,
    level: levels[hour],
    wind: point.wind_mph[hour],
    rain: point.rain_in_hr[hour],
    snow: point.snow_in_hr[hour],
  };
}

function describe(forecast, county) {
  const where = county ? `${county.name}, ${county.state}` : "";
  const when = `ETA ${timeFormat.format(new Date(forecast.eta * 1000))}`;
  if (forecast.level == null) return `No forecast · ${where} · ${when}`;
  return (
    `${RISK_LEVELS[forecast.level].label} · ${where} · ${when} · ` +
    `wind ${Math.round(forecast.wind)} mph, rain ${forecast.rain.toFixed(2)} in/hr, ` +
    `snow ${forecast.snow.toFixed(2)} in/hr`
  );
}

// Departure: hollow dot; arrival: filled dot.
const endpoint = (maps, fillColor, strokeColor) => ({
  icon: {
    path: maps.SymbolPath.CIRCLE,
    scale: 6,
    fillColor,
    fillOpacity: 1,
    strokeColor,
    strokeWeight: 2,
  },
});

// Google map of the trip: weather-risk heat map on a grid over the counties crossed,
// county outlines and the route drawn on top.
export default function RouteMap({ apiKey, route }) {
  const { weather } = route;
  const container = useRef(null);
  const dataLayer = useRef(null);
  const [departureHour, setDepartureHour] = useState(0);
  const [hovered, setHovered] = useState(null); // index into weather.cells
  const [error, setError] = useState(null);
  const [mapCount, setMapCount] = useState(0); // bumps when a map is created, to style it

  const countyByFips = useMemo(
    () => new Map(route.counties.map((county) => [county.fips, county])),
    [route],
  );

  // Risk level per grid point for the chosen departure time.
  const forecasts = useMemo(
    () => weather.points.map((point) => forecastAt(weather, point, departureHour)),
    [weather, departureHour],
  );

  useEffect(() => {
    let cancelled = false;
    const overlays = [];
    const listeners = [];

    loadGoogleMaps(apiKey)
      .then((maps) => maps.importLibrary("maps"))
      .then(({ Map: GoogleMap, Polyline }) => {
        if (cancelled) return;
        const { maps } = window.google;
        const map = new GoogleMap(container.current, {
          mapTypeControl: false,
          streetViewControl: false,
          clickableIcons: false,
        });

        dataLayer.current = map.data;
        map.data.addGeoJson({
          type: "FeatureCollection",
          features: [
            ...weather.cells.map(({ geometry, point }, index) => ({
              type: "Feature",
              geometry,
              properties: { kind: "cell", index, point },
            })),
            ...route.counties
              .filter((county) => county.geometry)
              .map(({ geometry, fips }) => ({
                type: "Feature",
                geometry,
                properties: { kind: "county", fips },
              })),
          ],
        });
        listeners.push(
          map.data.addListener("mouseover", ({ feature }) => {
            map.data.overrideStyle(feature, {
              fillOpacity: 0.9,
              strokeColor: ROUTE_COLOR,
              strokeWeight: 2,
            });
            setHovered(feature.getProperty("index"));
          }),
          map.data.addListener("mouseout", ({ feature }) => {
            map.data.revertStyle(feature);
            setHovered(null);
          }),
        );

        const path = route.points.map(([lat, lng]) => ({ lat, lng }));
        overlays.push(
          // White casing under the route keeps it readable over any fill.
          new Polyline({
            map,
            path,
            strokeColor: CASING_COLOR,
            strokeWeight: 7,
            clickable: false,
            zIndex: 10, // above the county fills
          }),
          new Polyline({
            map,
            path,
            strokeColor: ROUTE_COLOR,
            strokeWeight: 4,
            clickable: false,
            zIndex: 11,
            icons: [
              { ...endpoint(maps, CASING_COLOR, ROUTE_COLOR), offset: "0%" },
              { ...endpoint(maps, ROUTE_COLOR, CASING_COLOR), offset: "100%" },
            ],
          }),
        );

        const bounds = new maps.LatLngBounds();
        path.forEach((point) => bounds.extend(point));
        map.fitBounds(bounds, 24);
        setMapCount((count) => count + 1);
      })
      .catch((err) => !cancelled && setError(err.message));

    return () => {
      cancelled = true;
      dataLayer.current = null;
      listeners.forEach((listener) => listener.remove());
      overlays.forEach((overlay) => overlay.setMap(null));
    };
  }, [apiKey, route, weather]);

  // Recolor the cells when the departure time changes, and on each new map.
  useEffect(() => {
    dataLayer.current?.setStyle((feature) =>
      feature.getProperty("kind") === "cell"
        ? {
            fillColor: levelColor(forecasts[feature.getProperty("point")].level),
            fillOpacity: 0.7,
            strokeWeight: 0,
            zIndex: 1,
          }
        : {
            // Outline only, and not clickable, so hover reaches the cells below.
            fillOpacity: 0,
            strokeColor: COUNTY_COLOR,
            strokeOpacity: 0.6,
            strokeWeight: 1,
            clickable: false,
            zIndex: 2,
          },
    );
  }, [forecasts, mapCount]);

  if (error) return <p className="notice">{error}</p>;
  const hasNoForecast = forecasts.some((forecast) => forecast.level == null);
  const departure = new Date((weather.now + departureHour * 3600) * 1000);
  const hoveredCell = hovered == null ? null : weather.cells[hovered];
  return (
    <figure className="route-map">
      <div className="map-controls">
        <label className="map-slider">
          <span>
            Departure: <strong>{departureHour === 0 ? "now" : `in ${departureHour} h`}</strong> ·{" "}
            {timeFormat.format(departure)}
          </span>
          <input
            type="range"
            min={0}
            max={weather.hours}
            step={1}
            value={departureHour}
            onChange={(event) => setDepartureHour(Number(event.target.value))}
          />
          <span className="map-slider-scale" aria-hidden="true">
            <span>now</span>
            <span>+12 h</span>
            <span>+24 h</span>
            <span>+36 h</span>
            <span>+48 h</span>
          </span>
        </label>
      </div>
      <div
        className="route-map-canvas"
        ref={container}
        role="img"
        aria-label={`Weather risk map of the route through ${route.counties.length} counties`}
      />
      <figcaption className="route-map-legend">
        <span className="legend-item">
          <span className="legend-line" /> Route
        </span>
        <span className="legend-item">
          {RISK_LEVELS.map(({ label, color }) => (
            <span key={label} className="legend-item">
              <span className="legend-swatch" style={{ background: color }} />
              {label}
            </span>
          ))}
          {hasNoForecast && (
            <span className="legend-item">
              <span className="legend-swatch" style={{ background: NO_FORECAST_COLOR }} />
              No forecast
            </span>
          )}
        </span>
        <span className="legend-hover" aria-live="polite">
          {hoveredCell
            ? describe(forecasts[hoveredCell.point], countyByFips.get(hoveredCell.fips))
            : "Hover the map for the forecast when you get there"}
        </span>
      </figcaption>
    </figure>
  );
}
