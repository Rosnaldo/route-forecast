const timeFormat = new Intl.DateTimeFormat(undefined, {
  weekday: "short",
  hour: "numeric",
  minute: "2-digit",
});

// Departure time as hours from now (0 to the forecast window), for a weather grid
// from the route endpoint.
export default function DepartureSlider({ weather, hours, onChange }) {
  const departure = new Date((weather.now + hours * 3600) * 1000);
  return (
    <label className="map-slider">
      <span className="place-label">Departure</span>
      <input
        type="range"
        min={0}
        max={weather.hours}
        step={1}
        value={hours}
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
