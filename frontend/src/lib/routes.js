// How each route option is named and drawn, by its index in the response (A, B, C).
// Blue / violet / teal stay clear of the yellow-to-red risk heat map.
export const ROUTE_COLORS = ["#2563eb", "#7c3aed", "#0d9488"];

export const routeName = (index) => `Route ${String.fromCharCode(65 + index)}`;
export const routeLetter = (index) => String.fromCharCode(65 + index);
export const routeColor = (index) => ROUTE_COLORS[index % ROUTE_COLORS.length];

