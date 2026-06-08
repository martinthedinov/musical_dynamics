// Audio synthesis: Web Audio API for live playback, plus an offline render to .wav for the
// "rendered WAV" export. Note shape: { p, t, d, vel, role }.
let ac = null, master = null, delay = null, lpf = null;
let playing = false, voices = [];
const mtf = (m) => 440 * Math.pow(2, (m - 69) / 12);

function initAudio() {
  ac = new (window.AudioContext || window.webkitAudioContext)();
  master = ac.createGain(); master.gain.value = 0.78;
  lpf = ac.createBiquadFilter(); lpf.type = "lowpass"; lpf.frequency.value = 6500;
  master.connect(lpf); lpf.connect(ac.destination);
  delay = ac.createDelay(); delay.delayTime.value = 0.28;
  const fb = ac.createGain(); fb.gain.value = 0.30;
  const wet = ac.createGain(); wet.gain.value = 0.26;
  delay.connect(fb); fb.connect(delay); delay.connect(wet); wet.connect(lpf);
}

function voice(n, t0) {
  const a = ac.currentTime + t0 + n.t, freq = mtf(n.p);
  const g = ac.createGain();
  const lead = n.role === "lead" || n.role === "operand";
  const o = ac.createOscillator();
  o.type = n.role === "bass" ? "sine" : "triangle";
  o.frequency.value = freq;
  o.connect(g); g.connect(master); if (lead) g.connect(delay);
  const pk = (n.vel || 64) / 127 * (n.role === "bass" ? 0.16 : (lead ? 0.15 : 0.07));
  g.gain.setValueAtTime(0, a);
  g.gain.linearRampToValueAtTime(pk, a + (lead ? 0.006 : 0.05));
  if (!lead) g.gain.setValueAtTime(pk, a + n.d * 0.6);
  g.gain.exponentialRampToValueAtTime(0.0001, a + n.d + (lead ? 0.1 : 0.15));
  o.start(a); o.stop(a + n.d + 0.2);
  voices.push(o);
}

export async function playNotes(notes) {
  if (!ac) initAudio();
  if (ac.state === "suspended") await ac.resume();
  voices = [];
  playing = true;
  const total = Math.max(...notes.map(n => n.t + n.d), 0);
  for (const n of notes) voice(n, 0);
  // schedule the "stopped" flag flip
  setTimeout(() => { playing = false; }, (total + 0.3) * 1000);
}

export function stopAudio() {
  playing = false;
  if (ac) { try { ac.close(); } catch {} ac = null; voices = []; }
}

// ---------- offline render to a 16-bit PCM WAV blob ----------
export async function synthToWav(notes, { sr = 44100, stereo = true } = {}) {
  const total = Math.max(...notes.map(n => n.t + n.d), 0) + 0.4;
  const ch = stereo ? 2 : 1;
  const ctx = new OfflineAudioContext(ch, Math.ceil(total * sr), sr);
  const g = ctx.createGain(); g.gain.value = 0.5; g.connect(ctx.destination);
  const lp = ctx.createBiquadFilter(); lp.type = "lowpass"; lp.frequency.value = 6500;
  g.connect(lp); lp.connect(ctx.destination);
  for (const n of notes) {
    const o = ctx.createOscillator();
    o.type = n.role === "bass" ? "sine" : "triangle";
    o.frequency.value = mtf(n.p);
    const v = ctx.createGain();
    o.connect(v); v.connect(g);
    const pk = (n.vel || 64) / 127 * (n.role === "bass" ? 0.16 : (n.role === "lead" || n.role === "operand" ? 0.15 : 0.07));
    v.gain.setValueAtTime(0, n.t);
    v.gain.linearRampToValueAtTime(pk, n.t + 0.02);
    v.gain.setValueAtTime(pk, n.t + n.d * 0.6);
    v.gain.exponentialRampToValueAtTime(0.0001, n.t + n.d + 0.15);
    o.start(n.t); o.stop(n.t + n.d + 0.2);
  }
  const rendered = await ctx.startRendering();
  return audioBufferToWav(rendered);
}

function audioBufferToWav(buffer) {
  const ch = buffer.numberOfChannels, sr = buffer.sampleRate, len = buffer.length;
  const out = new Int16Array(len * ch);
  // interleave + convert float32 [-1,1] to int16
  for (let c = 0; c < ch; c++) {
    const data = buffer.getChannelData(c);
    for (let i = 0; i < len; i++) {
      const v = Math.max(-1, Math.min(1, data[i]));
      out[i * ch + c] = (v < 0 ? v * 0x8000 : v * 0x7FFF) | 0;
    }
  }
  const buf = new ArrayBuffer(44 + out.length * 2);
  const v = new DataView(buf);
  const w = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  w(0, "RIFF"); v.setUint32(4, 36 + out.length * 2, true);
  w(8, "WAVE"); w(12, "fmt ");
  v.setUint32(16, 16, true);
  v.setUint16(20, 1, true); v.setUint16(22, ch, true);
  v.setUint32(24, sr, true); v.setUint32(28, sr * ch * 2, true);
  v.setUint16(32, ch * 2, true); v.setUint16(34, 16, true);
  w(36, "data"); v.setUint32(40, out.length * 2, true);
  new Int16Array(buf, 44, out.length).set(out);
  return buf;
}
