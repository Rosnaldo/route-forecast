import { useEffect, useMemo, useRef, useState } from "react";

import DistanceDepartureForm from "./components/DistanceDepartureForm.jsx";
import ExampleRoutes from "./components/ExampleRoutes.jsx";
import PlaceInput from "./components/PlaceInput.jsx";
import RecommendationStep from "./components/RecommendationStep.jsx";
import Stepper from "./components/Stepper.jsx";
import Tabs from "./components/Tabs.jsx";
import TripResult from "./components/TripResult.jsx";
import { WEIGHT_DEFAULT, WEIGHT_MAX, WEIGHT_MIN, WEIGHT_STEP, pounds } from "./lib/load.js";
import useWeatherStream from "./lib/useWeatherStream.js";

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
          {pounds(data.weight_lb)} load
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
  const [step, setStep] = useState(0); // 0: route, 1: distance & departure, 2: recommendation
  // Departure in hours from now; set in the second form, drives the map's heat map.
  const [departureHour, setDepartureHour] = useState(0);
  // Checkpoints from the second endpoint, for the departure they were requested with.
  const [checkpoints, setCheckpoints] = useState(null);
  const [checkpointsLoading, setCheckpointsLoading] = useState(false);
  const [checkpointsError, setCheckpointsError] = useState(null);
  // Recommended route from the third endpoint, for the same trip and departure.
  const [recommendation, setRecommendation] = useState(null);

  // The route response draws the map (route lines); the stream then brings the grid
  // (counties, cells) and its forecasts. `routes` stays the route response's own list so
  // the map is not rebuilt; the grid's per-route counties and cells are `routeGrids`.
  const stream = useWeatherStream(data?.trip_id);
  const { grid } = stream;
  const weather = useMemo(() => {
    if (!grid) return null;
    const points = grid.points.map((point, i) =>
      stream.series[i] ? { ...point, ...stream.series[i] } : point,
    );
    return { ...grid, points };
  }, [grid, stream.series]);
  const shown = useMemo(
    () =>
      data && {
        ...data,
        routeGrids: grid?.routes ?? null,
        counties: grid?.counties ?? [],
        weather,
      },
    [data, grid, weather],
  );
  const forecastStatus = {
    state: stream.state,
    loaded: stream.loaded,
    failed: stream.failed,
    total: grid?.points.length ?? 0,
    hasGrid: Boolean(grid),
    detail: stream.detail,
    retry: stream.retry,
  };
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
        setRecommendation(null);
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
    setRecommendation(null);
    setCheckpointsError(null);
  };

  // Second form: checkpoints every distanceMi miles along each route, leaving at departure,
  // then the recommended route for that departure.
  const submitDistanceDeparture = ({ distanceMi, departure }) => {
    const post = (path, body) =>
      fetch(`/api/v1/trips/${path}/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          trip_id: data.trip_id,
          departure: departure.toISOString(),
          ...body,
        }),
      }).then(async (response) => {
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail ?? JSON.stringify(result));
        return result;
      });

    setCheckpointsLoading(true);
    setCheckpointsError(null);
    setCheckpoints(null);
    setRecommendation(null);
    post("checkpoints", { distance_mi: distanceMi })
      .then((result) => {
        setCheckpoints(result);
        return post("recommendation", {});
      })
      .then((result) => {
        setRecommendation(result);
        setStep(2); // on to the recommendation
      })
      .catch((err) => setCheckpointsError(err.message))
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
                  weather={weather}
                  departureHour={departureHour}
                  onDepartureChange={changeDeparture}
                  forecastStatus={forecastStatus}
                  loading={checkpointsLoading}
                  error={checkpointsError}
                  checkpoints={checkpoints}
                  onBack={() => setStep(0)}
                  onSubmit={submitDistanceDeparture}
                />
              ),
            },
            {
              id: "recommendation",
              label: "Recommendation",
              disabled: !recommendation, // reached by submitting the second form
              content: recommendation && checkpoints && (
                <RecommendationStep
                  recommendation={recommendation}
                  checkpoints={checkpoints}
                  onBack={() => setStep(1)}
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
              data={shown}
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
