import { useEffect, useRef, useState } from "react";

import { loadGoogleMaps } from "../lib/googleMaps.js";

// Address input backed by Google Places Autocomplete (Places API New).
// Calls onSelect({ address, lat, lon }) when the user picks a suggestion.
export default function PlaceInput({ apiKey, label, onSelect }) {
  const container = useRef(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    let element;

    loadGoogleMaps(apiKey)
      .then((maps) => maps.importLibrary("places"))
      .then(({ PlaceAutocompleteElement }) => {
        if (cancelled) return;
        element = new PlaceAutocompleteElement({ includedRegionCodes: ["us"] });
        element.setAttribute("aria-label", label);
        element.addEventListener("gmp-select", async ({ placePrediction }) => {
          const place = placePrediction.toPlace();
          await place.fetchFields({ fields: ["formattedAddress", "location"] });
          onSelect({
            address: place.formattedAddress,
            lat: place.location.lat(),
            lon: place.location.lng(),
          });
        });
        container.current.append(element);
      })
      .catch((err) => !cancelled && setError(err.message));

    // StrictMode mounts twice in development: remove the element we added.
    return () => {
      cancelled = true;
      element?.remove();
    };
  }, [apiKey, label, onSelect]);

  return (
    <>
      <span className="place-label">{label}</span>
      <div className="place-input" ref={container} />
      {error && <p className="notice">{error}</p>}
    </>
  );
}
