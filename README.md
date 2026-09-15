# VehicleShoot 360

Mobilos videóból automatikusan előállított, 36 nézetes prémium autóbemutató kereskedések számára.

## Termékfolyamat

1. A munkatárs megadja az autó készletazonosítóját.
2. Egy 30–40 másodperces videót készít, miközben körbejárja az autót.
3. A backend 108 jelölt képkockát nyer ki a videóból.
4. A worker a tájolás, élesség, expozíció, kontraszt és kiégett részletek alapján sorrendtartóan kiválaszt 36 egyedi nézetet.
5. A képeken képi horizontbecslés, körkörösen simított dőléskorrekció, céljármű-zárral védett háttéreltávolítás, expozíció-egységesítés és stabil méretezésű, kontaktárnyékos stúdiókompozíció fut.
6. Minden nézethez 1280 px-es gyorsnézet és 2400 px-es HD kép készül.
7. A dashboard élőben jelzi az állapotot és a minőségi pontszámot, majd megosztható és beágyazható 360° viewer készül.

## Architektúra

```text
React PWA
   │ video + orientation samples
   ▼
Express API ── FFmpeg ── 108 candidates ── MinIO
   │
   ▼
Redis Streams
   │
   ▼
Python workers ── QA + select 36 ── remove background ── compose studio
   │
   ├── preview + HD JPEGs ── MinIO
   └── progress + quality callback ── Express/Prisma
                                │
                                ▼
                      dashboard + 360 viewer
```

A `3d-worker` könyvtár korábbi Gaussian Splat kísérleti kódot tartalmazhat, de nem része az aktív Compose stacknek és nem fogyasztja a produkciós queue-t.

## Technológiák

- React 18, Vite és PWA
- Node.js 18, Express, Prisma és SQLite
- FFmpeg
- Redis Streams
- MinIO
- Python 3.11, rembg, OpenCV és Pillow

## Indítás

Előfeltétel: Docker és Docker Compose.

```bash
docker compose up --build
```

Elérhetőségek:

- alkalmazás: `http://localhost:5173`
- API és viewer: `http://localhost:3000`
- MinIO Console: `http://localhost:9001`

A kamera és a mozgásszenzorok telefonon HTTPS-kapcsolatot igényelnek. Helyi mobilteszthez használj HTTPS tunnelt, és állítsd be a `VITE_API_BASE_URL` értékét.

## Konfiguráció

Fontosabb backend változók:

```env
PORT=3000
BASE_URL=http://localhost:3000
DATABASE_URL=file:./dev.db
REDIS_URL=redis://redis:6379
MINIO_ENDPOINT=minio
MINIO_PORT=9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
INTERNAL_API_TOKEN=development-only-change-me
CANDIDATE_FRAMES=108
TARGET_FRAMES=36
ALLOWED_ORIGIN=*
WEBHOOK_URL=
```

Worker változók:

```env
BACKEND_URL=http://backend:3000
INTERNAL_API_TOKEN=development-only-change-me
TARGET_FRAMES=36
ENABLE_ALPHA_MATTING=false
ENABLE_GLASS_REPAIR=false
ENABLE_TARGET_LOCK=true
MAX_ROLL_CORRECTION=3.5
MAX_VEHICLE_ROLL_CORRECTION=5.5
MAX_PROCESSING_SIDE=1920
STALE_AFTER_MS=120000
TARGET_LOCK_CROP_TOP=0.16
TARGET_LOCK_CROP_BOTTOM=0.96
REMBG_MODEL=birefnet-general-lite
AI_WORKER_THREADS=4
ONNX_DISABLE_CPU_ARENA=true
```

A produkciós worker image csak az aktív feldolgozási út függőségeit tartalmazza. A korábbi, alapértelmezetten kikapcsolt FastSAM- és Real-ESRGAN-kísérletek nincsenek a képbe építve, mert a Torch/Ultralytics csomaglánc egy második OpenCV-disztribúciót telepített és bizonytalanná tette a buildet.

A `birefnet-general-lite` egyetlen workeres alapbeállítással fut: egy 1080p inference átmenetileg több GB memóriát használhat, ezért 8 GB-os Docker Desktop keretnél ne emeld a replikaszámot külön mérés nélkül. Nagyobb szerveren a worker külön gépekre skálázható.

Már kivágott projektek újrastabilizálhatók a neurális modell ismételt futtatása nélkül:

```bash
docker compose run --rm ai-worker python recompose.py jarmu-azonosito
```

Éles környezetben kötelező lecserélni a MinIO jelszót és az `INTERNAL_API_TOKEN` értékét, valamint konkrét originre szűkíteni az `ALLOWED_ORIGIN` beállítást.

## Session állapotok

- `uploading`: a videó fogadása
- `extracting`: FFmpeg képkockakinyerés
- `selecting`: a 36 optimális nézet kiválasztása
- `composing`: háttéreltávolítás és stúdiókompozíció
- `ready`: a viewer elkészült
- `failed`: a feldolgozás három sikertelen worker-próbálkozás után leállt

## API

- `POST /api/vehicles/:vehicleId/video` – videó és opcionális szenzoradat feltöltése
- `GET /api/sessions` – dashboard lista
- `GET /api/sessions/:vehicleId` – egy projekt élő állapota
- `DELETE /api/sessions/:vehicleId` – befejezett vagy sikertelen projekt törlése
- `GET /viewer/:vehicleId` – interaktív 360° bemutató
- `GET /embed.js` – beágyazó kliens
- `PATCH /internal/vehicles/:vehicleId/frame-processed` – tokennel védett worker callback
- `POST /internal/vehicles/:vehicleId/quality` – tokennel védett minőségellenőrzési callback

## Viewer képességek

- progresszív betöltés: kis gyorsnézetek, majd az aktuális és szomszédos képek HD frissítése
- egér-, érintés- és billentyűzetvezérlés, tehetetlenségi forgás
- kétujjas nagyítás, pásztázás, dupla kattintásos zoom és visszaállítás
- nézetscrubber, automatikus forgatás, teljes képernyő és natív megosztás
- automatikus frissítés, ha a viewer a feldolgozás befejezése előtt nyílik meg

## Ellenőrzések

```bash
cd frontend
npm run build

cd ../backend
npm test
npm run check
npx prisma validate

cd ..
python -m unittest discover -s ai-worker/tests -v
docker compose config
```

## Beágyazás

```html
<div data-vs360-vehicle="lancer-16"></div>
<script src="https://sajat-domain.hu/embed.js"></script>
```

## Produkciós megjegyzések

- SQLite helyett több backend példánynál PostgreSQL használata ajánlott.
- A publikus dashboard elé kereskedői autentikáció szükséges.
- A webhook kézbesítéshez tartós outbox/retry mechanizmus ajánlott.
- A queue backlogot, dead-letter streamet, feldolgozási időt és MinIO tárhelyet monitorozni kell.
