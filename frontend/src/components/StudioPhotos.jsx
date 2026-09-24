import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, Download, LoaderCircle, Sparkles } from 'lucide-react';
import { generateStudioPhotos, getStudioPhotos, studioPhotoUrl } from '../api/uploader';

export default function StudioPhotos() {
  const { vehicleId } = useParams();
  const navigate = useNavigate();
  const [result, setResult] = useState({ status: 'loading', completed: 0, total: 10 });
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    const refresh = async () => {
      try {
        const next = await getStudioPhotos(vehicleId);
        if (active) { setResult(next); setError(''); }
      } catch (requestError) {
        if (active) setError(requestError.message);
      }
    };
    refresh();
    const timer = window.setInterval(refresh, 3000);
    return () => { active = false; window.clearInterval(timer); };
  }, [vehicleId]);

  const start = async () => {
    setError('');
    try { setResult(await generateStudioPhotos(vehicleId)); }
    catch (requestError) { setError(requestError.message); }
  };

  return <main className="dashboard-shell studio-export-page">
    <header className="dashboard-header">
      <div>
        <button className="back-link" onClick={() => navigate('/dashboard')}><ArrowLeft size={16} /> Projektek</button>
        <p className="eyebrow">Önálló képexport</p>
        <h1>10 Studio Photos</h1>
        <p>{vehicleId} · 10 körben elosztott, 3840 × 2160 képpontos stúdiófotó</p>
      </div>
      {result.status === 'ready' && <a className="button button-primary" href={studioPhotoUrl(vehicleId, 'album.zip', result.generatedAt)}>
        <Download size={18} /> Mind a 10 letöltése
      </a>}
    </header>
    <section className="studio-export-intro">
      <Sparkles size={27} />
      <div><h2>Különálló fotók az autóról</h2><p>A 36 nézetes interaktív bemutató mellett készülő, egyenként felhasználható, letisztult stúdióképek.</p></div>
    </section>
    {result.status === 'ready' && result.photos?.some(photo => photo.angleSource !== 'sensor') &&
      <p className="studio-export-note">Szenzoros irányadat nélkül a jelölt szögek közelítő értékek; a rendszer minden irányból a legjobb használható képet választja.</p>}
    {error && <p className="dashboard-alert">{error}</p>}
    {result.status === 'failed' && <p className="dashboard-alert">{result.error || 'Az export sikertelen volt. Újraindíthatod.'}</p>}
    {(result.status === 'not_started' || result.status === 'failed') &&
      <button className="button button-primary" onClick={start}><Sparkles size={18} /> 10 stúdiófotó elkészítése</button>}
    {(result.status === 'loading' || result.status === 'processing') &&
      <p className="studio-export-progress"><LoaderCircle className="spin" size={20} />
        {result.status === 'loading' ? 'Állapot betöltése…' : `Képek készítése: ${result.completed || 0} / 10`}</p>}
    {result.status === 'ready' && <div className="studio-photo-grid">
      {(result.photos || Array.from({ length: 10 }, (_, index) => ({ number: index+1, file: `${String(index+1).padStart(2, '0')}.jpg`, degrees: index*36 }))).map(photo =>
        <article className="studio-photo-card" key={photo.number}>
          <img src={studioPhotoUrl(vehicleId, photo.file, result.generatedAt)} alt={`${vehicleId} – ${photo.degrees} fokos stúdiófotó`} loading="lazy" />
          <div><span>{String(photo.number).padStart(2, '0')} · {photo.angleSource === 'sensor' ? '' : '≈'}{photo.degrees}°</span>
            <a href={studioPhotoUrl(vehicleId, photo.file, result.generatedAt)} download><Download size={16} /> Letöltés</a></div>
        </article>)}</div>}
  </main>;
}
