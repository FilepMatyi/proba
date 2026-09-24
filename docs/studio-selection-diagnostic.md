# 10 Studio Photos — forrásválasztási diagnózis

Session: `car-test-5-studio-photos-v3`, 2026-09-24. Ez kizárólag a külön fotóexportot
érinti; a 36 képes viewer kódja és outputja változatlan.

Az eredeti capture 108 darab 1920 × 1080-as videóframe-et tartalmaz. Az aktív
MinIO-objektumok között ehhez a sessionhöz nem volt COLMAP kameraközéppont vagy
orientáció. A kiválasztás ezért `sequence_fallback`: a rendezett körsorozat
alapján 10 célirány, célonként ±18°-os ablak, 3/4 nézetnél ±26°-os ablak.
Az összes 108 frame gyors előszűrést kapott; a BiRefNet-proxy 50 különböző
jelöltet mért. Egy célirányból legfeljebb öt jelölt kerül a végső pontozásba.
Az egymáshoz túl közeli vagy azonos forrásframe-eket a közös kiválasztás
elkerüli. A körirányok ebben a fallbackben közelítőek, nem mértek azimutok.

Pontszámsúlyok: szög 10%, autórégió-élesség 22%, expozíció 7%, proxy-maszk
8%, relatív nézőpont 23%, perspektíva 14%, framing 10%, forrásrészletesség
6%. Ezen felül motion-blur és edge-clipping büntetés van. A relatív nézőpont
felső sziluettarányt, gumikontaktus-képsorok eltérését és látható kerékgeometriát
használ; nem állít fizikai kamera-magasságot vagy pitch-szöget egyetlen képből.
Ha később COLMAP-póz kerül a tárolóba, az adapter relatív körszöget,
elevációeltérést és kameratávolságot ad hozzá, kalibrálatlan világkoordinátát
nem tekint valódi gravitációhoz mért magasságnak.

| Cél | Korábbi frame | Új frame | Új szöghiba | Összpontszám | Relatív nézőpont | Választás fő oka |
| ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 0° | 4 | 1 | 0.0° | .824 | .80 | kis vágási kockázat, jó oldalnézet |
| 36° | 14 | 13 | 4.0° | .656 | .49 | a vizsgált közeli jelölteknél több szabad margó; közepes bizonyosság |
| 72° | 23 | 22 | 2.0° | .776 | 1.00 | stabilabb hátsó nézet, nincs élérintés |
| 108° | 35 | 34 | 2.0° | .801 | .69 | jó perspektíva és keretezés |
| 144° | 44 | 47 | 9.3° | .739 | .66 | a 44-esnél jobb nézőpont és perspektíva a nagyobb szöghiba ellenére |
| 180° | 56 | 57 | 6.7° | .742 | 1.00 | az 55–56-os oldalnézetek erős edge-clipping kockázatát csökkenti |
| 216° | 68 | 66 | 0.7° | .778 | .77 | erős összpontszám és pontos célirány |
| 252° | 77 | 77 | 1.3° | .848 | .85 | éles, jó front-háromnegyedes forrás maradt |
| 288° | 89 | 87 | 1.3° | .830 | .73 | éles frontnézet kis szöghibával |
| 324° | 98 | 97 | 4.0° | .849 | .86 | jó élesség, nézőpont és keretezés |

A MinIO-ban mind a tíz `3840×2160` JPEG újra készült a
`car-test-5-studio-photos-v3/studio-photos/` prefixben. A manifest és a ZIP
szintén új; a ZIP 10 JPEG-et tartalmaz. Az összes végső kép az eredeti
forrásframe-ből újraszegmentált soft matte-ot használta, tároltmaszk-fallback
nélkül. A `selection-debug.json` célonként az öt legjobb jelöltet és
részpontszámokat, a `selection-contact-sheet.jpg` vizuális összevetést ad.
A lokális `ai-worker/debug/car-test-5-studio-photos-v3-selection/` mappa
őriz egy régi–új kontaktlapot, a tíz új JPEG-et, az eredeti forrásokat és a
manifestet.

Vizuális ellenőrzés: az új nézeteknél a jármű körüli margó és egyes
háromnegyedes perspektívák valamivel kiegyensúlyozottabbak, de az eltérés
több képen kicsi. A forrás ugyanannak a kézből, viszonylag magas kameraállásból
felvett 108 frame-es videónak a sorozata; valóban szemmagasságú, hosszabb
fókusztávolságú nézetet a frame-választó nem tud előállítani. A 7. képen a
tetőcsomagtartó mögötti épület háromszög alakú részlete is bekerült a matte-ba;
ez a meglévő detail-szegmentálás külön hibája, amelyhez ebben a kizárólag
forrásválasztásra irányuló feladatban nem nyúltunk. A source frame-ek mind
1920×1080-asak, tehát a 4K fájl nem jelent natív 4K autórészletet.
