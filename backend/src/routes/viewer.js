const crypto = require('crypto');
const express = require('express');

const config = require('../config');
const { minioClient, PROCESSED_BUCKET } = require('../lib/minioClient');
const { normalizeVehicleId, parsePhotoIndex } = require('../lib/vehicleId');
const sessionService = require('../services/sessionService');

const router = express.Router();

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function safeJson(value) {
  return JSON.stringify(value).replaceAll('<', '\\u003c');
}

async function listProcessedImages(vehicleId) {
  const images = [];
  const objects = minioClient.listObjects(PROCESSED_BUCKET, `${vehicleId}/processed-`, false);

  for await (const object of objects) {
    const fileName = object.name.split('/').pop();
    const match = /^processed-(\d+)\.jpg$/.exec(fileName);
    const index = match ? parsePhotoIndex(match[1], config.processing.targetFrames) : null;
    if (index !== null) {
      const version = encodeURIComponent(
        object.etag || object.lastModified?.getTime?.() || 'current',
      );
      images.push({
        index,
        preview: `/viewer/${vehicleId}/image/preview-${index}.jpg?v=${version}`,
        hd: `/viewer/${vehicleId}/image/processed-${index}.jpg?v=${version}`,
      });
    }
  }

  return images.sort((left, right) => left.index - right.index);
}

router.get('/viewer/:vehicleId', async (req, res) => {
  try {
    const vehicleId = normalizeVehicleId(req.params.vehicleId);
    if (!vehicleId) return res.status(400).send('Invalid vehicle ID');

    const images = await listProcessedImages(vehicleId);
    const session = await sessionService.getSession(vehicleId);
    const qualityNeedsReview = session?.qualityScore !== null
      && session?.qualityScore !== undefined
      && session.qualityScore < 68;
    const nonce = crypto.randomBytes(18).toString('base64');
    const publicBaseUrl = config.baseUrl.replace(/\/$/, '');
    const canonicalUrl = `${publicBaseUrl}/viewer/${vehicleId}`;
    res.set('Content-Security-Policy', [
      "default-src 'self'",
      "img-src 'self' data:",
      "style-src 'unsafe-inline'",
      `script-src 'nonce-${nonce}'`,
      "connect-src 'self'",
      "frame-ancestors *",
      "base-uri 'none'",
      "form-action 'none'",
    ].join('; '));
    res.set('Referrer-Policy', 'strict-origin-when-cross-origin');
    return res.send(renderViewer({
      vehicleId: escapeHtml(vehicleId),
      imageSources: images.map(({ preview, hd }) => ({ preview, hd })),
      nonce,
      canonicalUrl: escapeHtml(canonicalUrl),
      socialImageUrl: escapeHtml(`${publicBaseUrl}/viewer/${vehicleId}/image/processed-1.jpg`),
      qualityNeedsReview,
      qualityLabel: qualityNeedsReview ? 'Minőségellenőrzés szükséges' : 'Ellenőrzött képsorozat',
    }));
  } catch (error) {
    console.error('Viewer generation failed:', error);
    return res.status(500).send('A bemutató átmenetileg nem érhető el.');
  }
});

router.get('/viewer/:vehicleId/image/:filename', async (req, res) => {
  try {
    const vehicleId = normalizeVehicleId(req.params.vehicleId);
    const match = /^(processed|preview)-(\d+)\.jpg$/.exec(req.params.filename);
    const photoIndex = match ? parsePhotoIndex(match[2], config.processing.targetFrames) : null;
    if (!vehicleId || photoIndex === null) return res.status(400).end();

    const variant = match[1];
    const objectKey = `${vehicleId}/${variant}-${photoIndex}.jpg`;
    const stats = await minioClient.statObject(PROCESSED_BUCKET, objectKey);
    if (req.get('if-none-match') === stats.etag) return res.status(304).end();

    res.set({
      'Content-Type': 'image/jpeg',
      'Content-Length': stats.size,
      'Cache-Control': 'public, max-age=300, stale-while-revalidate=3600',
      ETag: stats.etag,
    });
    const stream = await minioClient.getObject(PROCESSED_BUCKET, objectKey);
    stream.on('error', (error) => {
      console.error('Viewer image stream failed:', error);
      if (!res.headersSent) res.status(500).end();
      else res.destroy(error);
    });
    return stream.pipe(res);
  } catch (error) {
    if (error.code === 'NoSuchKey' || error.code === 'NotFound') return res.status(404).end();
    console.error('Viewer image failed:', error);
    return res.status(500).end();
  }
});

