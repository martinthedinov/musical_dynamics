// MusicXML 4.0 exporter — produces an engravable score that opens in MuseScore, Finale, etc.
// Treats the program as a stream of chord events at the realized timings. Each chord becomes a
// <note><chord/> group; operand and lead voices go to separate <voice>s on the same staff.

const STEP = ["C","C","D","D","E","F","F","G","G","A","A","B"];
const ALT  = [ 0,   1,  0,  1,  0,  0,  1,  0,  1,  0,  1,  0];
const _esc = (s) => String(s).replace(/[<>&"]/g, c => ({"<":"&lt;",">":"&gt;","&":"&amp;",'"':"&quot;"}[c]));

function pitchEl(midi) {
  const oct = Math.floor(midi / 12) - 1;
  const c = midi % 12;
  const alt = ALT[c] ? "<alter>1</alter>" : "";
  return `<pitch><step>${STEP[c]}</step>${alt}<octave>${oct}</octave></pitch>`;
}

export function notesToMusicXML(notes, { divisions = 8, title = "Musical Dynamics", composer = "MD player" } = {}) {
  // Group notes by onset time, then by role (each role -> its own voice).
  const onsets = new Map();
  for (const n of notes) {
    const key = Math.round(n.t * divisions);
    if (!onsets.has(key)) onsets.set(key, { t: n.t, byRole: { pad: [], operand: [], lead: [], bass: [] } });
    (onsets.get(key).byRole[n.role] ||= []).push(n);
  }
  const keys = [...onsets.keys()].sort((a, b) => a - b);
  // we treat the whole piece as one big measure for simplicity
  let measureBody = "";
  let prev = 0;
  for (let i = 0; i < keys.length; i++) {
    const onset = onsets.get(keys[i]);
    const dur = Math.max(1, Math.round(((keys[i + 1] ?? (keys[i] + divisions)) - keys[i])));
    // emit voice 1 = pad chord (the opcode), voice 2 = operand notes if any, voice 3 = lead/print melody
    const voices = [];
    if (onset.byRole.pad.length)      voices.push(["1", onset.byRole.pad]);
    if (onset.byRole.operand.length)  voices.push(["2", onset.byRole.operand]);
    if (onset.byRole.lead.length)     voices.push(["3", onset.byRole.lead]);
    if (!voices.length) continue;
    let first = true;
    for (const [voice, group] of voices) {
      if (!first) measureBody += `<backup><duration>${dur}</duration></backup>`;
      first = false;
      const sorted = [...group].sort((a, b) => a.p - b.p);
      sorted.forEach((n, idx) => {
        measureBody += `<note>${idx > 0 ? "<chord/>" : ""}${pitchEl(n.p)}<duration>${dur}</duration><voice>${voice}</voice></note>`;
      });
    }
    prev = keys[i] + dur;
  }
  return `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">
<score-partwise version="4.0">
  <work><work-title>${_esc(title)}</work-title></work>
  <identification><creator type="composer">${_esc(composer)}</creator><encoding><software>Musical Dynamics</software></encoding></identification>
  <part-list><score-part id="P1"><part-name>Program</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>${divisions}</divisions>
        <key><fifths>0</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
        <clef><sign>G</sign><line>2</line></clef>
      </attributes>
      ${measureBody}
    </measure>
  </part>
</score-partwise>`;
}

export function downloadMusicXML(notes, filename = "musical_dynamics.musicxml", opts = {}) {
  const xml = notesToMusicXML(notes, opts);
  const blob = new Blob([xml], { type: "application/vnd.recordare.musicxml+xml" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a"); a.href = url; a.download = filename; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 100);
}
