function buildMemoryPanel(body) {
  body.innerHTML = `
    <div style="padding:10px; border-bottom:1px solid var(--border); display:flex; gap:6px;">
        <input class="fi" id="mem-search-input" placeholder="Search Memory (Facts, Episodes, Projects)..." style="margin:0; flex:1;" onkeydown="if(event.key==='Enter') searchMemory()"/>
        <button class="cbtn primary" onclick="searchMemory()">Search</button>
    </div>
    <div id="memory-results" style="flex:1; overflow-y:auto; padding:10px; display:flex; flex-direction:column; gap:8px;">
        <div style="color:var(--muted); font-size:11px; text-align:center;">Enter a query to search long-term memory.</div>
    </div>
  `;
}

async function searchMemory() {
  const query = document.getElementById('mem-search-input').value.trim();
  if (!query) return;

  const resultsDiv = document.getElementById('memory-results');
  resultsDiv.innerHTML = '<div style="color:var(--muted); font-size:11px; text-align:center;">Searching...</div>';

  try {
      const res = await post('/api/memory/search', { query });
      if (res.results && res.results.length > 0) {
          resultsDiv.innerHTML = res.results.map(r => `
              <div style="padding:8px; border-radius:6px; background:var(--surface2); border:1px solid var(--border);">
                  <div style="font-size:11px; font-weight:bold; color:var(--accent); margin-bottom:4px;">${r.category || 'Fact'}</div>
                  <div style="font-size:11px; color:var(--text); line-height:1.4;">${r.content}</div>
                  <div style="font-size:9px; color:var(--muted); margin-top:4px;">Source: ${r.source || 'Unknown'}</div>
              </div>
          `).join('');
      } else {
          resultsDiv.innerHTML = '<div style="color:var(--muted); font-size:11px; text-align:center;">No relevant memories found.</div>';
      }
  } catch (e) {
      resultsDiv.innerHTML = `<div style="color:var(--red); font-size:11px; text-align:center;">Error: ${e.message}</div>`;
  }
}