router.get('/embed.js', (req, res) => {
  const configuredBase = config.baseUrl.replace(/\/$/, '');
  res.type('application/javascript');
  res.set('Cache-Control', 'public, max-age=3600');
  return res.send(`(() => {
    const baseUrl = ${safeJson(configuredBase)};
    document.querySelectorAll('[data-vs360-vehicle]').forEach((container) => {
      if (container.dataset.vs360Ready) return;
      const vehicleId = container.getAttribute('data-vs360-vehicle');
      if (!/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/.test(vehicleId || '')) return;
      const iframe = document.createElement('iframe');
      iframe.src = baseUrl + '/viewer/' + encodeURIComponent(vehicleId);
      iframe.title = '360° járműbemutató – ' + vehicleId;
      iframe.loading = 'lazy';
      iframe.allowFullscreen = true;
      iframe.style.cssText = 'width:100%;height:min(72vw,720px);min-height:420px;border:0;border-radius:18px;overflow:hidden;background:#0a0c0d';
      container.replaceChildren(iframe);
      container.dataset.vs360Ready = 'true';
    });
  })();`);
});

function renderViewer({
  vehicleId,
  imageSources,
  nonce,
  canonicalUrl,
  socialImageUrl,
  qualityNeedsReview = false,
  qualityLabel = 'Ellenőrzött képsorozat',
}) {
  return `<!doctype html>
<html lang="hu">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
  <meta name="theme-color" content="#090b0c">
  <meta name="description" content="${vehicleId} interaktív, 36 nézetes járműbemutatója.">
  <meta property="og:type" content="website">
  <meta property="og:title" content="${vehicleId} · 360° bemutató">
  <meta property="og:description" content="Forgasd körbe és nézd meg közelről a járművet.">
  <meta property="og:url" content="${canonicalUrl}">
  <meta property="og:image" content="${socialImageUrl}">
  <link rel="canonical" href="${canonicalUrl}">
  <title>${vehicleId} · 360° bemutató</title>
  <style>
    :root{color-scheme:dark;font-family:Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;--accent:#b8f15a;--ink:#f4f6f5;--muted:#8e9893}
    *{box-sizing:border-box}html,body{margin:0;min-width:320px;min-height:100%;background:#090b0c;color:var(--ink);overflow:hidden}button,input{font:inherit}button:focus-visible,input:focus-visible,.stage:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
    .shell{height:100dvh;display:grid;grid-template-rows:auto minmax(0,1fr) auto;padding:max(18px,env(safe-area-inset-top)) max(18px,env(safe-area-inset-right)) max(16px,env(safe-area-inset-bottom)) max(18px,env(safe-area-inset-left));background:radial-gradient(circle at 50% -15%,rgba(184,241,90,.08),transparent 36%),#090b0c}
    header{height:58px;display:flex;align-items:flex-start;justify-content:space-between;gap:18px}.brand{display:flex;align-items:center;gap:10px;font-size:12px;font-weight:750;letter-spacing:.02em}.mark{width:32px;height:32px;display:grid;place-items:center;color:#11170a;background:var(--accent);border-radius:10px}.brand span:last-child{display:grid;gap:2px}.brand small{color:var(--muted);font-size:9px;font-weight:650;letter-spacing:.11em;text-transform:uppercase}.badge{padding:8px 11px;border:1px solid rgba(255,255,255,.1);border-radius:999px;color:#cbd1ce;background:rgba(255,255,255,.035);font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase}
    .stage{position:relative;min-height:0;overflow:hidden;border:1px solid rgba(255,255,255,.1);border-radius:24px;background:linear-gradient(180deg,#edece9,#d9d9d5);box-shadow:0 28px 90px rgba(0,0,0,.42);touch-action:none;user-select:none;cursor:grab}.stage.grabbing{cursor:grabbing}.stage:fullscreen{border:0;border-radius:0}.frame{position:absolute;inset:0;display:grid;place-items:center;overflow:hidden}.frame img{position:absolute;width:100%;height:100%;object-fit:contain;opacity:0;transform-origin:center;pointer-events:none;will-change:transform,opacity}.frame img.active{opacity:1}
    .loading{position:absolute;z-index:20;inset:0;display:grid;place-items:center;background:linear-gradient(180deg,#e8e7e4,#d9d9d5);color:#282d2a;transition:opacity .35s}.loading.hidden{opacity:0;pointer-events:none}.loading-inner{text-align:center}.spinner{width:40px;height:40px;margin:0 auto 15px;border:2px solid rgba(0,0,0,.12);border-top-color:#1e2521;border-radius:50%;animation:spin .8s linear infinite}.loading strong{display:block;font-size:13px}.loading small{display:block;margin-top:5px;color:#68706c;font-size:10px}
    .empty{position:absolute;z-index:21;inset:0;display:none;place-items:center;text-align:center;color:#222824;padding:30px}.empty.visible{display:grid}.empty-icon{width:54px;height:54px;margin:0 auto 16px;display:grid;place-items:center;border:1px solid rgba(0,0,0,.13);border-radius:16px;font-size:24px}.empty h1{margin:0 0 8px;font-size:24px;letter-spacing:-.04em}.empty p{max-width:360px;margin:0;color:#68706c;font-size:12px;line-height:1.55}.empty small{display:block;margin-top:12px;color:#858d89;font-size:9px}
    .hint{position:absolute;z-index:8;left:50%;bottom:58px;transform:translateX(-50%);display:flex;align-items:center;gap:8px;padding:9px 13px;color:#303632;background:rgba(255,255,255,.76);border:1px solid rgba(0,0,0,.07);border-radius:999px;box-shadow:0 5px 22px rgba(0,0,0,.09);backdrop-filter:blur(10px);font-size:10px;font-weight:750;white-space:nowrap;transition:opacity .35s}.hint.hidden{opacity:0;pointer-events:none}.hint i{font-style:normal;font-size:15px}
    .controls{position:absolute;z-index:10;top:15px;right:15px;display:grid;gap:7px}.controls button{width:38px;height:38px;display:grid;place-items:center;border:1px solid rgba(0,0,0,.08);border-radius:11px;color:#242a26;background:rgba(255,255,255,.76);backdrop-filter:blur(10px);cursor:pointer;font-size:15px;font-weight:750;transition:transform .16s,background .16s}.controls button:disabled{opacity:.3;cursor:default}.controls button[aria-pressed="true"]{color:#11170a;background:var(--accent)}
    .timeline{position:absolute;z-index:9;left:50%;bottom:17px;transform:translateX(-50%);width:min(66%,520px);height:28px;display:flex;align-items:center;padding:0 11px;background:rgba(255,255,255,.7);border:1px solid rgba(0,0,0,.08);border-radius:999px;backdrop-filter:blur(10px)}.timeline input{width:100%;height:3px;margin:0;accent-color:#28322c;cursor:ew-resize}.toast{position:absolute;z-index:12;top:16px;left:50%;transform:translate(-50%,-12px);padding:9px 12px;color:#202621;background:rgba(255,255,255,.9);border-radius:999px;box-shadow:0 8px 30px rgba(0,0,0,.12);font-size:10px;font-weight:750;opacity:0;pointer-events:none;transition:.2s}.toast.visible{opacity:1;transform:translate(-50%,0)}
    footer{height:62px;padding-top:17px;display:flex;align-items:flex-end;justify-content:space-between;gap:18px;color:var(--muted);font-size:10px}.vehicle{min-width:0;display:grid;gap:3px}.vehicle small{font-size:8px;font-weight:750;letter-spacing:.12em;text-transform:uppercase}.vehicle strong{overflow:hidden;text-overflow:ellipsis;color:#dfe4e1;font-size:12px;letter-spacing:.02em}.counter{font-variant-numeric:tabular-nums;font-weight:750}.counter b{color:var(--accent);font-weight:800}.quality{display:flex;align-items:center;gap:7px}.quality span{width:6px;height:6px;border-radius:50%;background:var(--accent);box-shadow:0 0 9px var(--accent)}.quality.review{color:#e8b75d}.quality.review span{background:#e8b75d;box-shadow:0 0 9px #e8b75d}
    @keyframes spin{to{transform:rotate(360deg)}}
    @media(hover:hover){.controls button:hover:not(:disabled){transform:translateY(-1px);background:white}}
    @media(max-width:600px){.shell{padding:12px}.stage{border-radius:18px}header{height:52px}.badge{display:none}.hint{bottom:54px}.controls{top:10px;right:10px}.controls button{width:36px;height:36px}.timeline{bottom:13px;width:74%}footer{height:55px}.quality{display:none}}
    @media(prefers-reduced-motion:reduce){*{animation-duration:.01ms!important;animation-iteration-count:1!important;scroll-behavior:auto!important}}
  </style>
</head>
<body>
  <main class="shell">
    <header>
      <div class="brand"><span class="mark">360°</span><span>VehicleShoot<small>Interactive presentation</small></span></div>
      <div class="badge">36 nézet · adaptív HD</div>
    </header>
    <section class="stage" id="stage" aria-label="Forgatható és nagyítható 360 fokos járműbemutató" tabindex="0">
      <div class="frame" id="frame"></div>
      <div class="loading" id="loading"><div class="loading-inner"><div class="spinner"></div><strong>Bemutató betöltése</strong><small id="loadingText">Első nézet előkészítése</small></div></div>
      <div class="empty" id="empty"><div><div class="empty-icon">↻</div><h1>A bemutató készül</h1><p>A képek feldolgozása még folyamatban van. Az oldal automatikusan megnyílik, amikor elkészült.</p><small>Állapot ellenőrzése…</small></div></div>
      <div class="hint" id="hint"><i>↔</i> Húzd oldalra · csippents a nagyításhoz</div>
      <div class="toast" id="toast" role="status" aria-live="polite"></div>
      <div class="controls">
        <button type="button" id="play" title="Automatikus forgatás" aria-label="Automatikus forgatás" aria-pressed="false">▶</button>
        <button type="button" id="zoomIn" title="Nagyítás" aria-label="Nagyítás">＋</button>
        <button type="button" id="zoomOut" title="Kicsinyítés" aria-label="Kicsinyítés" disabled>−</button>
        <button type="button" id="reset" title="Nézet visszaállítása" aria-label="Nézet visszaállítása">↺</button>
        <button type="button" id="share" title="Megosztás" aria-label="Bemutató megosztása">↗</button>
        <button type="button" id="fullscreen" title="Teljes képernyő" aria-label="Teljes képernyő">⛶</button>
      </div>
      <label class="timeline" aria-label="Nézet kiválasztása"><input id="scrubber" type="range" min="0" max="${Math.max(imageSources.length - 1, 0)}" value="0" step="1"></label>
    </section>
    <footer>
      <div class="vehicle"><small>Jármű</small><strong>${vehicleId}</strong></div>
      <div class="counter" aria-live="polite"><b id="current">01</b> / ${String(imageSources.length).padStart(2, '0')}</div>
      <div class="quality${qualityNeedsReview ? ' review' : ''}"><span></span> ${escapeHtml(qualityLabel)}</div>
    </footer>
  </main>
  <script nonce="${nonce}">
    (() => {
      const sources=${safeJson(imageSources)};
      const stage=document.getElementById('stage');
      const frame=document.getElementById('frame');
      const loading=document.getElementById('loading');
      const loadingText=document.getElementById('loadingText');
      const empty=document.getElementById('empty');
      const hint=document.getElementById('hint');
      const toast=document.getElementById('toast');
      const current=document.getElementById('current');
      const playButton=document.getElementById('play');
      const zoomIn=document.getElementById('zoomIn');
      const zoomOut=document.getElementById('zoomOut');
      const resetButton=document.getElementById('reset');
      const shareButton=document.getElementById('share');
      const fullscreen=document.getElementById('fullscreen');
      const scrubber=document.getElementById('scrubber');
      const reducedMotion=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      const images=[];
      const loaded=new Set();
      const pointers=new Map();
      let index=0,desiredIndex=0,rotation=0,zoom=1,panX=0,panY=0,velocity=0;
      let lastX=0,lastY=0,pinchDistance=0,autoplay=!reducedMotion,lastFrame=performance.now(),toastTimer;

      function flash(message){window.clearTimeout(toastTimer);toast.textContent=message;toast.classList.add('visible');toastTimer=window.setTimeout(()=>toast.classList.remove('visible'),1800)}
      function setAutoplay(next){autoplay=Boolean(next)&&!reducedMotion;playButton.textContent=autoplay?'Ⅱ':'▶';playButton.setAttribute('aria-pressed',String(autoplay))}
      function interact(){setAutoplay(false);hint.classList.add('hidden')}
      function normalize(next){return ((next%sources.length)+sources.length)%sources.length}
      function clampPan(){const maxX=stage.clientWidth*(zoom-1)/2,maxY=stage.clientHeight*(zoom-1)/2;panX=Math.max(-maxX,Math.min(maxX,panX));panY=Math.max(-maxY,Math.min(maxY,panY))}
      function applyTransform(){clampPan();images.forEach(img=>{img.style.transform='translate('+panX+'px,'+panY+'px) scale('+zoom+')'})}
      function upgrade(position){if(!sources[position]||images[position].dataset.hd==='true')return;const high=new Image();high.onload=()=>{images[position].src=sources[position].hd;images[position].dataset.hd='true'};high.src=sources[position].hd}
      function show(next){
        if(!sources.length)return;
        desiredIndex=normalize(next);
        if(!loaded.has(desiredIndex)){loadPreview(desiredIndex);return}
        index=desiredIndex;
        images.forEach((img,i)=>img.classList.toggle('active',i===index));
        current.textContent=String(index+1).padStart(2,'0');scrubber.value=String(index);
        upgrade(index);upgrade(normalize(index-1));upgrade(normalize(index+1));
      }
      function markLoaded(position){if(loaded.has(position))return;loaded.add(position);loadingText.textContent=loaded.size+' / '+sources.length+' gyorsnézet';if(loaded.size===1){show(desiredIndex);loading.classList.add('hidden')}if(loaded.size===sources.length)loading.classList.add('hidden')}
      function loadPreview(position){
        const img=images[position];if(!img||img.dataset.started==='true')return;img.dataset.started='true';
        img.onload=()=>{markLoaded(position);if(position===desiredIndex)show(position)};
        img.onerror=()=>{if(img.dataset.fallback!=='true'){img.dataset.fallback='true';img.dataset.hd='true';img.src=sources[position].hd}else markLoaded(position)};
        img.src=sources[position].preview;
      }
      function loadImages(){
        sources.forEach((source,i)=>{const img=new Image();img.alt='${vehicleId} – '+(i+1)+'. nézet';img.draggable=false;img.decoding='async';images.push(img);frame.appendChild(img)});
        [0,1,sources.length-1,2,sources.length-2].forEach(position=>{if(position>=0)loadPreview(position)});
        const loadRest=()=>sources.forEach((_,i)=>window.setTimeout(()=>loadPreview(i),i*18));
        if('requestIdleCallback' in window)window.requestIdleCallback(loadRest,{timeout:700});else window.setTimeout(loadRest,120);
      }
      function setZoom(next){zoom=Math.max(1,Math.min(4,next));if(zoom===1){panX=0;panY=0}zoomOut.disabled=zoom===1;applyTransform()}
      function resetView(){interact();rotation=index;setZoom(1);show(index);flash('Nézet visszaállítva')}
      function pointerDistance(){const values=[...pointers.values()];return values.length<2?0:Math.hypot(values[0].x-values[1].x,values[0].y-values[1].y)}

      if(!sources.length){
        loading.classList.add('hidden');empty.classList.add('visible');[playButton,zoomIn,zoomOut,resetButton,shareButton,scrubber].forEach(control=>control.disabled=true);
        const poll=window.setInterval(async()=>{try{const response=await fetch('/api/sessions/${vehicleId}',{cache:'no-store'});if(response.ok&&(await response.json()).status==='completed'){window.clearInterval(poll);location.reload()}}catch{}},7000);
        return;
      }

      stage.addEventListener('pointerdown',event=>{if(event.target.closest('button,input'))return;pointers.set(event.pointerId,{x:event.clientX,y:event.clientY});stage.setPointerCapture(event.pointerId);lastX=event.clientX;lastY=event.clientY;velocity=0;stage.classList.add('grabbing');interact();if(pointers.size===2)pinchDistance=pointerDistance()});
      stage.addEventListener('pointermove',event=>{
        if(!pointers.has(event.pointerId))return;
        pointers.set(event.pointerId,{x:event.clientX,y:event.clientY});
        if(pointers.size>=2){const distance=pointerDistance();if(pinchDistance>0)setZoom(zoom*distance/pinchDistance);pinchDistance=distance;return}
        const dx=event.clientX-lastX,dy=event.clientY-lastY;
        if(zoom===1){rotation+=dx/16;velocity=dx/16;show(Math.round(rotation))}else{panX+=dx;panY+=dy;applyTransform()}
        lastX=event.clientX;lastY=event.clientY;
      });
      function release(event){pointers.delete(event.pointerId);if(pointers.size<2)pinchDistance=0;if(!pointers.size)stage.classList.remove('grabbing');else{const point=[...pointers.values()][0];lastX=point.x;lastY=point.y}}
      stage.addEventListener('pointerup',release);stage.addEventListener('pointercancel',release);
      stage.addEventListener('wheel',event=>{event.preventDefault();interact();setZoom(zoom+(event.deltaY<0?.25:-.25))},{passive:false});
      stage.addEventListener('dblclick',()=>{interact();setZoom(zoom>1?1:2)});
      stage.addEventListener('keydown',event=>{
        if(event.target===scrubber)return;
        if(event.key==='ArrowRight'||event.key==='ArrowLeft'){event.preventDefault();interact();rotation+=event.key==='ArrowRight'?1:-1;show(Math.round(rotation))}
        else if(event.key==='+'||event.key==='='){event.preventDefault();interact();setZoom(zoom+.35)}
        else if(event.key==='-'){event.preventDefault();interact();setZoom(zoom-.35)}
        else if(event.key==='Home'){event.preventDefault();resetView()}
        else if(event.key===' '){event.preventDefault();setAutoplay(!autoplay)}
      });
      playButton.addEventListener('click',()=>{setAutoplay(!autoplay);hint.classList.add('hidden')});
      zoomIn.addEventListener('click',()=>{interact();setZoom(zoom+.35)});zoomOut.addEventListener('click',()=>{interact();setZoom(zoom-.35)});
      resetButton.addEventListener('click',resetView);
      scrubber.addEventListener('input',event=>{interact();rotation=Number(event.target.value);show(rotation)});
      shareButton.addEventListener('click',async()=>{try{if(navigator.share)await navigator.share({title:document.title,url:location.href});else{await navigator.clipboard.writeText(location.href);flash('Link a vágólapra másolva')}}catch(error){if(error.name!=='AbortError')flash('A megosztás nem sikerült')}});
      fullscreen.addEventListener('click',()=>{if(document.fullscreenElement)document.exitFullscreen();else stage.requestFullscreen?.()});
      window.addEventListener('resize',applyTransform);
      function animate(now){const dt=Math.min(now-lastFrame,40);lastFrame=now;if(!pointers.size&&zoom===1&&document.visibilityState==='visible'){if(autoplay&&loaded.size>=5)velocity=.00075*dt;else velocity*=.91;if(Math.abs(velocity)>.002){rotation+=velocity;show(Math.round(rotation))}}requestAnimationFrame(animate)}
      if(sources.length<${config.processing.targetFrames}){const completionPoll=window.setInterval(async()=>{try{const response=await fetch('/api/sessions/${vehicleId}',{cache:'no-store'});if(response.ok&&(await response.json()).status==='completed'){window.clearInterval(completionPoll);location.reload()}}catch{}},7000)}
      loadImages();setAutoplay(autoplay);requestAnimationFrame(animate);window.setTimeout(()=>hint.classList.add('hidden'),5500);
    })();
  </script>
</body>
</html>`;
}

module.exports = router;
module.exports.renderViewer = renderViewer;
