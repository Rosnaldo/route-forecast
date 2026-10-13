import { useMemo, useState } from "react";

import { gridForecasts } from "../lib/risk.js";
import { routeColor, routeName } from "../lib/routes.js";
import RouteMap from "./RouteMap.jsx";

const timeFormat = new Intl.DateTimeFormat(undefined, {
  weekday: "short",
  hour: "numeric",
  minute: "2-digit",
});

// The routes from one request: departure-time slider, the map with every route and the
// weather over all their counties, and the counties each route crosses.
export default function TripResult({ apiKey, data }) {
  const { routes, weather } = data;
  const [departureHour, setDepartureHour] = useState(0);

  const forecasts = useMemo(
    () => gridForecasts(weather, routes, departureHour),
    [weather, routes, departureHour],
  );
  const countyByFips = useMemo(
    () => new Map(data.counties.map((county) => [county.fips, county])),
    [data],
  );
  const departure = new Date((weather.now + departureHour * 3600) * 1000);

  return (
    <>
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

      <RouteMap
        apiKey={apiKey}
        routes={routes}
        countyByFips={countyByFips}
        weather={weather}
        forecasts={forecasts}
      />

      <div className="county-lists">
        {routes.map((route, index) => (
          <section key={index} className="county-group">
            <h3 className="county-group-title">
              <span className="legend-line" style={{ background: routeColor(index) }} />
              {routeName(index)} counties
            </h3>
            <ol className="county-list">
              {route.counties.map((fips) => {
                const county = countyByFips.get(fips);
                return (
                  <li key={fips}>
                    {county.name}, {county.state}
                  </li>
                );
              })}
            </ol>
          </section>
        ))}
      </div>
    </>
  );
}
