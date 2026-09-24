# Grounding and viewer regression notes

## Geometry

- The active worker no longer applies scene-roll, wheel-point roll, or
  perspective warp to the captured vehicle. Those helpers remain only for
  legacy diagnostics and their own tests.
- Each final image is proportionally scaled, centered from the mask bounding
  box, and translated so a robust lower silhouette anchor meets a fixed floor
  level. Narrow tow hitches and isolated alpha dust do not define that anchor.
- Robust supported mask-bottom runs define the vertical anchor. Reliable tire
  contacts position shadows only, so intermittent detections cannot move,
  rotate or warp the vehicle. A broad soft body shadow
  follows the same translation. The viewer keeps its wider turntable surface;
  the separate photo export uses a seamless cyclorama without the drawn hub.
  A single 2D cutout still cannot recover camera height or true 3D geometry;
  inspect difficult views visually.

## Viewer

- Pan/zoom modifies one shared layer once per animation frame, not 36 images.
- HD loads are deduplicated and limited to two concurrent decodes; only the
  active frame and its neighbours retain HD. Fast spins use previews until a
  view settles for 120 ms. No synthesized paint/scratch detail or frame blending.
- Wheel/double-click zoom preserves the point beneath the pointer; pointer
  cancellation, capture loss and window blur clear the gesture state.
- Inertia is elapsed-time based. The input remains a discrete 36-view orbit;
  it does not provide continuous novel 3D viewpoints.

## Repeatable checks

```sh
docker compose exec -T backend npm test
docker compose exec -T ai-worker python -m unittest discover -s tests
```

The legacy `inspect_grounding.py` audit can still examine inferred wheel
contacts, but its wheel-fit score no longer describes the active compositor.

To compare a new processing variant, create a separate local session and run:

```sh
docker compose exec -T ai-worker python recompose.py NEW_SESSION --source-vehicle SOURCE_SESSION
```

This preserves the source masks. Re-running without `--source-vehicle` uses the
target's already transformed masks and can compound resampling. Use
`--compose-only` when changing only the background/contact composition.
