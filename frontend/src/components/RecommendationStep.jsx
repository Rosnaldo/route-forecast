import { NO_FORECAST_COLOR, RISK_LEVELS } from "../lib/risk.js";
import { routeColor, routeName } from "../lib/routes.js";

// Columns of the miles table: the API's miles_by_level keys, in risk order.
const MILES_COLUMNS = [
  ...RISK_LEVELS.map(({ label, color }) => ({
    key: label.toLowerCase().replace(" ", "_"),
    label,
    color,
  })),
  { key: "no_forecast", label: "No forecast", color: NO_FORECAST_COLOR },
];

// The ranking rules in order (the API's decided_by values), as shown to the user.
const RULES = {
  severe_miles: "1. Fewest Severe miles",
  high_miles: "2. Fewest High miles",
  average_level: "3. Lowest average risk",
  travel_s: "4. Shortest travel time",
};

// Which rule decided the recommendation.
function decidingRule({ decided_by: decidedBy }) {
  if (decidedBy in RULES) return `Deciding rule: ${RULES[decidedBy]}`;
  if (decidedBy === "tie") return "All rules tied: the first route is chosen";
  return "It is the only route";
}

// The recommended route (third endpoint) and why.
function RecommendationNote({ recommendation }) {
  const route = recommendation.recommended;
  return (
    <div className="recommendation" aria-live="polite">
      <span className="place-label">Recommended</span>
      <p>
        <span className="legend-line" style={{ background: routeColor(route) }} />
        <strong>{routeName(route)}</strong> — {decidingRule(recommendation)}
      </p>
    </div>
  );
}

const etaFormat = new Intl.DateTimeFormat(undefined, {
  weekday: "short",
  hour: "2-digit",
  minute: "2-digit",
});

// Miles of each route at each risk level when the truck gets there, its average risk
// and its arrival time; `scores` is the recommendation's ranking (any order).
function MilesTable({ routes, scores, departure }) {
  const scoreOf = new Map(scores.map((score) => [score.route, score]));
  return (
    <div className="miles">
      <table className="miles-table" aria-label="Miles at each risk level, average risk and ETA">
        <thead>
          <tr>
            <th scope="col">Route</th>
            {MILES_COLUMNS.map(({ key, label, color }) => (
              <th key={key} scope="col" className="num">
                <span className="legend-swatch" style={{ background: color }} />
                {label}
              </th>
            ))}
            <th scope="col" className="num" title="Mile-weighted risk level, 0 (Low) to 4 (No Travel)">
              Avg risk
            </th>
            <th scope="col" className="num" title="Arrival at the destination, breaks included">
              ETA
            </th>
          </tr>
        </thead>
        <tbody>
          {routes.map((route, index) => (
            <tr key={index}>
              <th scope="row">
                <span className="legend-line" style={{ background: routeColor(index) }} />
                {routeName(index)}
              </th>
              {MILES_COLUMNS.map(({ key }) => (
                <td key={key} className={`num${route.miles_by_level[key] ? "" : " zero"}`}>
                  {route.miles_by_level[key].toFixed(1)}
                </td>
              ))}
              <td className="num">{scoreOf.get(index).average_level?.toFixed(2) ?? "—"}</td>
              <td className="num">
                {etaFormat.format(new Date(departure.getTime() + scoreOf.get(index).travel_s * 1000))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Third step: the recommended route and why, with every route's miles per risk level.
export default function RecommendationStep({ recommendation, checkpoints, onBack }) {
  return (
    <div className="trip-form">
      <RecommendationNote recommendation={recommendation} />
      <MilesTable
        routes={checkpoints.routes}
        scores={recommendation.ranking}
        departure={new Date(recommendation.departure)}
      />
      <div className="form-actions">
        <button type="button" className="secondary" onClick={onBack}>
          Back
        </button>
      </div>
    </div>
  );
}
