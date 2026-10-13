const timeFormat = new Intl.DateTimeFormat(undefined, {
  weekday: "short",
  hour: "numeric",
  minute: "2-digit",
});

const FORECAST_HOURS = 48; // until the grid (with its own `hours`) has streamed in

// Departure time as hours from now (0 to the forecast window), for the trip's weather
// grid (null until it has streamed in: then counted from the current time).
export default function DepartureSlider({ weather, hours, onChange, disabled = false }) {
  const now = weather?.now ?? Date.now() / 1000;
  const departure = new Date((now + hours * 3600) * 1000);
  return (
    <label className="map-slider">
      <span className="place-label">Departure</span>
      <input
        type="range"
        min={0}
        max={weather?.hours ?? FORECAST_HOURS}
        step={1}
        value={hours}
        disabled={disabled}
        onChange={(event) => onChange(Number(event.target.value))}
        aria-valuetext={`${hours === 0 ? "now" : `in ${hours} hours`}, ${timeFormat.format(departure)}`}
      />
      <span className="map-slider-scale" aria-hidden="true">
        <span>now</span>
        <span>+12 h</span>
        <span>+24 h</span>
        <span>+36 h</span>
        <span>+48 h</span>
      </span>
      <span className="place-selected">
        <strong>{hours === 0 ? "Now" : `In ${hours} h`}</strong> · {timeFormat.format(departure)}
      </span>
    </label>
  );
}
