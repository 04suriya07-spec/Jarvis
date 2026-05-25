/* ════════════════════════════════════════════════════════════════
   live-bg.js — JAVRIS AMBIENT BACKGROUND LAYER
   ───────────────────────────────────────────────────────────────
   Drop this onto any page to make it feel alive:
   - Breathing scanline grid (opacity pulse)
   - Drifting radial glow orbs (cyan + purple)
   - 18 falling cyan particles
   - 6 random blinking dots
   - HUD corner brackets that pulse
   - A traveling horizontal scanline
   - Live JS-driven timestamp readouts (top-left + top-right)
   - Bottom data ticker scrolling JARVIS telemetry
   Usage:  <script src="path/to/live-bg.js"></script>
   ════════════════════════════════════════════════════════════════ */
(function () {
  if (window.__jvbgLoaded) return;
  window.__jvbgLoaded = true;

  // Skip on tiny viewports (would dominate the content)
  const tiny = window.innerWidth < 200 || window.innerHeight < 140;

  const CSS = `
    @keyframes jvbg-grid-breath { 0%,100%{opacity:.45} 50%{opacity:1} }
    @keyframes jvbg-scan        { 0%{transform:translateY(-4px);opacity:0} 8%{opacity:1} 92%{opacity:1} 100%{transform:translateY(101vh);opacity:0} }
    @keyframes jvbg-orb-a       { 0%{transform:translate(-10vw,10vh)} 33%{transform:translate(40vw,30vh)} 66%{transform:translate(20vw,60vh)} 100%{transform:translate(-10vw,10vh)} }
    @keyframes jvbg-orb-b       { 0%{transform:translate(60vw,70vh)} 33%{transform:translate(20vw,30vh)} 66%{transform:translate(70vw,10vh)} 100%{transform:translate(60vw,70vh)} }
    @keyframes jvbg-particle    { from{transform:translateY(110vh)} to{transform:translateY(-10vh)} }
    @keyframes jvbg-corner      { 0%,100%{opacity:.35;box-shadow:0 0 0 rgba(0,212,255,0)} 50%{opacity:.95;box-shadow:0 0 6px rgba(0,212,255,.4)} }
    @keyframes jvbg-blink       { 0%,90%{opacity:0;transform:scale(.6)} 95%{opacity:1;transform:scale(1)} 100%{opacity:0;transform:scale(.6)} }
    @keyframes jvbg-ticker      { from{transform:translateX(0)} to{transform:translateX(-50%)} }
    @keyframes jvbg-readout     { 0%,100%{opacity:.7} 50%{opacity:.4} }

    /* Hide the page's existing static grid if it has one — we replace it */
    body[data-jvbg]::before { display: none !important; }

    .jvbg-layer { position:fixed; inset:0; pointer-events:none; z-index:0; overflow:hidden; }
    .jvbg-grid {
      position:absolute; inset:0;
      background-image:
        linear-gradient(rgba(0,212,255,.05) 1px, transparent 1px),
        linear-gradient(90deg, rgba(0,212,255,.05) 1px, transparent 1px);
      background-size: 40px 40px;
      animation: jvbg-grid-breath 7s ease-in-out infinite;
    }
    .jvbg-orb {
      position:absolute; width:60vmax; height:60vmax; border-radius:50%;
      background: radial-gradient(closest-side, rgba(0,212,255,.06), transparent 70%);
      filter: blur(40px);
      animation: jvbg-orb-a 38s ease-in-out infinite;
      will-change: transform;
    }
    .jvbg-orb.b {
      background: radial-gradient(closest-side, rgba(124,58,237,.05), transparent 70%);
      animation: jvbg-orb-b 52s ease-in-out infinite;
      width:50vmax; height:50vmax;
    }
    .jvbg-particle {
      position:absolute; width:2px; height:2px; border-radius:50%;
      background: rgba(0,212,255,.65);
      box-shadow: 0 0 4px rgba(0,212,255,.7);
      animation: jvbg-particle linear infinite;
      will-change: transform;
    }
    .jvbg-blink {
      position:absolute; width:3px; height:3px; border-radius:50%;
      background: rgba(0,212,255,.9);
      box-shadow: 0 0 6px rgba(0,212,255,.9);
      animation: jvbg-blink ease-out infinite;
    }
    .jvbg-scan {
      position:fixed; left:0; right:0; top:0; height:1px;
      background: linear-gradient(90deg, transparent 0%, rgba(0,212,255,.0) 10%, rgba(0,212,255,.6) 50%, rgba(0,212,255,.0) 90%, transparent 100%);
      box-shadow: 0 0 8px rgba(0,212,255,.5), 0 0 24px rgba(0,212,255,.25);
      animation: jvbg-scan 9s linear infinite;
      pointer-events:none; z-index:1;
    }
    .jvbg-corner {
      position:fixed; width:22px; height:22px; pointer-events:none; z-index:2;
      border: 1px solid rgba(0,212,255,.6);
      animation: jvbg-corner 3.2s ease-in-out infinite;
    }
    .jvbg-corner.tl { top:6px;  left:6px;  border-right:0; border-bottom:0; }
    .jvbg-corner.tr { top:6px;  right:6px; border-left:0;  border-bottom:0; animation-delay:.8s }
    .jvbg-corner.bl { bottom:6px; left:6px; border-right:0; border-top:0; animation-delay:1.6s }
    .jvbg-corner.br { bottom:6px; right:6px; border-left:0; border-top:0; animation-delay:2.4s }

    .jvbg-readout {
      position:fixed; top:6px; left:34px; z-index:3; pointer-events:none;
      font-family: 'JetBrains Mono', 'Cascadia Code', monospace;
      font-size:9px; letter-spacing:1.2px; text-transform:uppercase;
      color: rgba(0,212,255,.6);
      animation: jvbg-readout 4s ease-in-out infinite;
      white-space:nowrap;
    }
    .jvbg-readout.r { left:auto; right:34px; }

    .jvbg-ticker {
      position:fixed; bottom:0; left:34px; right:34px; height:16px; z-index:3;
      pointer-events:none; overflow:hidden;
      font-family: 'JetBrains Mono', 'Cascadia Code', monospace;
      font-size: 9px; letter-spacing:1.5px;
      color: rgba(0,212,255,.45);
      display:flex; align-items:center;
      -webkit-mask-image: linear-gradient(90deg, transparent, #000 8%, #000 92%, transparent);
              mask-image: linear-gradient(90deg, transparent, #000 8%, #000 92%, transparent);
    }
    .jvbg-ticker-inner {
      display:inline-flex; white-space:nowrap;
      animation: jvbg-ticker 80s linear infinite;
    }
    .jvbg-ticker-inner > span { padding: 0 28px; }
    .jvbg-ticker-inner .sep { color: rgba(0,212,255,.7); }

    /* Tiny-viewport variant — keep ambient motion, drop the chrome */
    .jvbg-tiny .jvbg-readout,
    .jvbg-tiny .jvbg-ticker { display:none; }
    .jvbg-tiny .jvbg-corner { width:14px; height:14px; top:3px; left:3px; }
    .jvbg-tiny .jvbg-corner.tr { left:auto; right:3px; }
    .jvbg-tiny .jvbg-corner.bl { top:auto; bottom:3px; }
    .jvbg-tiny .jvbg-corner.br { top:auto; bottom:3px; left:auto; right:3px; }
  `;

  const styleTag = document.createElement('style');
  styleTag.id = 'jvbg-style';
  styleTag.textContent = CSS;
  document.head.appendChild(styleTag);

  function mount() {
    document.body.setAttribute('data-jvbg', '');
    if (tiny) document.body.classList.add('jvbg-tiny');

    const layer = document.createElement('div');
    layer.className = 'jvbg-layer';

    const grid = document.createElement('div'); grid.className = 'jvbg-grid'; layer.appendChild(grid);
    const orbA = document.createElement('div'); orbA.className = 'jvbg-orb';   layer.appendChild(orbA);
    const orbB = document.createElement('div'); orbB.className = 'jvbg-orb b'; layer.appendChild(orbB);

    // Falling particles
    const pCount = tiny ? 6 : 18;
    for (let i = 0; i < pCount; i++) {
      const p = document.createElement('div'); p.className = 'jvbg-particle';
      p.style.left = (Math.random() * 100) + '%';
      p.style.animationDuration = (12 + Math.random() * 24).toFixed(1) + 's';
      p.style.animationDelay = (-Math.random() * 30).toFixed(1) + 's';
      p.style.opacity = (0.25 + Math.random() * 0.5).toFixed(2);
      const s = (1 + Math.random() * 2).toFixed(1);
      p.style.width = s + 'px'; p.style.height = s + 'px';
      layer.appendChild(p);
    }

    // Random blinking pixels
    const bCount = tiny ? 3 : 7;
    for (let i = 0; i < bCount; i++) {
      const b = document.createElement('div'); b.className = 'jvbg-blink';
      b.style.left = (Math.random() * 100) + '%';
      b.style.top  = (Math.random() * 100) + '%';
      b.style.animationDelay = (Math.random() * 6).toFixed(1) + 's';
      b.style.animationDuration = (4 + Math.random() * 6).toFixed(1) + 's';
      layer.appendChild(b);
    }

    // Traveling horizontal scanline
    const scan = document.createElement('div'); scan.className = 'jvbg-scan';

    // Corner brackets
    ['tl','tr','bl','br'].forEach(c => {
      const corner = document.createElement('div');
      corner.className = 'jvbg-corner ' + c;
      document.body.appendChild(corner);
    });

    document.body.insertBefore(layer, document.body.firstChild);
    document.body.appendChild(scan);

    if (!tiny) {
      // Top readouts (live)
      const rl = document.createElement('div'); rl.className = 'jvbg-readout';
      const rr = document.createElement('div'); rr.className = 'jvbg-readout r';
      document.body.appendChild(rl); document.body.appendChild(rr);

      // Bottom ticker
      const ticker = document.createElement('div'); ticker.className = 'jvbg-ticker';
      const inner = document.createElement('div'); inner.className = 'jvbg-ticker-inner';
      const items = [
        'NEURAL CORE · ONLINE',
        'ROUTER · GROQ → CEREBRAS → CLAUDE',
        'MEMORY · 12.4 MB INDEXED · 1,247 EMBEDDINGS',
        'AMBIENT · 8 CONTEXT SLOTS · USER PRESENT',
        'AUTONOMY · FAST LOOP 30S · SLOW LOOP 10MIN',
        'CIRCUIT BREAKER · 0 OPEN · 5 / 5 HEALTHY',
        'EPISODIC · WRITING SESSION s_847A',
        'CHANNEL · WSS://JAVRIS/WS · ALIVE',
        'TASK LEDGER · 23 PENDING · 4 SCHEDULED',
        'VECTOR INDEX · CHROMA · 12 MS LOOKUP',
        'TTS · EDGE-NEURAL · EN-GB-RYAN',
        'STT · WHISPER LARGE · LOCAL',
        'WAKE WORD · ACTIVE · "JAVRIS"',
        'GUARDIAN · POLICY ENGINE · NOMINAL',
      ];
      const seq = items.map(t => `<span>${t}</span>`).join('<span class="sep">◆</span>');
      inner.innerHTML = seq + '<span class="sep">◆</span>' + seq;
      ticker.appendChild(inner);
      document.body.appendChild(ticker);

      // Live readouts ticking once per second
      let frame = 0;
      function tick() {
        const t = new Date();
        const hh = String(t.getHours()).padStart(2, '0');
        const mm = String(t.getMinutes()).padStart(2, '0');
        const ss = String(t.getSeconds()).padStart(2, '0');
        const ms = String(t.getMilliseconds()).padStart(3, '0');
        rl.textContent = `JAVRIS · ${hh}:${mm}:${ss}.${ms.slice(0,2)} · F${String(frame).padStart(5,'0')}`;
        const hex = (0xA00 + (frame * 7) % 0xFFF).toString(16).toUpperCase().padStart(3,'0');
        const cpu = (6 + (frame * 3) % 18);
        const mem = (62 + (frame * 5) % 8);
        rr.textContent = `0x${hex} · CPU ${cpu}% · MEM ${mem}% · LAT ${(120 + (frame * 11) % 240)}MS`;
        frame++;
      }
      tick();
      setInterval(() => { tick(); }, 1000);

      // Sub-second flicker for the trailing ms digits — extra alive feel
      setInterval(() => {
        const t = new Date();
        const ms = String(t.getMilliseconds()).padStart(3, '0').slice(0,2);
        const cur = rl.textContent;
        rl.textContent = cur.replace(/\.\d{2} ·/, '.' + ms + ' ·');
      }, 70);
    }
  }

  if (document.body) mount();
  else document.addEventListener('DOMContentLoaded', mount);
})();
