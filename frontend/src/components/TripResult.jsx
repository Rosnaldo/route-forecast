import { useMemo, useState } from "react";

import { gridForecasts } from "../lib/risk.js";
import { routeColor, routeName } from "../lib/routes.js";
import RouteMap from "./RouteMap.jsx";
import Tabs from "./Tabs.jsx";

// The routes from one request: the map with every route and the weather over all their
// counties for a departure `departureHour` h from now (set in the second form), any
// checkpoints from the second form, and the counties each route crosses (a tab each).
// Counties, cells and forecasts stream in after the routes (`routeGrids`, `weather` and
// `counties` are empty until then).
export default function TripResult({ apiKey, data, departureHour, checkpoints }) {
  const { routes, routeGrids, weather } = data;
  const [countyTab, setCountyTab] = useState("0"); // which route's counties are listed

  const forecasts = useMemo(
    () => (weather && routeGrids ? gridForecasts(weather, routeGrids, departureHour) : []),
    [weather, routeGrids, departureHour],
  );
  // Keyed on the counties, not `data`: forecasts streaming in must not redraw shapes.
  const countyByFips = useMemo(
    () => new Map(data.counties.map((county) => [county.fips, county])),
    [data.counties],
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
        <Tabs
          label="Counties per route"
          active={countyTab}
          onChange={setCountyTab}
          tabs={routes.map((_, index) => ({
            id: String(index),
            label: (
              <>
                <span className="legend-line" style={{ background: routeColor(index) }} />
                {routeName(index)}
                {routeGrids && ` (${routeGrids[index].counties.length})`}
              </>
            ),
            content: !routeGrids ? (
              <p className="place-selected">Finding the counties along the route…</p>
            ) : (
              <ol className="county-list" aria-label={`Counties on ${routeName(index)}`}>
                {routeGrids[index].counties.map((fips) => {
                  const county = countyByFips.get(fips);
                  return (
                    <li key={fips}>
                      {county.name}, {county.state}
                    </li>
                  );
                })}
              </ol>
            ),
          }))}
        />
      </div>
    </>
  );
}
