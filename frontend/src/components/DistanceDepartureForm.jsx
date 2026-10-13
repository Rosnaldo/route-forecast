import { useState } from "react";

import DepartureSlider from "./DepartureSlider.jsx";

const DISTANCES_MI = [10, 25, 50];

// Second step: the gap between checkpoints (10 / 25 / 50 miles) and the departure time,
// as hours from now within the forecast window of `weather`. The departure also drives
// the map, so its value lives in the parent. Calls onSubmit({ distanceMi, departure }),
// departure a Date; `checkpoints` is the last result, `loading`/`error` the requests
// (checkpoints, then the recommendation shown in the next step).
export default function DistanceDepartureForm({
  weather,
  departureHour,
  onDepartureChange,
  onBack,
  onSubmit,
  loading,
  error,
  checkpoints,
}) {
  const [distanceMi, setDistanceMi] = useState(null);

  const submit = (event) => {
    event.preventDefault();
    if (distanceMi == null) return;
    const departure = new Date((weather.now + departureHour * 3600) * 1000);
    onSubmit({ distanceMi, departure });
  };

  return (
    <form className="trip-form" onSubmit={submit}>
      <fieldset className="choice-field">
        <legend className="place-label">Checkpoint every</legend>
        <div className="choice-options">
          {DISTANCES_MI.map((miles) => (
            <label key={miles} className="choice">
              <input
                type="radio"
                name="distance"
                value={miles}
                checked={distanceMi === miles}
                onChange={() => setDistanceMi(miles)}
                required
              />
              {miles} miles
            </label>
          ))}
        </div>
      </fieldset>

      <DepartureSlider weather={weather} hours={departureHour} onChange={onDepartureChange} />

      <div className="form-actions">
        <button type="button" className="secondary" onClick={onBack}>
          Back
        </button>
        <button type="submit" className="submit" disabled={distanceMi == null || loading}>
          {loading ? "Calculating…" : "Submit"}
        </button>
        {distanceMi == null && <span className="place-selected">Pick a distance.</span>}
      </div>
      {error && <p className="notice">{error}</p>}
      {checkpoints && (
        <>
          <p className="place-selected" aria-live="polite">
            {checkpoints.routes.reduce((sum, route) => sum + route.checkpoints.length, 0)}{" "}
            checkpoints every {checkpoints.distance_mi} miles on the map, each with its arrival
            time. Hover one for travel time and forecast.
          </p>

        </>
      )}
    </form>
  );
}
