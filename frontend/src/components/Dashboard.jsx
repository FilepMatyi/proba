import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertTriangle, ArrowLeft, Camera, Check, Copy, ExternalLink, LoaderCircle, Rotate3D, ShieldCheck, Trash2 } from 'lucide-react';

import { deleteSession, getSessions } from '../api/uploader';

const STAGE_LABELS = {
  uploading: 'Feltöltés', extracting: 'Képkockák', selecting: 'Válogatás', composing: 'Stúdiófeldolgozás', ready: 'Elkészült', failed: 'Sikertelen',
};

function parseWarnings(value) {
  if (Array.isArray(value)) return value;
  try {
    const warnings = JSON.parse(value || '[]');
    return Array.isArray(warnings) ? warnings : [];
  } catch {
    return [];
  }
}

export default function Dashboard() {
  const navigate = useNavigate();
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [copiedId, setCopiedId] = useState(null);

  useEffect(() => {
    let active = true;
    const refresh = async () => {
      try {
        const data = await getSessions();
        if (active) {
          setSessions(data);
          setError('');
        }
      } catch (requestError) {
        if (active) setError(requestError.message);
      } finally {
        if (active) setLoading(false);
      }
    };
    refresh();
    const timer = window.setInterval(refresh, 5000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  const removeSession = async (vehicleId) => {
    if (!window.confirm(`Biztosan törlöd a(z) ${vehicleId} projektet?`)) return;
    try {
      await deleteSession(vehicleId);
      setSessions((items) => items.filter((item) => item.vehicleId !== vehicleId));
    } catch (requestError) {
      setError(requestError.message);
    }
  };

  const copyEmbedCode = async (vehicleId) => {
    const baseUrl = window.location.origin;
    const code = `<div data-vs360-vehicle="${vehicleId}"></div>\n<script src="${baseUrl}/embed.js"></script>`;
    try {
      await navigator.clipboard.writeText(code);
      setCopiedId(vehicleId);
      window.setTimeout(() => setCopiedId(null), 2000);
    } catch {
      setError('Az embed kód nem másolható automatikusan ezen az eszközön.');
    }
  };

  return (
    <main className="dashboard-shell">
      <header className="dashboard-header">
        <div>
          <button className="back-link" onClick={() => navigate('/')}><ArrowLeft size={16} /> Rögzítés</button>
          <p className="eyebrow">Kereskedői munkatér</p>
          <h1>360° bemutatók</h1>
          <p>{sessions.length} projekt · automatikus frissítés</p>
        </div>
        <button className="button button-primary" onClick={() => navigate('/')}><Camera size={18} /> Új autó</button>
      </header>

      {error && <div className="dashboard-alert"><AlertTriangle size={18} /> {error}</div>}

      {loading ? (
        <div className="dashboard-empty"><LoaderCircle className="spin" size={28} /><p>Projektek betöltése…</p></div>
      ) : sessions.length === 0 ? (
        <div className="dashboard-empty">
          <span><Rotate3D size={30} /></span>
          <h2>Az első bemutató rád vár</h2>
          <p>Egy rövid videóból 36 egységes, interaktív nézet készül.</p>
          <button className="button button-primary" onClick={() => navigate('/')}><Camera size={18} /> Első felvétel</button>
        </div>
      ) : (
        <section className="project-grid">
          {sessions.map((session) => {
            const progress = Math.round((session.processedFrames / session.totalFrames) * 100);
            const completed = session.status === 'completed';
            const failed = session.status === 'failed';
            const warnings = parseWarnings(session.qualityWarnings);
            const qualityTone = session.qualityScore >= 82 ? 'excellent' : session.qualityScore >= 68 ? 'good' : 'review';
            const qualityLabel = qualityTone === 'excellent' ? 'Kiváló' : qualityTone === 'good' ? 'Jó' : 'Ellenőrzendő';
            return (
              <article className="project-card" key={session.vehicleId}>
                <div className="project-card-top">
                  <div className={`project-status ${completed ? 'complete' : failed ? 'failed' : ''}`}>
                    {completed ? <Check size={15} /> : failed ? <AlertTriangle size={15} /> : <LoaderCircle className="spin" size={15} />}
                    {STAGE_LABELS[session.stage] || 'Feldolgozás'}
                  </div>
                  <button className="icon-button danger" onClick={() => removeSession(session.vehicleId)} aria-label={`${session.vehicleId} törlése`}><Trash2 size={16} /></button>
                </div>
                <h2>{session.vehicleId}</h2>
                <p className="project-date">{new Intl.DateTimeFormat('hu-HU', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(session.createdAt))}</p>

                {session.qualityScore !== null && session.qualityScore !== undefined && (
                  <div className={`quality-report ${qualityTone}`} title={warnings.join('\n')}>
                    <ShieldCheck size={16} />
                    <span><small>Automatikus képminőség</small>{qualityLabel}</span>
                    <strong>{session.qualityScore}<small>/100</small></strong>
                  </div>
                )}
                {completed && warnings.length > 0 && (
                  <p className="quality-warning"><AlertTriangle size={13} /> {warnings[0]}</p>
                )}

                <div className="project-progress">
                  <div><span>{completed ? '36 nézet kész' : failed ? 'Feldolgozás megállt' : `${session.processedFrames} / ${session.totalFrames} kép`}</span><b>{failed ? '!' : `${progress}%`}</b></div>
                  <div className={`progress-track ${failed ? 'progress-failed' : ''}`}><span style={{ width: `${failed ? 100 : progress}%` }} /></div>
                </div>

                <div className="project-actions">
                  <button className="button button-secondary" onClick={() => copyEmbedCode(session.vehicleId)} disabled={!completed}>
                    {copiedId === session.vehicleId ? <Check size={16} /> : <Copy size={16} />}
                    {copiedId === session.vehicleId ? 'Másolva' : 'Embed'}
                  </button>
                  {completed && <a className="button button-primary" href={`/viewer/${session.vehicleId}`} target="_blank" rel="noreferrer">Megnyitás <ExternalLink size={16} /></a>}
                </div>
              </article>
            );
          })}
        </section>
      )}
    </main>
  );
}
