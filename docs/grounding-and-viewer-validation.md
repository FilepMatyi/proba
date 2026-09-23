# Grounding and viewer regression notes

## Geometry

- Tire footprints use independent lower-silhouette lobes plus neutral material
  and local edge support. Both wheels may be on the same side of the image.
- Circle candidates also require a matching silhouette lobe. Narrow rear-view
  pairs around the bumper/hitch are treated conservatively.
- The perspective solver uses rotated contact coordinates, not a clipped angle.
  The default warp limit is now 0.3 (at most roughly 15% column-scale change).
  Camera height cannot be reconstructed exactly from a single 2D cutout.
- The complete orbit shares one platform depth and scale. The compositor solves
  for a common translation keeping measured contacts inside the ellipse.
  It enlarges the surface when a fixed thin ellipse cannot contain the pair.
- A projected contact residual is not an independent measurement of correctness.
  Occluded wheels and bumper-only masks still need visual review. Do not treat
  a successful geometric fit as proof that the detector chose the right parts.

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
docker compose exec -T ai-worker python inspect_grounding.py SESSION --audit --frames 1 5 6 21 28 36
```

The diagnostic command only reads stored assets and writes local files under
`ai-worker/diagnostics/grounding`. The contact sheet and JSON show inferred
anchors; visually check that those anchors actually belong to tires.

To compare a new processing variant, create a separate local session and run:

```sh
docker compose exec -T ai-worker python recompose.py NEW_SESSION --source-vehicle SOURCE_SESSION
```

This preserves the source masks. Re-running without `--source-vehicle` uses the
target's already transformed masks and can compound resampling. Use
`--compose-only` when changing only the background/contact composition.
