import { useEffect, useState } from "react";

// Sample trips from example_routes.csv (served by the backend). Clicking a row
// calls onSelect(example) to request that route.
export default function ExampleRoutes({ selectedId, onSelect }) {
  const [examples, setExamples] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch("/api/v1/trips/examples/")
      .then((response) => {
        if (!response.ok) throw new Error("Could not load example routes");
        return response.json();
      })
      .then(setExamples)
      .catch((err) => setError(err.message));
  }, []);

  if (error) return <p className="notice">{error}</p>;

  const onKeyDown = (event, example) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onSelect(example);
    }
  };

  return (
    <div className="examples">
      <table className="examples-table">
        <caption>Example routes: click one to compute it</caption>
        <thead>
          <tr>
            <th scope="col">#</th>
            <th scope="col">Departure</th>
            <th scope="col">Arrival</th>
            <th scope="col" className="num">Expected</th>
            <th scope="col">What it tests</th>
          </tr>
        </thead>
        <tbody>
          {examples.map((example) => (
            <tr
              key={example.id}
              tabIndex={0}
              aria-current={example.id === selectedId || undefined}
              className={example.id === selectedId ? "selected" : undefined}
              onClick={() => onSelect(example)}
              onKeyDown={(event) => onKeyDown(event, example)}
            >
              <td className="num">{example.id}</td>
              <td>{example.departure}</td>
              <td>{example.arrival}</td>
              <td className="num">{example.distance_km.toLocaleString()} km</td>
              <td className="purpose">{example.purpose}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
