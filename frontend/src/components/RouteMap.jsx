import { useEffect, useRef, useState } from "react";

import { loadGoogleMaps } from "../lib/googleMaps.js";
import { NO_FORECAST_COLOR, RISK_LEVELS, levelColor } from "../lib/risk.js";
import { routeColor, routeLetter, routeName } from "../lib/routes.js";

const HIGHLIGHT_COLOR = "#1d2433"; // hovered cell outline, departure/arrival dots
const CASING_COLOR = "#ffffff";
const COUNTY_COLOR = "#5b6472";

const timeFormat = new Intl.DateTimeFormat(undefined, {
  weekday: "short",
  hour: "numeric",
  minute: "2-digit",
});

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

const duration = (seconds) =>
  `${Math.floor(seconds / 3600)} h ${String(Math.round((seconds % 3600) / 60)).padStart(2, "0")} min`;

const clockFormat = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" });
const localDay = (date) => Math.floor((date.getTime() - date.getTimezoneOffset() * 60_000) / 86_400_000);

// A checkpoint's estimated arrival time, shown beside it: "14:30", or "14:30 +1d" when
// it is on a later (local) day than the departure.
function arrivalLabel(eta, departure) {
  const days = localDay(eta) - localDay(departure);
  return days > 0 ? `${clockFormat.format(eta)} +${days}d` : clockFormat.format(eta);
}

