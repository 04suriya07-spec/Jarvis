function buildApprovalsPanel(body) {
  body.innerHTML = `
    <div style="padding:10px; border-bottom:1px solid var(--border); display:flex; justify-content:space-between; align-items:center;">
        <span style="font-weight:bold; color:var(--accent4);">Pending Approvals</span>
    </div>
    <div id="approvals-list" style="flex:1; overflow-y:auto; padding:10px; display:flex; flex-direction:column; gap:8px;">
        <div style="color:var(--muted); font-size:11px; text-align:center;">No pending approvals.</div>
    </div>
  `;
}

function addApprovalRequest(eventData) {
  const list = document.getElementById('approvals-list');
  if (!list) return;

  if (list.innerHTML.includes("No pending approvals.")) {
      list.innerHTML = "";
  }

  const { tool, policy, trace_id } = eventData.data;
  const hash = policy.action_hash;

  const el = document.createElement("div");
  el.id = `approval-${hash}`;
  el.style.cssText = "padding:10px; border-radius:8px; background:var(--surface2); border:1px solid var(--accent4);";

  el.innerHTML = `
      <div style="font-weight:bold; font-size:12px; margin-bottom:4px; color:var(--accent4);">Action Blocked: ${tool}</div>
      <div style="font-size:11px; color:var(--text); margin-bottom:4px;">Risk: <span style="color:var(--red);">${policy.risk}</span></div>
      <div style="font-size:11px; color:var(--muted); margin-bottom:8px;">${eventData.message}</div>
      <div style="display:flex; gap:6px;">
          <button class="cbtn primary" onclick="approveAction('${hash}')">Approve (10m)</button>
          <button class="cbtn danger" onclick="denyAction('${hash}')">Deny</button>
      </div>
  `;
  list.appendChild(el);
}

async function approveAction(hash) {
  try {
      const res = await post('/api/policy/approve', { action_hash: hash, ttl_seconds: 600 });
      if (res.status === "approved") {
          showToast('Approval', 'Action approved.', 'success');
          const el = document.getElementById(`approval-${hash}`);
          if (el) el.remove();
          checkEmptyApprovals();
      }
  } catch (e) {
      showToast('Approval Error', e.message, 'error');
  }
}

function denyAction(hash) {
  const el = document.getElementById(`approval-${hash}`);
  if (el) el.remove();
  showToast('Approval', 'Action denied.', 'info');
  checkEmptyApprovals();
}

function checkEmptyApprovals() {
  const list = document.getElementById('approvals-list');
  if (list && list.children.length === 0) {
      list.innerHTML = '<div style="color:var(--muted); font-size:11px; text-align:center;">No pending approvals.</div>';
  }
}
