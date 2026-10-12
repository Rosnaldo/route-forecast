import { useState } from "react";

import PlaceInput from "./components/PlaceInput.jsx";

const apiKey = __GOOGLE_MAPS_API_KEY__;

function Selection({ place }) {
  if (!place) return <p className="place-selected" />;
  return (
    <p className="place-selected" aria-live="polite">
      {place.address} ({place.lat.toFixed(4)}, {place.lon.toFixed(4)})
    </p>
  );
}

export default function App() {
  const [origin, setOrigin] = useState(null);
  const [destination, setDestination] = useState(null);

  return (
    <main className="container">
      <h1>Trip weather</h1>

      {apiKey ? (
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
      ) : (
        <p className="notice">
          Set <code>GOOGLE_MAPS_API_KEY</code> in <code>.env</code> to enable address search.
        </p>
      )}
    </main>
  );
}
