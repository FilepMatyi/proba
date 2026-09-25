export const SECTOR_COUNT = 10;
export const CAPTURE_SETTINGS = {
  normalWindow: 18, heroWindow: 26, stableMs: 600,
  adaptiveAfterMs: 5000, fallbackSectorMs: 3200, minBetweenMs: 1200,
  comfortableRoll: 6, warningRoll: 12,
};

const clamp = (value) => Math.max(0, Math.min(1, value));
const signedAngle = (value) => ((value + 540) % 360) - 180;

export function smoothOrientation(previous, sample, factor = 0.22) {
  if (!sample || !Number.isFinite(sample.heading)) return previous;
  if (!previous) return { ...sample };
  return {
    heading: (previous.heading + factor * signedAngle(sample.heading - previous.heading) + 360) % 360,
    beta: Number.isFinite(sample.beta) ? previous.beta + factor * (sample.beta - previous.beta) : previous.beta,
    gamma: Number.isFinite(sample.gamma) ? previous.gamma + factor * (sample.gamma - previous.gamma) : previous.gamma,
  };
}

export function evaluateQuality(sample, settings = CAPTURE_SETTINGS, relaxed = false) {
  if (!sample.landscape) return { grade: 'red', instruction: 'FORDÍTSD VÍZSZINTESRE A TELEFONT', score: 0, critical: true };
  const box = sample.vehicleBox;
  if (box) {
    const margin = Math.min(box.x, box.y, 1-box.x-box.width, 1-box.y-box.height);
    if (margin < 0.035 || box.width > 0.86 || box.height > 0.81) {
      return { grade: 'red', instruction: 'LÉPJ KICSIT HÁTRÉBB', score: 0, critical: true };
    }
    if (box.width < 0.35) return { grade: 'yellow', instruction: 'LÉPJ KICSIT KÖZELEBB', score: .45, critical: false };
  }
  const roll = Math.abs(sample.roll ?? 0);
  if (roll > settings.warningRoll) return { grade: 'red', instruction: 'TARTSD EGYENESEBBEN', score: .2, critical: true };
  if (sample.exposureScore < .22) return { grade: 'red', instruction: 'KERESS EGYENLETESEBB FÉNYT', score: .2, critical: true };
  if (sample.sharpnessScore < .18) return { grade: 'red', instruction: 'TARTSD STABILAN', score: .2, critical: true };
  const score = clamp(.36*sample.sharpnessScore + .25*sample.exposureScore
    + .31*sample.stabilityScore + .08*(1-clamp(roll/20)));
  if (sample.stabilityScore < .32) return { grade: 'yellow', instruction: 'TARTSD STABILAN', score, critical: false };
  if (roll > settings.comfortableRoll + (relaxed ? 2 : 0)) {
    return { grade: 'yellow', instruction: 'TARTSD EGYENESEBBEN', score, critical: false };
  }
  if (sample.exposureScore < .42 || sample.sharpnessScore < (relaxed ? .29 : .37)) {
    return { grade: 'yellow', instruction: 'TARTSD STABILAN', score, critical: false };
  }
  return { grade: 'green', instruction: 'TARTSD STABILAN', score, critical: false };
}

export function initialCaptureState(now = 0, retakeSector = null) {
  return { captured: Array(SECTOR_COUNT).fill(false), nextSector: retakeSector || 1,
    retakeSector, startedAt: now, sectorStartedAt: now, lastCaptureAt: -Infinity,
    firstHeading: null, lastHeading: null, unwrapped: 0, direction: null,
    maxProgress: 0, greenSince: null, candidateHistory: [], phase: 'waiting',
    lastCaptureProgress: 0,
    instruction: 'HELYEZD AZ AUTÓT A KERETBE', grade: 'yellow',
    retries: Array(SECTOR_COUNT).fill(0), instructions: {},
    orientationBase: null, completedAt: null };
}

