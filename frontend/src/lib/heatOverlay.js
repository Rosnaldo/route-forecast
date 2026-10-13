// The smooth heat map on the Google map: one canvas over the grid's box, under the
// route lines (mapPane, like a ground overlay), redrawn only when the forecasts change
// or the zoom changes its resolution. Pixels come from heatField.js; the canvas is then
// cut to the cells' outlines, so the field ends at the county borders as the cells do.

import { gridBounds, mercatorY, renderField } from "./heatField.js";

// Canvas pixels: past this, zooming in scales the image up. The field is smooth, so this
// costs little sharpness, and a redraw stays ~40 ms at worst.
const MAX_SIDE = 1280;

// The overlay class needs google.maps loaded, so it is made on first use.
let HeatOverlay;

export function createHeatOverlay(maps) {
  HeatOverlay ??= class extends maps.OverlayView {
    constructor() {
      super();
      this.canvas = document.createElement("canvas");
      Object.assign(this.canvas.style, { position: "absolute", pointerEvents: "none" });
      this.weather = null;
      this.dirty = false;
    }

    // Show `weather`'s field with these per-point `values` (heatField.centerValues);
    // null hides it.
    setField(weather, values) {
      if (weather !== this.weather) this.bounds = weather && gridBounds(weather);
      this.weather = weather;
      this.values = values;
      this.dirty = true;
      this.draw();
    }

    onAdd() {
      this.getPanes().mapPane.appendChild(this.canvas);
    }

    onRemove() {
      this.canvas.remove();
    }

    // Called by the map on zoom and on setField: place the canvas, and re-render it when
    // the data or the resolution it should have changed.
    draw() {
      const projection = this.getProjection();
      if (!projection || !this.weather) {
        this.canvas.style.display = "none";
        return;
      }
      const { south, north, west, east } = this.bounds;
      const sw = projection.fromLatLngToDivPixel(new maps.LatLng(south, west));
      const ne = projection.fromLatLngToDivPixel(new maps.LatLng(north, east));
      const cssWidth = ne.x - sw.x;
      const cssHeight = sw.y - ne.y;
      Object.assign(this.canvas.style, {
        display: "block",
        left: `${sw.x}px`,
        top: `${ne.y}px`,
        width: `${cssWidth}px`,
        height: `${cssHeight}px`,
      });

      // As sharp as the screen shows it, up to MAX_SIDE.
      const density = Math.min(window.devicePixelRatio || 1, 1.5);
      const fit = Math.min(1, MAX_SIDE / (Math.max(cssWidth, cssHeight) * density));
      const width = Math.max(1, Math.round(cssWidth * density * fit));
      const height = Math.max(1, Math.round(cssHeight * density * fit));
      if (!this.dirty && width === this.canvas.width && height === this.canvas.height) return;
      this.dirty = false;
      this.render(width, height);
    }

    render(width, height) {
      const { canvas, weather, bounds } = this;
      canvas.width = width;
      canvas.height = height;
      const context = canvas.getContext("2d");
      const pixels = renderField(weather, this.values, bounds, width, height);
      context.putImageData(new ImageData(pixels, width, height), 0, 0);

      // Keep only what lies inside the cells (one path: no seams between them).
      const yNorth = mercatorY(bounds.north);
      const ySouth = mercatorY(bounds.south);
      const x = (lon) => ((lon - bounds.west) / (bounds.east - bounds.west)) * width;
      const y = (lat) => ((yNorth - mercatorY(lat)) / (yNorth - ySouth)) * height;
      const path = new Path2D();
      for (const { geometry } of weather.cells) {
        const polygons =
          geometry.type === "Polygon"
            ? [geometry.coordinates]
            : geometry.type === "MultiPolygon"
              ? geometry.coordinates
              : [];
        for (const rings of polygons) {
          for (const ring of rings) {
            ring.forEach(([lon, lat], index) =>
              index ? path.lineTo(x(lon), y(lat)) : path.moveTo(x(lon), y(lat)),
            );
            path.closePath();
          }
        }
      }
      context.globalCompositeOperation = "destination-in";
      context.fill(path, "evenodd");
      context.globalCompositeOperation = "source-over";
    }
  };
  return new HeatOverlay();
}
