// Standard MIDI File writer (Format 0, one track) — produces .mid that matches what mido reads.
// Used to export the realized notes from the player.

function vlq(n) {
  // variable-length quantity (used for delta-times)
  const bytes = [n & 0x7F]; n >>>= 7;
  while (n > 0) { bytes.unshift((n & 0x7F) | 0x80); n >>>= 7; }
  return bytes;
}
function u32be(n) { return [(n >>> 24) & 0xFF, (n >>> 16) & 0xFF, (n >>> 8) & 0xFF, n & 0xFF]; }
function u16be(n) { return [(n >>> 8) & 0xFF, n & 0xFF]; }

export function notesToMidi(notes, { bpm = 112, ticksPerBeat = 480 } = {}) {
  // Convert (p, t, d, vel, role, ch?) notes into an SMF byte array. Beats are seconds-per-beat
  // scaled by tempo; (t, d) are already in beats here (matching the realizer output).
  const events = [];                                       // {tick, kind, ch, note, vel}
  const channelOf = (role) => role === "operand" ? 1 : role === "bass" ? 2 : 0;
  for (const n of notes) {
    const start = Math.round(n.t * ticksPerBeat);
    const end   = Math.round((n.t + n.d) * ticksPerBeat);
    events.push({ tick: start, kind: 0x90, ch: channelOf(n.role), note: n.p | 0, vel: n.vel | 0 });
    events.push({ tick: end,   kind: 0x80, ch: channelOf(n.role), note: n.p | 0, vel: 0 });
  }
  // stable sort by (tick, note-on-after-note-off-at-same-tick)
  events.sort((a, b) => (a.tick - b.tick) || (a.kind - b.kind));
  // build track event stream
  const tr = [];
  // tempo meta
  const tempo = Math.round(60_000_000 / bpm);              // microseconds per quarter
  tr.push(...vlq(0), 0xFF, 0x51, 0x03, (tempo >> 16) & 0xFF, (tempo >> 8) & 0xFF, tempo & 0xFF);
  // program changes per channel (matching mc_codec.write_midi voices)
  const programs = { 0: 89, 1: 81, 2: 38 };
  for (const ch of [0, 1, 2]) tr.push(...vlq(0), 0xC0 | ch, programs[ch]);
  let last = 0;
  for (const e of events) {
    const dt = Math.max(0, e.tick - last); last = e.tick;
    tr.push(...vlq(dt), e.kind | e.ch, Math.max(0, Math.min(127, e.note)), Math.max(0, Math.min(127, e.vel)));
  }
  tr.push(...vlq(0), 0xFF, 0x2F, 0x00);                    // end-of-track meta
  // wrap into a Format-0 SMF
  const hdr = [
    0x4D, 0x54, 0x68, 0x64,                                // 'MThd'
    ...u32be(6), ...u16be(0), ...u16be(1), ...u16be(ticksPerBeat),
  ];
  const trkHdr = [0x4D, 0x54, 0x72, 0x6B, ...u32be(tr.length)];   // 'MTrk' + length
  return new Uint8Array([...hdr, ...trkHdr, ...tr]);
}

export function downloadMidi(notes, filename = "musical_dynamics.mid", opts = {}) {
  const bytes = notesToMidi(notes, opts);
  const blob = new Blob([bytes], { type: "audio/midi" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a"); a.href = url; a.download = filename; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 100);
}