export function captureTick(state, sample, settings = CAPTURE_SETTINGS) {
  if (state.phase === 'capturing' || state.phase === 'done') return { state, capture: false };
  const next = { ...state, candidateHistory: [...state.candidateHistory],
    retries: [...state.retries], instructions: { ...state.instructions } };
  if (Number.isFinite(sample.heading)) {
    if (next.firstHeading === null) {
      next.firstHeading = sample.heading;
      next.lastHeading = sample.heading;
    } else {
      const delta = signedAngle(sample.heading - next.lastHeading);
      if (Math.abs(delta) <= 40) {
        next.unwrapped += delta;
        next.lastHeading = sample.heading;
        if (next.direction === null && Math.abs(next.unwrapped) >= 8) {
          next.direction = Math.sign(next.unwrapped);
        }
        if (next.direction !== null) next.maxProgress = Math.max(next.maxProgress, next.unwrapped*next.direction);
      }
    }
  }
  if (sample.orientation && !next.orientationBase) next.orientationBase = sample.orientation;
  const sector = next.nextSector;
  const hero = [2, 4, 7, 9].includes(sector);
  const halfWindow = hero ? settings.heroWindow : settings.normalWindow;
  const sensorProgress = next.direction !== null && next.maxProgress >= 8;
  const target = (sector-1)*36;
  const elapsed = sample.time-next.sectorStartedAt;
  const progress = next.maxProgress;
  const zone = next.retakeSector !== null || sector === 1
    || (sensorProgress
      ? progress >= target-halfWindow && progress <= target+halfWindow+8
        && progress-next.lastCaptureProgress >= 20
      : sample.time-next.startedAt >= (sector-1)*settings.fallbackSectorMs);
  const relaxed = elapsed >= settings.adaptiveAfterMs;
  const quality = evaluateQuality(sample, settings, relaxed);
  const previousGrade = next.grade;
  next.grade = quality.grade;
  next.instruction = !zone ? 'HALADJ TOVÁBB' : quality.instruction;
  next.candidateHistory.push({ time: sample.time, score: quality.score, grade: quality.grade });
  next.candidateHistory = next.candidateHistory.filter((item) => sample.time-item.time <= 1600);
  next.instructions[next.instruction] = (next.instructions[next.instruction] || 0) + 1;
  if (!zone || quality.critical || sample.time-next.lastCaptureAt < settings.minBetweenMs) {
    next.greenSince = null;
    if (zone && quality.critical && previousGrade !== 'red') next.retries[sector-1] += 1;
    return { state: next, capture: false };
  }
  const acceptable = quality.grade === 'green' || (relaxed && quality.grade === 'yellow'
    && quality.score >= .45 && sample.stabilityScore >= .49);
  if (!acceptable) {
    next.greenSince = null;
    return { state: next, capture: false };
  }
  if (next.greenSince === null) next.greenSince = sample.time;
  if (sample.time-next.greenSince < settings.stableMs) return { state: next, capture: false };
  const recentBest = Math.max(...next.candidateHistory
    .filter((item) => sample.time-item.time <= 900).map((item) => item.score));
  if (quality.score < recentBest-.08 && sample.time-next.greenSince < settings.stableMs+450) {
    return { state: next, capture: false };
  }
  next.phase = 'capturing';
  next.instruction = 'FOTÓ KÉSZÜL';
  return { state: next, capture: true, quality };
}

export function confirmCapture(state, time) {
  const captured = [...state.captured];
  captured[state.nextSector-1] = true;
  const done = captured.every(Boolean);
  return { ...state, captured, phase: done ? 'done' : 'waiting',
    nextSector: state.retakeSector ?? Math.min(SECTOR_COUNT, state.nextSector+1),
    lastCaptureAt: time, sectorStartedAt: time, greenSince: null,
    lastCaptureProgress: state.maxProgress,
    candidateHistory: [], instructions: {}, completedAt: done ? time : null,
    instruction: done ? 'MIND A TÍZ KÉP ELKÉSZÜLT' : 'HALADJ TOVÁBB' };
}

export function retryCapture(state) {
  return { ...state, phase: 'waiting', greenSince: null, instruction: 'TARTSD STABILAN' };
}

export function beginRetake(state, sector, time) {
  if (!Number.isInteger(sector) || sector < 1 || sector > SECTOR_COUNT) throw new Error('Invalid sector');
  return { ...state, nextSector: sector, retakeSector: sector,
    sectorStartedAt: time, lastCaptureAt: -Infinity, greenSince: null,
    phase: 'waiting', instruction: 'TARTSD STABILAN' };
}