// The hovered checkpoint's details, as a DOM node for the map's info box.
function checkpointDetails(checkpoint, routeIndex) {
  const miles = Math.round(checkpoint.distance_m / 1609.344);
  const lines = [
    `${routeName(routeIndex)} · ${checkpoint.is_arrival ? "Arrival" : "Checkpoint"} · ${miles} mi`,
    `Travel time ${duration(checkpoint.elapsed_s)}` +
      (checkpoint.breaks
        ? ` (incl. ${checkpoint.breaks} × 30 min break${checkpoint.breaks > 1 ? "s" : ""})`
        : "") +
      ` · ETA ${timeFormat.format(new Date(checkpoint.eta * 1000))}`,
    checkpoint.level == null
      ? "No forecast for that time"
      : `${RISK_LEVELS[checkpoint.level].label} · wind ${Math.round(checkpoint.wind_mph)} mph, ` +
        `rain ${checkpoint.rain_in_hr.toFixed(2)} in/hr, snow ${checkpoint.snow_in_hr.toFixed(2)} in/hr`,
  ];
  const box = document.createElement("div");
  box.className = "checkpoint-info";
  lines.forEach((text, index) => {
    const line = document.createElement(index === 0 ? "strong" : "div");
    line.textContent = text;
    box.append(line);
  });
  return box;
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

// Where to put a route's letter: the point (between 15% and 85% of the way) farthest
// from the other routes, so labels of routes sharing a road do not stack.
function labelPoint(routes, index) {
  const sample = (points, n) =>
    Array.from({ length: n }, (_, i) => points[Math.floor((i / (n - 1)) * (points.length - 1))]);
  const own = sample(routes[index].points, 41).slice(6, -6);
  const others = routes.filter((_, i) => i !== index).flatMap((r) => sample(r.points, 80));
  const distance = ([lat, lon]) =>
    Math.min(Infinity, ...others.map(([a, b]) => (lat - a) ** 2 + (lon - b) ** 2));
  const [lat, lng] = own.reduce((best, point) => (distance(point) > distance(best) ? point : best));
  return { lat, lng };
}

// Google map of the trip: every route drawn the same way in its own color with its
// letter, and the weather-risk heat map on a grid over the counties all routes cross.
// `forecasts` holds each grid cell's forecast, in weather.cells order.
export default function RouteMap({
  apiKey,
  routes,
  countyByFips,
  weather,
  forecasts,
  checkpoints,
}) {
  const container = useRef(null);
  const map = useRef(null); // { maps, map, lines: [{ casing, line, label }] } once created
  const [hovered, setHovered] = useState(null); // index into weather.cells
  const [error, setError] = useState(null);
  const [mapCount, setMapCount] = useState(0); // bumps when a map is created, to fill it

  // Create the map and a line per route.
  useEffect(() => {
    let cancelled = false;
    const listeners = [];
    let lines = [];

    loadGoogleMaps(apiKey)
      .then((maps) => Promise.all([maps.importLibrary("maps"), maps.importLibrary("marker")]))
      .then(([{ Map: GoogleMap, Polyline, InfoWindow }, { Marker }]) => {
        if (cancelled) return;
        const { maps } = window.google;
        const instance = new GoogleMap(container.current, {
          mapTypeControl: false,
          streetViewControl: false,
          clickableIcons: false,
        });

        const bounds = new maps.LatLngBounds();
        lines = routes.map((route, index) => {
          const path = route.points.map(([lat, lng]) => ({ lat, lng }));
          path.forEach((point) => bounds.extend(point));
          // White casing under each route keeps it readable over any fill.
          const casing = new Polyline({
            map: instance,
            path,
            strokeColor: CASING_COLOR,
            strokeWeight: 7,
            clickable: false,
            zIndex: 10,
          });
          const line = new Polyline({
            map: instance,
            path,
            strokeColor: routeColor(index),
            strokeWeight: 4,
            clickable: false,
            zIndex: 11,
            // All routes share departure and arrival: draw those dots once.
            icons:
              index === 0
                ? [
                    { ...endpoint(maps, CASING_COLOR, HIGHLIGHT_COLOR), offset: "0%" },
                    { ...endpoint(maps, HIGHLIGHT_COLOR, CASING_COLOR), offset: "100%" },
                  ]
                : [],
          });
          const label = new Marker({
            map: instance,
            position: labelPoint(routes, index),
            title: routeName(index),
            clickable: false,
            zIndex: 900,
            label: { text: routeLetter(index), color: "#fff", fontWeight: "700", fontSize: "12px" },
            icon: {
              path: maps.SymbolPath.CIRCLE,
              scale: 11,
              fillColor: routeColor(index),
              fillOpacity: 1,
              strokeColor: CASING_COLOR,
              strokeWeight: 2,
            },
          });
          return { casing, line, label };
        });
        instance.fitBounds(bounds, 24);

        listeners.push(
          instance.data.addListener("mouseover", ({ feature }) => {
            instance.data.overrideStyle(feature, {
              fillOpacity: 0.9,
              strokeColor: HIGHLIGHT_COLOR,
              strokeWeight: 2,
            });
            setHovered(feature.getProperty("index"));
          }),
          instance.data.addListener("mouseout", ({ feature }) => {
            instance.data.revertStyle(feature);
            setHovered(null);
          }),
        );
        // Shared box for a hovered checkpoint's details.
        const info = new InfoWindow({ disableAutoPan: true, headerDisabled: true });
        map.current = { maps, map: instance, lines, Marker, info };
        setMapCount((count) => count + 1);
      })
      .catch((err) => !cancelled && setError(err.message));

    return () => {
      cancelled = true;
      map.current = null;
      listeners.forEach((listener) => listener.remove());
      lines.forEach((overlays) => Object.values(overlays).forEach((o) => o.setMap(null)));
    };
  }, [apiKey, routes]);

  // Checkpoints: a dot per checkpoint (fill: risk level, ring: route color) with its
  // estimated arrival time beside it; travel time and forecast show while hovered.
  useEffect(() => {
    if (!map.current || !checkpoints) return;
    const { maps, map: instance, Marker, info } = map.current;
    const departure = new Date(checkpoints.departure);
    const markers = checkpoints.routes.flatMap((route, routeIndex) =>
      route.map((checkpoint) => {
        const marker = new Marker({
          map: instance,
          position: { lat: checkpoint.lat, lng: checkpoint.lon },
          zIndex: 950,
          label: {
            text: arrivalLabel(new Date(checkpoint.eta * 1000), departure),
            className: "checkpoint-eta",
            color: "#1c1917",
            fontSize: "11px",
            fontWeight: "700",
          },
          icon: {
            path: maps.SymbolPath.CIRCLE,
            scale: 6,
            fillColor: levelColor(checkpoint.level),
            fillOpacity: 1,
            strokeColor: routeColor(routeIndex),
            strokeWeight: 3,
            labelOrigin: new maps.Point(0, 2.9), // the time sits just below the dot
          },
        });
        marker.addListener("mouseover", () => {
          info.setContent(checkpointDetails(checkpoint, routeIndex));
          info.open({ map: instance, anchor: marker, shouldFocus: false });
        });
        marker.addListener("mouseout", () => info.close());
        return marker;
      }),
    );
    return () => {
      info.close();
      markers.forEach((marker) => {
        maps.event.clearInstanceListeners(marker);
        marker.setMap(null);
      });
    };
  }, [checkpoints, mapCount]);

  // The heat map: every cell of the grid (all routes) and every county they cross.
  useEffect(() => {
    if (!map.current) return;
    const { map: instance } = map.current;
    instance.data.forEach((feature) => instance.data.remove(feature));
    instance.data.addGeoJson({
      type: "FeatureCollection",
      features: [
        ...weather.cells.map(({ geometry }, index) => ({
          type: "Feature",
          geometry,
          properties: { kind: "cell", index },
        })),
        ...[...countyByFips.values()]
          .filter((county) => county.geometry)
          .map(({ geometry, fips }) => ({
            type: "Feature",
            geometry,
            properties: { kind: "county", fips },
          })),
      ],
    });
    setHovered(null);
  }, [weather, countyByFips, mapCount]);

  // Color the cells for the departure time; also once they are added.
  useEffect(() => {
    map.current?.map.data.setStyle((feature) =>
      feature.getProperty("kind") === "cell"
        ? {
            fillColor: levelColor(forecasts[feature.getProperty("index")]?.level),
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
  const hoveredFips = hovered == null ? null : weather.cells[hovered]?.fips;
  return (
    <figure className="route-map">
      <div
        className="route-map-canvas"
        ref={container}
        role="img"
        aria-label={`Weather risk map of ${routes.length} routes crossing ${countyByFips.size} counties`}
      />
      <figcaption className="route-map-legend">
        {routes.map((_, index) => (
          <span key={index} className="legend-item">
            <span className="legend-line" style={{ background: routeColor(index) }} />
            {routeName(index)}
          </span>
        ))}
        <span className="legend-item">
          {RISK_LEVELS.map(({ label, color }) => (
            <span key={label} className="legend-item">
              <span className="legend-swatch" style={{ background: color }} />
              {label}
            </span>
          ))}
          {checkpoints && (
            <span className="legend-item">
              <span className="legend-checkpoint" /> Checkpoint with arrival time (hover for
              details)
            </span>
          )}
          {hasNoForecast && (
            <span className="legend-item">
              <span className="legend-swatch" style={{ background: NO_FORECAST_COLOR }} />
              No forecast
            </span>
          )}
        </span>
        <span className="legend-hover" aria-live="polite">
          {hoveredFips
            ? describe(forecasts[hovered], countyByFips.get(hoveredFips))
            : "Hover the map for the forecast when you get there"}
        </span>
      </figcaption>
    </figure>
  );
}
