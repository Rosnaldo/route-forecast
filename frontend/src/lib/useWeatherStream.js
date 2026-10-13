import { useCallback, useEffect, useState } from "react";

// A trip's weather grid and its forecasts, streamed by the backend (server-sent events):
// first the grid (counties, cells, points), then forecasts batch by batch, the start of
// the trip first. Returns:
//   grid:    the "grid" event's data (null until it arrives)
//   series:  per grid point (index into grid.points), its forecast fields once loaded
//   loaded / failed: point counts so far; state: "loading" | "done" | "error"
//   detail: why points failed or the stream broke; retry(): fetch what is missing
export default function useWeatherStream(tripId) {
  const [grid, setGrid] = useState(null);
  const [series, setSeries] = useState([]);
  const [failed, setFailed] = useState(0);
  const [state, setState] = useState("loading");
  const [detail, setDetail] = useState(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!tripId) return undefined;
    setState("loading");
    setFailed(0);
    setDetail(null);
    const source = new EventSource(`/backend/trips/${tripId}/weather/`);

    source.addEventListener("grid", (event) => setGrid(JSON.parse(event.data)));
    source.addEventListener("batch", (event) => {
      const { points } = JSON.parse(event.data);
      setSeries((previous) => {
        const next = previous.slice();
        for (const point of points) next[point.index] = point;
        return next;
      });
    });
    source.addEventListener("batch-error", (event) => {
      const { indices, detail: why } = JSON.parse(event.data);
      setFailed((count) => count + indices.length);
      setDetail(why);
    });
    source.addEventListener("done", () => {
      source.close(); // otherwise EventSource reconnects and streams it all again
      setState("done");
    });
    // Connection lost (or the trip expired) before "done".
    source.onerror = () => {
      source.close();
      setState((current) => (current === "done" ? current : "error"));
      setDetail((current) => current ?? "Lost the connection while loading forecasts");
    };
    return () => source.close();
  }, [tripId, attempt]);

  // A new trip starts empty; a retry keeps what already loaded (the server resends it
  // from its cache and fetches only what is missing).
  useEffect(() => {
    setGrid(null);
    setSeries([]);
  }, [tripId]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  const loaded = series.reduce((count, point) => count + (point ? 1 : 0), 0);
  return { grid, series, loaded, failed, state, detail, retry };
}
