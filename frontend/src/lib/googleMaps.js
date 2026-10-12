// Loads the Maps JavaScript API once per page and resolves with `google.maps`.
let loading;

export function loadGoogleMaps(apiKey) {
  loading ??= new Promise((resolve, reject) => {
    const callback = "__onGoogleMapsLoaded";
    window[callback] = () => resolve(window.google.maps);

    const params = new URLSearchParams({ key: apiKey, loading: "async", v: "weekly", callback });
    const script = document.createElement("script");
    script.src = `https://maps.googleapis.com/maps/api/js?${params}`;
    script.async = true;
    script.onerror = () => reject(new Error("Google Maps failed to load"));
    document.head.append(script);
  });
  return loading;
}
