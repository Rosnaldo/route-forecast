import { useEffect, useRef, useState } from "react";

import DistanceDepartureForm from "./components/DistanceDepartureForm.jsx";
import ExampleRoutes from "./components/ExampleRoutes.jsx";
import PlaceInput from "./components/PlaceInput.jsx";
import Stepper from "./components/Stepper.jsx";
import Tabs from "./components/Tabs.jsx";
import TripResult from "./components/TripResult.jsx";
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

function RouteSummary({ trip, data, loading, error }) {
  if (!trip) return null;
  return (
    <div aria-live="polite">
      <h2 className="route-title">
        {trip.from} → {trip.to}
      </h2>
      {loading && <p className="route-summary">Calculating routes…</p>}
      {error && <p className="notice">{error}</p>}
      {data && !loading && (
        <p className="route-summary">
          {data.routes.length} {data.routes.length === 1 ? "route" : "routes"}
          {trip.expectedKm && ` (expected ~${trip.expectedKm.toLocaleString()} km)`} ·{" "}
          {pounds(data.weather.weight_lb)} load
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
  const [data, setData] = useState(null); // the endpoint's response: routes and weather
  const [loading, setLoading] = useState(false);
  const [routeError, setRouteError] = useState(null);
  const [step, setStep] = useState(0); // 0: route form, 1: distance & departure form
  // Departure in hours from now; set in the second form, drives the map's heat map.
  const [departureHour, setDepartureHour] = useState(0);
  // Checkpoints from the second endpoint, for the departure they were requested with.
  const [checkpoints, setCheckpoints] = useState(null);
  const [checkpointsLoading, setCheckpointsLoading] = useState(false);
  const [checkpointsError, setCheckpointsError] = useState(null);
  const result = useRef(null);

  const draft = tripFrom(tab, { origin, destination, example });

  const submit = (event) => {
    event.preventDefault();
    if (!draft) return;
    // A new object (and id), so submitting again refetches and resets the result.
    setTrip({ ...draft, weightLb, id: Date.now() });
    // Side by side the result is already in view; stacked, scroll down to it.
    result.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  };

  useEffect(() => {
    setData(null);
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
        setData(data);
        setDepartureHour(0); // new forecasts: start from leaving now
        setCheckpoints(null);
        setLoading(false);
        setStep(1); // the routes are in: on to the second form
      })
      .catch((err) => {
        if (err.name === "AbortError") return;
        setData(null);
        setRouteError(err.message);
        setLoading(false);
      });

    return () => controller.abort();
  }, [trip]);

  // Moving the departure makes shown checkpoints stale: clear them.
  const changeDeparture = (hours) => {
    setDepartureHour(hours);
    setCheckpoints(null);
    setCheckpointsError(null);
  };

  // Second form: checkpoints every distanceMi miles along each route, leaving at departure.
  const submitDistanceDeparture = ({ distanceMi, departure }) => {
    setCheckpointsLoading(true);
    setCheckpointsError(null);
    fetch("/api/v1/trips/checkpoints/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        trip_id: data.trip_id,
        distance_mi: distanceMi,
        departure: departure.toISOString(),
      }),
    })
      .then(async (response) => {
        const body = await response.json();
        if (!response.ok) throw new Error(body.detail ?? JSON.stringify(body));
        setCheckpoints(body);
      })
      .catch((err) => {
        setCheckpoints(null);
        setCheckpointsError(err.message);
      })
      .finally(() => setCheckpointsLoading(false));
  };

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
        <Stepper
          label="Trip steps"
          active={step}
          onChange={setStep}
          steps={[
            {
              id: "route",
              label: "Route",
              content: (
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
              ),
            },
            {
              id: "distance-departure",
              label: "Distance & departure",
              disabled: !data, // reached by submitting the first form
              content: data && (
                <DistanceDepartureForm
                  weather={data.weather}
                  departureHour={departureHour}
                  onDepartureChange={changeDeparture}
                  loading={checkpointsLoading}
                  error={checkpointsError}
                  checkpoints={checkpoints}
                  onBack={() => setStep(0)}
                  onSubmit={submitDistanceDeparture}
                />
              ),
            },
          ]}
        />

        <section ref={result} className="route-result">
          <RouteSummary trip={trip} data={data} loading={loading} error={routeError} />
          {data ? (
            <TripResult
              key={trip.id}
              apiKey={apiKey}
              data={data}
              departureHour={departureHour}
              checkpoints={checkpoints}
            />
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
