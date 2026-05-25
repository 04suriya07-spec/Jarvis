function buildTracePanel(body) {
  body.innerHTML = `
    <div style="padding:10px; border-bottom:1px solid var(--border); display:flex; justify-content:space-between; align-items:center;">
        <span style="font-weight:bold; color:var(--accent);">Live Executor Trace</span>
        <button class="cbtn" onclick="clearTrace()">Clear</button>
    </div>
    <div class="chat-scroll" id="trace-scroll" style="flex:1; overflow-y:auto; padding:10px;">
        <div style="color:var(--muted); font-size:11px; text-align:center;">Waiting for tasks...</div>
    </div>
  `;
}

function appendTraceEvent(eventData) {
  const scroll = document.getElementById('trace-scroll');
  if (!scroll) return;
  
  if (scroll.innerHTML.includes("Waiting for tasks...")) {
      scroll.innerHTML = "";
  }

  const el = document.createElement("div");
  el.style.cssText = "margin-bottom:8px; padding:8px; border-radius:6px; background:var(--surface2); border-left:3px solid var(--accent); font-size:11px;";
  
  let content = `<strong>${eventData.title || eventData.event_type}</strong>`;
  if (eventData.message) content += `<div style="margin-top:4px; color:var(--muted);">${eventData.message}</div>`;
  if (eventData.data && Object.keys(eventData.data).length > 0) {
      content += `<pre style="margin-top:4px; font-size:9px; background:var(--surface3); padding:4px; border-radius:4px; overflow-x:auto;">${JSON.stringify(eventData.data, null, 2)}</pre>`;
  }
  
  el.innerHTML = content;
  scroll.appendChild(el);
  scroll.scrollTop = scroll.scrollHeight;
}

function clearTrace() {
  const scroll = document.getElementById('trace-scroll');
  if (scroll) scroll.innerHTML = '<div style="color:var(--muted); font-size:11px; text-align:center;">Waiting for tasks...</div>';
}
