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


```
average = Σ (level × piece length) ÷ Σ (piece length)      over pieces that have a forecast
```