import { useEffect, useState } from "react";

import PlaceInput from "./components/PlaceInput.jsx";
import RouteMap from "./components/RouteMap.jsx";

const apiKey = __GOOGLE_MAPS_API_KEY__;

function Selection({ place }) {
  if (!place) return <p className="place-selected" />;
  return (
    <p className="place-selected" aria-live="polite">
      {place.address} ({place.lat.toFixed(4)}, {place.lon.toFixed(4)})
    </p>
  );
}

function RouteSummary({ apiKey, route, error }) {
  if (error) return <p className="notice">{error}</p>;
  if (!route) return null;
  const km = (route.distance_m / 1000).toFixed(0);
  const hours = Math.floor(route.duration_s / 3600);
  const minutes = Math.round((route.duration_s % 3600) / 60);
  return (
    <section aria-live="polite">
      <p className="route-summary">
        {km} km · {hours} h {minutes} min · {route.counties.length} counties
      </p>
      <RouteMap apiKey={apiKey} route={route} />
      <ol className="county-list">
        {route.counties.map((county) => (
          <li key={county.fips}>
            {county.name}, {county.state}
          </li>
        ))}
      </ol>
    </section>
  );
}

export default function App() {
  const [origin, setOrigin] = useState(null);
  const [destination, setDestination] = useState(null);
  const [route, setRoute] = useState(null);
  const [routeError, setRouteError] = useState(null);

  useEffect(() => {
    setRoute(null);
    setRouteError(null);
    if (!origin || !destination) return;

    const controller = new AbortController();
    fetch("/api/v1/trips/route/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        departure: { lat: origin.lat, lon: origin.lon },
        arrival: { lat: destination.lat, lon: destination.lon },
      }),
      signal: controller.signal,
    })
      .then(async (response) => {
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail ?? "Route request failed");
        setRoute(data);
      })
      .catch((err) => err.name !== "AbortError" && setRouteError(err.message));

    return () => controller.abort();
  }, [origin, destination]);

  return (
    <main className="container">
      <h1>Trip weather</h1>

      {apiKey ? (
        <>
          <form className="trip-form" onSubmit={(event) => event.preventDefault()}>
            <div className="place-field">
              <PlaceInput apiKey={apiKey} label="Departure" onSelect={setOrigin} />
              <Selection place={origin} />
            </div>
            <div className="place-field">
              <PlaceInput apiKey={apiKey} label="Arrival" onSelect={setDestination} />
              <Selection place={destination} />
            </div>
          </form>
          <RouteSummary apiKey={apiKey} route={route} error={routeError} />
        </>
      ) : (
        <p className="notice">
          Set <code>GOOGLE_MAPS_API_KEY</code> in <code>.env</code> to enable address search.
        </p>
      )}
    </main>
  );
}
