import { useMemo } from "react";

import { gridForecasts } from "../lib/risk.js";
import { routeColor, routeName } from "../lib/routes.js";
import RouteMap from "./RouteMap.jsx";

// The routes from one request: the map with every route and the weather over all their
// counties for a departure `departureHour` h from now (set in the second form), any
// checkpoints from the second form, and the counties each route crosses.
export default function TripResult({ apiKey, data, departureHour, checkpoints }) {
  const { routes, weather } = data;

  const forecasts = useMemo(
    () => gridForecasts(weather, routes, departureHour),
    [weather, routes, departureHour],
  );
  const countyByFips = useMemo(
    () => new Map(data.counties.map((county) => [county.fips, county])),
    [data],
  );

  return (
    <>
      <RouteMap
        apiKey={apiKey}
        routes={routes}
        countyByFips={countyByFips}
        weather={weather}
        forecasts={forecasts}
        checkpoints={checkpoints}
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
