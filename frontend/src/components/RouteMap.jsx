import { useEffect, useRef, useState } from "react";

import { loadGoogleMaps } from "../lib/googleMaps.js";

// Sequential blue ramp (light -> dark) for travel order: first county lightest.
const ORDER_RAMP = [
  "#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6",
  "#256abf", "#1c5cab", "#184f95", "#104281",
];
const ROUTE_COLOR = "#eb6834";
const CASING_COLOR = "#ffffff";

function orderColor(index, count) {
  const t = count > 1 ? index / (count - 1) : 0;
  return ORDER_RAMP[Math.round(t * (ORDER_RAMP.length - 1))];
}

const endpoint = (maps, fillColor) => ({
  icon: {
    path: maps.SymbolPath.CIRCLE,
    scale: 6,
    fillColor,
    fillOpacity: 1,
    strokeColor: CASING_COLOR,
    strokeWeight: 2,
  },
});

// Google map of the trip: counties shaded by travel order, route drawn on top.
export default function RouteMap({ apiKey, route }) {
  const container = useRef(null);
  const [hovered, setHovered] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const overlays = [];
    const listeners = [];

    loadGoogleMaps(apiKey)
      .then((maps) => maps.importLibrary("maps"))
      .then(({ Map, Polyline }) => {
        if (cancelled) return;
        const { maps } = window.google;
        const map = new Map(container.current, {
          mapTypeControl: false,
          streetViewControl: false,
          clickableIcons: false,
        });

        const count = route.counties.length;
        map.data.addGeoJson({
          type: "FeatureCollection",
          features: route.counties
            .map(({ geometry, ...county }, order) => ({
              type: "Feature",
              geometry,
              properties: { ...county, order },
            }))
            .filter((feature) => feature.geometry),
        });
        map.data.setStyle((feature) => ({
          fillColor: orderColor(feature.getProperty("order"), count),
          fillOpacity: 0.45,
          strokeColor: CASING_COLOR,
          strokeWeight: 1,
          zIndex: 1,
        }));
        listeners.push(
          map.data.addListener("mouseover", ({ feature }) => {
            map.data.overrideStyle(feature, { fillOpacity: 0.7, strokeWeight: 3 });
            setHovered({
              name: feature.getProperty("name"),
              state: feature.getProperty("state"),
              order: feature.getProperty("order") + 1,
            });
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
              { ...endpoint(maps, ROUTE_COLOR), offset: "0%" },
              { ...endpoint(maps, ORDER_RAMP.at(-1)), offset: "100%" },
            ],
          }),
        );

        const bounds = new maps.LatLngBounds();
        path.forEach((point) => bounds.extend(point));
        map.fitBounds(bounds, 24);
      })
      .catch((err) => !cancelled && setError(err.message));

    return () => {
      cancelled = true;
      listeners.forEach((listener) => listener.remove());
      overlays.forEach((overlay) => overlay.setMap(null));
    };
  }, [apiKey, route]);

  if (error) return <p className="notice">{error}</p>;
  const count = route.counties.length;
  return (
    <figure className="route-map">
      <div
        className="route-map-canvas"
        ref={container}
        role="img"
        aria-label={`Map of the route through ${count} counties`}
      />
      <figcaption className="route-map-legend">
        <span className="legend-item">
          <span className="legend-line" /> Route
        </span>
        <span className="legend-item">
          Departure
          <span
            className="legend-ramp"
            style={{ background: `linear-gradient(to right, ${ORDER_RAMP.join(", ")})` }}
          />
          Arrival
        </span>
        <span className="legend-hover" aria-live="polite">
          {hovered
            ? `${hovered.order} of ${count} · ${hovered.name}, ${hovered.state}`
            : "Hover a county"}
        </span>
      </figcaption>
    </figure>
  );
}
