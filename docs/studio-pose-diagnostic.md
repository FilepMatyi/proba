# 10 Studio Photos — stance diagnosis (car-test-5-studio-photos-v3)

The 10 selected original video frames were resegmented through the active
Studio Photos detail path. Per-photo source, final foreground RGBA, detected
contacts/bounds, previous output, new output, placement overlay and a
before/after pair are in
`ai-worker/debug/car-test-5-studio-photos-v3-pose-before/`. The complete
measurements are in `diagnostics.json` and `pose-after.json` there.

## Cause

The old photo compositor placed the car using a supported *silhouette* bottom
while its tire detector affected only shadows. It also reused a variable
viewer-derived height ratio and platform-derived floor coordinate for the
separate photo appearance. This produced 369–472 px top placement across the
ten 4K photos (standard deviation 34.5 px). It did not rotate the car.
Unreliable wheel lobes (notably views 4 and 8) were occasionally accepted as
tires for shadows. A horizontal underbody ellipse sat at the median of near
and far tire rows even when those rows were far apart in perspective.

The raw footage additionally has changing camera azimuth/elevation. A tire
line's image-space slope is not, by itself, camera roll. There is no 3D model
from which to recover true pitch, so perspective/pitch is not warped away.

| Photo | View | Tire-line slope | Body-line slope | Applied roll | Diagnosis |
|---:|---|---:|---:|---:|---|
| 01 | near-side | +10.95° | 0.00° | 0° | wheel slope is perspective |
| 02 | rear 3/4 | +29.03° | +0.75° | 0° | strong foreshortening |
| 03 | rear | +0.39° | −4.20° | 0° | independent cues disagree |
| 04 | rear 3/4 | unavailable | −0.54° | 0° | false second tire rejected |
| 05 | rear/side 3/4 | −21.52° | −1.38° | 0° | strong foreshortening |
| 06 | side | −2.35° | +1.43° | 0° | body and tire cues disagree |
| 07 | front/side 3/4 | +15.71° | unavailable | 0° | perspective, insufficient body line |
| 08 | front 3/4 | unavailable | −4.47° | 0° | false second tire rejected |
| 09 | near-front | unavailable | +3.98° | 0° | only one reliable tire |
| 10 | front 3/4 | −28.35° | −0.40° | 0° | strong foreshortening |

The axis types are geometrical classifications, not exact azimuths. A
conservative roll estimator is now available for later captures: up to 2°
only for near-axial side/front/rear views when both tire and long body-line
cues agree. It did **not** rotate any of these ten Ford frames; claiming that
they are mathematically level would be misleading.

## Result

The photo branch now anchors the nearest reliable tire to its own fixed
cyclorama floor line, rejecting small bumper/hitch lobes. It uses a single
photo-specific target height independent of the viewer layout ratio. Across
these ten exports, the car's top placement is now 406–419 px (standard
deviation 3.5 px) and the nearest tire contacts are 1883.5–1886.5 px around
the 1884 px floor coordinate. Far tires remain higher where natural 3/4
perspective requires it. The underbody/ambient shadow follows the final
near/far contact segment, and reflection follows the same final placement.

All ten 3840×2160 JPEGs, manifest and ZIP were regenerated in MinIO under
`car-test-5-studio-photos-v3/studio-photos/`. The existing 360 viewer was not
reprocessed or changed. The remaining limitation is source-camera
perspective: strong pitch/elevation variation cannot safely be converted into
eye-level studio photography by a 2D affine transform.
