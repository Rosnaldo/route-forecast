import { useEffect, useRef, useState } from "react";

import ExampleRoutes from "./components/ExampleRoutes.jsx";
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

function RouteSummary({ trip, route, loading, error }) {
  if (!trip) return null;
  return (
    <div aria-live="polite">
      <h2 className="route-title">
        {trip.from} → {trip.to}
      </h2>
      {loading && <p className="route-summary">Calculating route…</p>}
      {error && <p className="notice">{error}</p>}
      {route && !loading && (
        <p className="route-summary">
          {(route.distance_m / 1000).toFixed(0)} km
          {trip.expectedKm && ` (expected ~${trip.expectedKm.toLocaleString()} km)`} ·{" "}
          {Math.floor(route.duration_s / 3600)} h {Math.round((route.duration_s % 3600) / 60)} min
          · {route.counties.length} counties
        </p>
      )}
    </div>
  );
}

const asPoint = ({ lat, lon }) => ({ lat, lon });

export default function App() {
  const [origin, setOrigin] = useState(null);
  const [destination, setDestination] = useState(null);
  // What to route: { departure, arrival } request points, labels, and the example row if any.
  const [trip, setTrip] = useState(null);
  const [route, setRoute] = useState(null);
  const [loading, setLoading] = useState(false);
  const [routeError, setRouteError] = useState(null);
  const result = useRef(null);

  useEffect(() => {
    if (!origin || !destination) return;
    setTrip({
      departure: asPoint(origin),
      arrival: asPoint(destination),
      from: origin.address,
      to: destination.address,
    });
  }, [origin, destination]);

  const selectExample = (example) => {
    setTrip({
      departure: { address: example.departure },
      arrival: { address: example.arrival },
      from: example.departure,
      to: example.arrival,
      exampleId: example.id,
      expectedKm: example.distance_km,
    });
    result.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  useEffect(() => {
    setRoute(null);
    setRouteError(null);
    if (!trip) return;

    const controller = new AbortController();
    setLoading(true);
    fetch("/api/v1/trips/route/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ departure: trip.departure, arrival: trip.arrival }),
      signal: controller.signal,
    })
      .then(async (response) => {
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail ?? JSON.stringify(data));
        setRoute(data);
        setLoading(false);
      })
      .catch((err) => {
        if (err.name === "AbortError") return;
        setRoute(null);
        setRouteError(err.message);
        setLoading(false);
      });

    return () => controller.abort();
  }, [trip]);

  if (!apiKey) {
    return (
      <main className="container">
        <h1>Trip weather</h1>
        <p className="notice">
          Set <code>GOOGLE_MAPS_API_KEY</code> in <code>.env</code> to enable address search.
        </p>
      </main>
    );
  }

  return (
    <main className="container">
      <h1>Trip weather</h1>

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

      <section ref={result} className="route-result">
        <RouteSummary trip={trip} route={route} loading={loading} error={routeError} />
        {route ? (
          <>
            <RouteMap apiKey={apiKey} route={route} />
            <ol className="county-list">
              {route.counties.map((county) => (
                <li key={county.fips}>
                  {county.name}, {county.state}
                </li>
              ))}
            </ol>
          </>
        ) : (
          !trip && <p className="place-selected">Pick two places, or click an example below.</p>
        )}
      </section>

      <ExampleRoutes selectedId={trip?.exampleId} onSelect={selectExample} />
    </main>
  );
}
