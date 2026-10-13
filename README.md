# Weather-Aware Truck Routing

A React + Django web app that helps a truck driver choose the safest route
based on weather, load weight and travel time. The user enters an origin, a
destination, a departure time and a load weight. The app compares three route
options, samples the forecast at each checkpoint for the moment the truck is
expected to arrive there, classifies the weather risk, and recommends the best
route.

## Assumptions

- Region: contiguous United States
- Forecast window: 48 hours
- Weather factors: wind (mph); rain (in/hr); snow (in/hr)
- 30-minute stop after every 8 hours of driving.
- velocity 100 km/h used as fallback
- the heatmap forecast area are represented by grids of 20km squares

```
average = Σ (level × piece length) ÷ Σ (piece length)      over pieces that have a forecast
```

## External APIs

- **Google Routes API** (`routes.googleapis.com/directions/v2:computeRoutes`) — returns up to three driving route options between origin and destination (backend, [services/routing.py](apps/trips/services/routing.py)).
- **Google Maps JavaScript API** — render the map (frontend, [googleMaps.js](frontend/src/lib/googleMaps.js)).
- **Google Places API** (Maps JS `places` library) — autocompletes the origin and destination inputs (frontend, [PlaceInput.jsx](frontend/src/components/PlaceInput.jsx)).
- **Open-Meteo Forecast API** (`api.open-meteo.com/v1/forecast`) — free hourly wind, rain and snow forecasts for each grid point (backend, [services/weather.py](apps/trips/services/weather.py)).

## County boundaries

[data/cb_2024_us_county_500k.zip](data/cb_2024_us_county_500k.zip) is a **local
copy of every US county's shape**.

- **Source:** the US Census Bureau's 2024 cartographic boundary file.
- **How it's used:** [services/counties.py](apps/trips/services/counties.py) loads
  every outline into memory once per process and finds the counties a route
  crosses, in travel order. The map gets a simplified (~500 m) outline of each one.

**What is the spatial index?** A fast check that finds the few counties near
the route, and only those get the exact geometry check. Without it, every
request would test the route against all 3,235 county polygons.
