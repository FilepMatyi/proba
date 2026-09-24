# Studio Photos: vékony részletek diagnózisa

A `car-test-5-studio-photos-v3` export 4. fotója a 12. tárolt nézetből, az
eredeti `car-test-5-premium-v2/candidates/frame-035.jpg` frame-ből származik.
Az egyezést 413 ORB/RANSAC inlierrel ellenőriztük. A hét kért köztes kép az
`ai-worker/debug/studio-mask-frame-12/` könyvtárban van; a `03b` és `06b`
plusz fájlok segítenek elkülöníteni a pontos veszteségi pontot.

| Lépés | Debug fájl | Megfigyelés |
| --- | --- | --- |
| 01 eredeti frame | `01_original_source.jpg` | A két rúd és a tartók láthatók. |
| 02 inferencia input | `02_segmentation_input.jpg` | Teljes 1920×1080 frame, előzetes crop nélkül. |
| 03 nyers BiRefNet alpha | `03_raw_birefnet_alpha.png` | A vékony részek nagy része soft alfával jelen van. |
| 04 resize után | `04_alpha_after_resize.png` | Ugyanaz a 1920×1080 geometria; itt nincs veszteség. |
| 05 cleanup után | `05_alpha_after_cleanup.png` | A korábbi bináris post-process eredménye. |
| 06 előtér RGBA | `06_final_foreground_rgba.png` | Régi, eltárolt maszk; a `06_current_pipeline_foreground_rgba.png` a mai régi úttal reprodukált változat. |
| 07 stúdiókompozit | `07_final_studio_composite.jpg` | Korábbi fotó-export. |

A döntő, közbeiktatott ellenőrzés a `03b_rembg_postprocess_alpha.png`. A
`rembg` `post_process_mask=True` ága morfológiai nyitást, Gaussian-blurt,
majd 127/255-ös kemény küszöbölést végez. A tető régiójában
(`x=580..1139`, `y=185..284`) a nyers BiRefNet alfában 34 440 pixel volt
legalább 24/255 értékű, a post-process után 33 535: 905 ilyen pixel eltűnt.
A nyers régió 35 086 soft, 1–254 közötti pixelt tartalmazott; a post-process
után egyet sem. A saját komponens-választás ezen a frame-en nem csökkentette
tovább a foreground pixelszámot. Tehát a fő ok a `rembg` bináris
utófeldolgozása, nem a crop, a resize vagy a végső canvas/framing.

Az új 10-fotós ág csak a kiválasztott eredeti frame-eket szegmentálja újra.
A nyers alpha float32-ként marad meg; 0.55-ös erős magból a hozzá 0.10 fölött
kapcsolódó gyenge régiót tartja meg, izolált hátteret nem. A detail pass
forrásképből készített, oldalanként 10%, felül 16%, alul 10% paddingű ROI-t
használ (minimum 32 pixel), és crop-edge veszély esetén kibővítve újrapróbálja.
A végső árnyék, padlóreflexió és a 36 képes viewer változatlan.

Az új `08_studio_soft_alpha.png`, `08_studio_foreground_rgba.png` és
`09_studio_detail_composite.jpg` a javított köztes eredmény; a ténylegesen
újragenerált fotó a `10_final_export_04.jpg`. Az új 10-képes manifest mind a
10 nézetnél `original-frame-soft-matte` forrást jelez, tároltmaszk-fallback
nélkül. Kilenc nézetnél a részlet-pass elfogadott javítást adott, egynél a
teljes frame soft alfája maradt meg.
