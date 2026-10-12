import { useEffect, useRef, useState } from "react";

import ExampleRoutes from "./components/ExampleRoutes.jsx";
import PlaceInput from "./components/PlaceInput.jsx";
import RouteMap from "./components/RouteMap.jsx";
import Tabs from "./components/Tabs.jsx";
import { WEIGHT_DEFAULT, WEIGHT_MAX, WEIGHT_MIN, WEIGHT_STEP, pounds } from "./lib/load.js";

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
          · {route.counties.length} counties · {pounds(route.weather.weight_lb)} load
        </p>
      )}
    </div>
  );
}

const asPoint = ({ lat, lon }) => ({ lat, lon });

// Cargo weight; heavier loads raise the wind risk (see apps/trips/risk.py).
function WeightInput({ weightLb, onChange }) {
  return (
    <div className="weight-field">
      <label className="place-label" htmlFor="load-weight">
        Load weight
      </label>
      <input
        id="load-weight"
        type="range"
        min={WEIGHT_MIN}
        max={WEIGHT_MAX}
        step={WEIGHT_STEP}
        value={weightLb}
        onChange={(event) => onChange(Number(event.target.value))}
        aria-valuetext={pounds(weightLb)}
      />
      <p className="place-selected" aria-live="polite">
        <strong>{pounds(weightLb)}</strong>
      </p>
    </div>
  );
}

// The two points to route, from whichever tab is active; null until it is complete.
function tripFrom(tab, { origin, destination, example }) {
  if (tab === "customize") {
    if (!origin || !destination) return null;
    return {
      departure: asPoint(origin),
      arrival: asPoint(destination),
      from: origin.address,
      to: destination.address,
    };
  }
  if (!example) return null;
  return {
    departure: { address: example.departure },
    arrival: { address: example.arrival },
    from: example.departure,
    to: example.arrival,
    expectedKm: example.distance_km,
  };
}

const MISSING = {
  customize: "Pick a departure and an arrival.",
  examples: "Pick an example route.",
};

export default function App() {
  const [tab, setTab] = useState("customize");
  const [origin, setOrigin] = useState(null);
  const [destination, setDestination] = useState(null);
  const [example, setExample] = useState(null);
  const [weightLb, setWeightLb] = useState(WEIGHT_DEFAULT);
  // The submitted request: { departure, arrival, weightLb } plus labels for the summary.
  const [trip, setTrip] = useState(null);
  const [route, setRoute] = useState(null);
  const [loading, setLoading] = useState(false);
  const [routeError, setRouteError] = useState(null);
  const result = useRef(null);

  const draft = tripFrom(tab, { origin, destination, example });

  const submit = (event) => {
    event.preventDefault();
    if (!draft) return;
    setTrip({ ...draft, weightLb }); // a new object, so submitting again refetches
    // Side by side the result is already in view; stacked, scroll down to it.
    result.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
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
      body: JSON.stringify({
        departure: trip.departure,
        arrival: trip.arrival,
        weight_lb: trip.weightLb,
      }),
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

      <div className="workspace">
        <form className="trip-form" onSubmit={submit}>
          <Tabs
            label="Choose the trip"
            active={tab}
            onChange={setTab}
            tabs={[
              {
                id: "customize",
                label: "Customize",
                content: (
                  <div className="place-fields">
                    <div className="place-field">
                      <PlaceInput apiKey={apiKey} label="Departure" onSelect={setOrigin} />
                      <Selection place={origin} />
                    </div>
                    <div className="place-field">
                      <PlaceInput apiKey={apiKey} label="Arrival" onSelect={setDestination} />
                      <Selection place={destination} />
                    </div>
                  </div>
                ),
              },
              {
                id: "examples",
                label: "Examples",
                content: <ExampleRoutes selectedId={example?.id} onSelect={setExample} />,
              },
            ]}
          />

          <WeightInput weightLb={weightLb} onChange={setWeightLb} />

          <div className="form-actions">
            <button type="submit" className="submit" disabled={!draft || loading}>
              {loading ? "Calculating…" : "Submit"}
            </button>
            {!draft && <span className="place-selected">{MISSING[tab]}</span>}
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
            !trip && (
              <p className="place-selected">
                Pick two places in Customize, or a route in Examples, then Submit.
              </p>
            )
          )}
        </section>
      </div>
    </main>
  );
}
