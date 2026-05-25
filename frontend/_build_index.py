"""Build the new cinematic index.html."""
import os

script_inner = open('S:/Javris/frontend/static/js/_script_inner.txt', encoding='utf-8').read()
# Strip the closing </script> tag that's already in script_inner (we add it in HTML_BOTTOM)
script_inner = script_inner.rstrip()
if script_inner.endswith('</script>'):
    script_inner = script_inner[:-len('</script>')].rstrip()

HTML_TOP = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>Javris OS</title>
<link rel="stylesheet" href="/static/css/design-tokens.css"/>
<link rel="stylesheet" href="/static/css/cinematic.css"/>
<style>
/* ═══════════════════════════════════════════════════════════
   JAVRIS OS — WORKSPACE STYLESHEET  (Cinematic Edition)
   ═══════════════════════════════════════════════════════════ */

/* Map old --accent/--bg/etc vars to design tokens */
:root{
  --bg:var(--color-bg);--surface:var(--color-surface-1);
  --surface2:var(--color-surface-2);--surface3:var(--color-surface-3);
  --accent:var(--color-accent);--accent2:var(--color-accent-2);
  --accent3:var(--color-accent-3);--accent4:var(--color-accent-4);
  --red:var(--color-danger);--muted:var(--color-text-muted);
  --text:var(--color-text);--border:var(--color-border);
  --font:var(--font-body);--mono:var(--font-mono);
  --r:10px;--panel-head:38px;
}

/* Override crimson gradients in cs-stage to cyan */
.cs-stage{
  background:
    radial-gradient(900px 700px at 50% 50%,rgba(0,212,255,.04),transparent 60%),
    radial-gradient(600px 500px at 20% 20%,rgba(0,212,255,.02),transparent 60%),
    radial-gradient(700px 500px at 80% 90%,rgba(0,212,255,.02),transparent 60%),
    #02030a;
  z-index:0;
}
.cs-stage::before{
  background-image:
    linear-gradient(rgba(0,212,255,.025) 1px,transparent 1px),
    linear-gradient(90deg,rgba(0,212,255,.025) 1px,transparent 1px);
}
/* Adjust corner positions for our 44px topbar + 40px taskbar */
.cs-corner.tl{top:52px}.cs-corner.tr{top:52px}
.cs-corner.bl{bottom:48px}.cs-corner.br{bottom:48px}

*{box-sizing:border-box;margin:0;padding:0;user-select:none}
input,textarea,select{user-select:text}
html,body{width:100%;height:100%;overflow:hidden;background:var(--bg);color:var(--text);font-family:var(--font);font-size:13px}

/* ── TOPBAR ── */
#topbar{
  position:fixed;top:0;left:0;right:0;height:44px;z-index:9000;
  background:rgba(5,8,16,.92);backdrop-filter:blur(12px);
  border-bottom:1px solid var(--border);
  display:flex;align-items:center;gap:10px;padding:0 14px;overflow:hidden;
}
.tb-logo{width:30px;height:30px;border-radius:50%;background:conic-gradient(var(--accent),var(--accent2),var(--accent));display:flex;align-items:center;justify-content:center;font-weight:900;font-size:13px;color:#fff;animation:hue 8s linear infinite;flex-shrink:0;cursor:pointer}
@keyframes hue{to{filter:hue-rotate(360deg)}}
.tb-brand{font-family:var(--font-display);font-size:18px;font-weight:700;letter-spacing:4px;color:var(--accent);flex-shrink:0;text-shadow:0 0 20px rgba(0,212,255,.5)}
.tb-sep{width:1px;height:20px;background:var(--border);flex-shrink:0}
.panel-launcher{display:flex;align-items:center;gap:5px;padding:4px 10px;border-radius:6px;border:1px solid transparent;background:none;color:var(--muted);cursor:pointer;font-size:11px;font-family:var(--font);transition:all .15s;flex-shrink:0;}
.panel-launcher:hover{background:rgba(0,212,255,.08);border-color:var(--accent);color:var(--accent)}
.panel-launcher.open{background:rgba(0,212,255,.12);border-color:var(--accent);color:var(--accent)}
#voice-area{margin-left:auto;display:flex;align-items:center;gap:8px;flex-shrink:0}
#voice-ring{width:34px;height:34px;border-radius:50%;border:2px solid var(--muted);display:flex;align-items:center;justify-content:center;cursor:pointer;transition:all .2s;position:relative;}
#voice-ring.listening{border-color:var(--red);animation:vring-red 1s infinite}
#voice-ring.speaking{border-color:var(--accent3);animation:vring 1s infinite}
@keyframes vring{0%,100%{box-shadow:0 0 0 0 rgba(0,212,255,.4)}50%{box-shadow:0 0 0 8px rgba(0,212,255,0)}}
@keyframes vring-red{0%,100%{box-shadow:0 0 0 0 rgba(239,68,68,.5)}50%{box-shadow:0 0 0 10px rgba(239,68,68,0)}}
#voice-label{font-size:10px;color:var(--muted);max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#notif-btn{width:32px;height:32px;border-radius:8px;border:1px solid var(--border);background:var(--surface2);display:flex;align-items:center;justify-content:center;cursor:pointer;position:relative;font-size:14px;}
#notif-count{position:absolute;top:-4px;right:-4px;background:var(--red);color:#fff;font-size:9px;width:16px;height:16px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:700;display:none;}
.tb-badge{display:flex;align-items:center;gap:4px;padding:3px 8px;border-radius:12px;background:var(--surface2);border:1px solid var(--border);font-size:10px;flex-shrink:0}
.dot{width:6px;height:6px;border-radius:50%}
.dot.on{background:var(--accent3);box-shadow:0 0 5px var(--accent3)}.dot.off{background:var(--red)}.dot.idle{background:var(--accent4)}
#vitals-bar{display:flex;align-items:center;gap:6px;flex-shrink:0}
.vital-chip{display:flex;align-items:center;gap:4px;padding:2px 7px;border-radius:10px;background:var(--surface2);border:1px solid var(--border);font-size:10px;font-family:var(--mono);white-space:nowrap;}
.vc-lbl{color:var(--muted);font-size:9px;text-transform:uppercase;letter-spacing:.5px}
.vc-val{color:var(--accent);font-weight:700}
#provider-badge{display:flex;align-items:center;gap:4px;padding:3px 8px;border-radius:10px;background:var(--surface2);border:1px solid var(--border);font-size:10px;font-weight:600;letter-spacing:.5px;flex-shrink:0;color:var(--muted);}
#provider-badge[data-provider="groq"]{border-color:rgba(0,212,255,.4);color:var(--accent)}
#provider-badge[data-provider="cerebras"]{border-color:rgba(124,58,237,.4);color:#a78bfa}
#provider-badge[data-provider="claude"]{border-color:rgba(245,158,11,.4);color:var(--accent4)}
#provider-badge[data-provider="openai"]{border-color:rgba(16,185,129,.4);color:var(--accent3)}
#jarvis-status-badge{display:flex;align-items:center;gap:5px;padding:3px 9px;border-radius:12px;background:var(--surface2);border:1px solid var(--accent3);font-size:10px;font-weight:700;letter-spacing:1px;color:var(--accent3);flex-shrink:0;}
.jsbdot{width:5px;height:5px;border-radius:50%;background:currentColor;animation:jspulse 1.5s infinite}
@keyframes jspulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.3;transform:scale(.6)}}
#waveform{display:flex;align-items:center;gap:2px;height:28px;padding:0 2px;opacity:0;transition:opacity .3s;flex-shrink:0;}
#waveform.active{opacity:1}
.wf-bar{width:3px;border-radius:2px;background:var(--accent);height:2px;}
#waveform.active .wf-bar{animation-iteration-count:infinite;animation-direction:alternate;animation-timing-function:ease-in-out;}
@keyframes wfa{0%{height:2px}100%{height:var(--h,8px)}}

/* ── AMBIENT STRIP ── */
#ambient-strip{position:fixed;top:44px;left:0;right:0;height:24px;z-index:8999;background:rgba(5,8,16,.85);border-bottom:1px solid rgba(0,212,255,.08);display:flex;align-items:center;padding:0 16px;font-family:var(--mono);font-size:10px;color:var(--accent);letter-spacing:.5px;opacity:0;transition:opacity .5s;pointer-events:none;}
#ambient-strip.visible{opacity:1}
#ambient-text{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1}
#ambient-time{flex-shrink:0;color:var(--muted);margin-left:12px;font-size:9px}

/* ── GESTURE HUD ── */
#gesture-hud{position:fixed;bottom:50px;right:16px;z-index:8990;background:rgba(5,8,16,.88);border:1px solid rgba(0,212,255,.15);border-radius:10px;padding:8px 12px;font-family:var(--mono);font-size:11px;color:var(--accent);backdrop-filter:blur(8px);opacity:0;transform:translateY(4px);transition:opacity .3s,transform .3s;pointer-events:none;min-width:180px;}
#gesture-hud.visible{opacity:1;transform:translateY(0)}
#gesture-hud.cursor-mode{border-color:rgba(0,200,255,.5);background:rgba(0,20,40,.9)}
#gesture-hud.scroll-mode{border-color:rgba(16,185,129,.5);background:rgba(0,20,16,.9)}
#gesture-hud.scroll-mode .gh-value,#gesture-hud.scroll-mode #gesture-dot{color:#10b981}
#gesture-hud.scroll-mode .gh-cursor-badge{border-color:#10b981;background:rgba(16,185,129,.15);color:#10b981}
.gh-row{display:flex;justify-content:space-between;gap:12px;line-height:1.6}
.gh-label{color:var(--muted);font-size:10px}
.gh-value{color:var(--accent);font-weight:600;text-transform:uppercase;letter-spacing:.5px}
.gh-action{color:var(--accent3);font-size:10px;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.gh-cursor-badge{display:inline-block;background:rgba(0,200,255,.2);border:1px solid var(--accent);border-radius:4px;padding:1px 6px;font-size:9px;margin-top:4px;letter-spacing:.5px;}
#gesture-dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--accent3);margin-right:5px;vertical-align:middle;animation:gdot 1s ease-in-out infinite;}
@keyframes gdot{0%,100%{opacity:1}50%{opacity:.3}}

/* ── CIN CLOCK (decorative, top-left below topbar) ── */
#cin-clock{position:fixed;top:52px;left:12px;z-index:8998;font-family:var(--font-display);font-size:11px;font-weight:600;letter-spacing:2px;color:rgba(0,212,255,.35);pointer-events:none;text-shadow:0 0 8px rgba(0,212,255,.2);line-height:1.4;}

/* ── WORKSPACE ── */
#workspace{position:fixed;top:44px;left:0;right:0;bottom:40px;z-index:1;transition:top .3s}
#workspace.ambient-on{top:68px}

/* ── FLOATING PANEL ── */
.panel{position:absolute;background:rgba(11,17,32,.95);backdrop-filter:blur(16px);border:1px solid var(--border);border-radius:12px;display:flex;flex-direction:column;box-shadow:0 8px 40px rgba(0,0,0,.6),0 0 0 1px rgba(0,212,255,.05);min-width:280px;min-height:180px;transition:box-shadow .15s;overflow:hidden;}
.panel.focused{border-color:rgba(0,212,255,.3);box-shadow:0 12px 50px rgba(0,0,0,.7),0 0 0 1px rgba(0,212,255,.15);}
.panel.minimized{display:none}
.panel-head{height:var(--panel-head);display:flex;align-items:center;gap:8px;padding:0 12px;cursor:move;flex-shrink:0;background:rgba(255,255,255,.02);border-bottom:1px solid var(--border);}
.panel-head .ph-icon{font-size:14px;flex-shrink:0}
.panel-head .ph-title{font-family:var(--font-display);font-size:13px;font-weight:600;flex:1;letter-spacing:1px;color:var(--accent)}
.panel-head .ph-controls{display:flex;gap:4px;margin-left:auto}
.phc-btn{width:18px;height:18px;border-radius:50%;border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:9px;transition:opacity .15s;}
.phc-btn:hover{opacity:.8}
.phc-min{background:#f59e0b;color:#000}.phc-max{background:#10b981;color:#000}.phc-cls{background:#ef4444;color:#fff}
.panel-body{flex:1;overflow:hidden;display:flex;flex-direction:column;position:relative}
.resize-handle{position:absolute;bottom:0;right:0;width:14px;height:14px;cursor:se-resize;z-index:10;background:linear-gradient(135deg,transparent 50%,rgba(0,212,255,.3) 50%);border-bottom-right-radius:10px;}

/* ── TASKBAR ── */
#taskbar{position:fixed;bottom:0;left:0;right:0;height:40px;z-index:9000;background:rgba(5,8,16,.92);backdrop-filter:blur(12px);border-top:1px solid var(--border);display:flex;align-items:center;gap:4px;padding:0 8px;overflow-x:auto;}
.taskbar-item{display:flex;align-items:center;gap:5px;padding:4px 10px;border-radius:6px;border:1px solid var(--border);background:var(--surface2);color:var(--muted);cursor:pointer;font-size:11px;font-family:var(--font);transition:all .15s;flex-shrink:0;min-width:80px;}
.taskbar-item:hover{border-color:var(--accent);color:var(--accent)}
.taskbar-item.active{background:rgba(0,212,255,.1);border-color:var(--accent);color:var(--accent)}
.taskbar-item .ti-dot{width:5px;height:5px;border-radius:50%;background:var(--accent3);flex-shrink:0}

/* ── NOTIFICATIONS ── */
.notif-item{padding:10px 12px;border-radius:8px;background:var(--surface2);border-left:3px solid var(--muted);margin-bottom:7px;font-size:12px;cursor:pointer;transition:background .15s;}
.notif-item:hover{background:var(--surface3)}
.notif-item.high,.notif-item.critical{border-left-color:var(--red)}
.notif-item.medium{border-left-color:var(--accent4)}
.notif-item.low,.notif-item.info{border-left-color:var(--accent3)}
.notif-item .ni-title{font-weight:600;margin-bottom:3px;display:flex;align-items:center;gap:6px}
.notif-item .ni-msg{color:var(--muted);line-height:1.4}
.notif-item .ni-time{font-size:10px;color:var(--muted);margin-top:4px}

/* ── CHAT ── */
.chat-scroll{flex:1;overflow-y:auto;padding:12px;display:flex;flex-direction:column;gap:10px}
.msg{display:flex;gap:8px;max-width:100%}
.msg.user{flex-direction:row-reverse;align-self:flex-end}
.msg.assistant{align-self:flex-start}
.msg .avatar{width:26px;height:26px;border-radius:50%;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:12px}
.msg.user .avatar{background:var(--accent2)}
.msg.assistant .avatar{background:linear-gradient(135deg,var(--accent),var(--accent2))}
.msg .bubble{padding:8px 12px;border-radius:12px;font-size:12px;line-height:1.6;max-width:85%;position:relative}
.msg.user .bubble{background:#0f2744;border:1px solid rgba(0,212,255,.15);border-bottom-right-radius:3px}
.msg.assistant .bubble{background:#0b1628;border:1px solid var(--border);border-bottom-left-radius:3px}
.msg .bubble pre{background:#060d1a;padding:8px;border-radius:6px;overflow-x:auto;font-family:var(--mono);font-size:11px;margin:5px 0;border:1px solid var(--border)}
.msg .bubble code{font-family:var(--mono);background:rgba(0,212,255,.1);padding:1px 4px;border-radius:3px;font-size:11px}
.msg .bubble pre code{background:none;padding:0}
.msg .bubble strong{color:var(--accent)}.msg .bubble a{color:var(--accent);text-decoration:none}
.msg .bubble ul,.msg .bubble ol{padding-left:14px;margin:4px 0}
.typing-dots{display:flex;gap:3px;padding:8px 12px;background:#0b1628;border-radius:12px;border-bottom-left-radius:3px;border:1px solid var(--border)}
.td{width:6px;height:6px;border-radius:50%;background:var(--accent);animation:tdb 1.4s infinite}
.td:nth-child(2){animation-delay:.2s}.td:nth-child(3){animation-delay:.4s}
@keyframes tdb{0%,60%,100%{transform:translateY(0);opacity:.4}30%{transform:translateY(-5px);opacity:1}}
.mem-badge{display:inline-flex;align-items:center;gap:3px;padding:1px 6px;border-radius:8px;background:rgba(0,212,255,.12);border:1px solid rgba(0,212,255,.3);color:var(--accent);font-size:9px;font-weight:700;letter-spacing:.5px;position:absolute;top:-9px;right:4px;white-space:nowrap;}
.chat-input-strip{padding:8px 10px;border-top:1px solid var(--border);display:flex;gap:6px;align-items:flex-end;flex-shrink:0}
.chat-ta{flex:1;background:var(--surface2);border:1px solid var(--border);border-radius:8px;color:var(--text);font-family:var(--font);font-size:12px;padding:7px 10px;resize:none;min-height:34px;max-height:120px;outline:none;transition:border-color .2s;line-height:1.4;}
.chat-ta:focus{border-color:var(--accent)}
.chat-ta::placeholder{color:var(--muted)}
.ibtn{width:34px;height:34px;border-radius:8px;border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:14px;transition:all .15s;flex-shrink:0}
.ibtn.send{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff}
.ibtn.send:hover{opacity:.85;transform:scale(1.05)}
.ibtn.send:disabled{opacity:.3;cursor:not-allowed;transform:none}
.ibtn.ghost{background:var(--surface2);border:1px solid var(--border);color:var(--muted)}
.ibtn.ghost:hover{border-color:var(--accent);color:var(--accent)}

/* ── COMPUTER PANEL ── */
.comp-screenshot{flex:1;overflow:auto;display:flex;align-items:flex-start;justify-content:center;padding:8px;background:var(--bg)}
.comp-screenshot img{max-width:100%;border-radius:6px;border:1px solid var(--border)}
.step-log{height:160px;overflow-y:auto;padding:8px;border-top:1px solid var(--border);background:var(--surface)}
.step-entry{display:flex;gap:6px;padding:3px 0;border-bottom:1px solid rgba(255,255,255,.03);font-size:11px;line-height:1.4}
.step-num{color:var(--muted);flex-shrink:0;width:20px}.step-desc{flex:1;color:var(--text)}.step-desc.fail{color:var(--red)}
.comp-controls{display:flex;gap:5px;padding:7px 10px;border-bottom:1px solid var(--border);flex-wrap:wrap;flex-shrink:0}
.cbtn{padding:4px 10px;border-radius:6px;border:1px solid var(--border);background:var(--surface2);color:var(--text);font-size:11px;cursor:pointer;font-family:var(--font);transition:all .15s;flex-shrink:0}
.cbtn:hover{border-color:var(--accent);color:var(--accent)}
.cbtn.danger{border-color:rgba(239,68,68,.3);color:var(--red)}.cbtn.danger:hover{background:rgba(239,68,68,.1)}
.cbtn.primary{background:linear-gradient(135deg,var(--accent),var(--accent2));border-color:transparent;color:#fff}

/* ── TASKS ── */
.task-row{display:flex;align-items:center;gap:7px;padding:7px 10px;border-radius:8px;background:var(--surface2);border:1px solid var(--border);margin-bottom:5px}
.task-cb{width:15px;height:15px;border-radius:4px;border:1px solid var(--muted);flex-shrink:0;cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:9px;transition:all .15s}
.task-cb.done{background:var(--accent3);border-color:var(--accent3);color:#fff}
.task-info{flex:1;min-width:0}
.task-title-t{font-size:12px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.task-meta{font-size:10px;color:var(--muted)}
.prio{font-size:9px;padding:1px 6px;border-radius:8px;flex-shrink:0}
.prio.critical{background:rgba(239,68,68,.2);color:var(--red)}.prio.high{background:rgba(249,115,22,.2);color:#f97316}
.prio.medium{background:rgba(245,158,11,.2);color:var(--accent4)}.prio.low{background:rgba(16,185,129,.2);color:var(--accent3)}

/* ── FORMS ── */
.fi{width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:7px;color:var(--text);font-family:var(--font);font-size:12px;padding:7px 9px;outline:none;margin-bottom:7px;transition:border-color .2s}
.fi:focus{border-color:var(--accent)}.fl{font-size:10px;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);margin-bottom:4px;display:block}
.fs{appearance:none}
.ab{width:100%;padding:8px;border-radius:8px;border:none;font-size:12px;font-weight:600;cursor:pointer;font-family:var(--font);margin-bottom:6px;transition:opacity .2s}
.ab.pri{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff}
.ab.sec{background:var(--surface2);border:1px solid var(--border);color:var(--text)}.ab.sec:hover{border-color:var(--accent);color:var(--accent)}

/* ── INTELLIGENCE ── */
.stat-mini{background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:10px;text-align:center}
.stat-mini .sm-val{font-size:20px;font-weight:700;color:var(--accent);font-family:var(--font-display)}
.stat-mini .sm-lbl{font-size:10px;color:var(--muted)}
.fact-card{padding:8px;border-radius:7px;background:var(--surface2);border:1px solid var(--border);margin-bottom:5px;font-size:11px}
.fact-cat{font-size:9px;color:var(--accent);text-transform:uppercase;margin-bottom:2px}
.pat-bar-wrap{height:3px;background:var(--surface3);border-radius:2px;margin-top:4px}
.pat-bar-fill{height:100%;border-radius:2px;background:linear-gradient(90deg,var(--accent),var(--accent2))}

/* ── WEATHER / NEWS ── */
.weather-big{text-align:center;padding:16px}
.weather-temp{font-size:48px;font-weight:100;font-family:var(--font-display);color:var(--accent);line-height:1}
.weather-desc{font-size:14px;color:var(--muted);margin-top:4px}
.weather-stats{display:grid;grid-template-columns:1fr 1fr;gap:6px;padding:0 10px 10px}
.weather-stat{background:var(--surface2);border:1px solid var(--border);border-radius:7px;padding:8px;font-size:11px;text-align:center}
.weather-stat .ws-val{font-size:14px;font-weight:600;color:var(--text)}.weather-stat .ws-lbl{color:var(--muted);font-size:10px}
.news-item-p{padding:9px 10px;border-bottom:1px solid var(--border);font-size:11px;cursor:pointer}
.news-item-p:hover{background:var(--surface2)}
.news-item-p .nt{font-weight:600;line-height:1.4;margin-bottom:3px}
.news-item-p .ns{color:var(--muted);font-size:10px}.news-item-p .nb{color:var(--muted);line-height:1.4;margin-top:3px}

/* ── VOICE BAR ── */
#voice-bar{position:fixed;bottom:40px;left:50%;transform:translateX(-50%) translateY(20px);background:rgba(0,0,0,.85);backdrop-filter:blur(16px);border:1px solid var(--accent);border-radius:30px;padding:8px 20px;font-family:var(--font-display);font-size:13px;letter-spacing:1px;color:var(--accent);transition:all .3s;opacity:0;pointer-events:none;z-index:9999;max-width:500px;text-align:center;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
#voice-bar.show{opacity:1;transform:translateX(-50%) translateY(0)}

/* ── TOASTS ── */
#toast-container{position:fixed;top:76px;right:12px;z-index:9998;display:flex;flex-direction:column;gap:6px;pointer-events:none}
.toast{padding:10px 14px;border-radius:10px;background:rgba(11,17,32,.96);backdrop-filter:blur(12px);border:1px solid var(--border);color:var(--text);font-size:12px;max-width:300px;line-height:1.4;animation:toast-in .28s ease;box-shadow:0 4px 20px rgba(0,0,0,.5);pointer-events:all;cursor:pointer;}
.toast-title{font-family:var(--font-display);font-weight:700;margin-bottom:3px;font-size:11px;text-transform:uppercase;letter-spacing:1px}
.toast-msg{color:var(--muted)}
@keyframes toast-in{from{transform:translateX(30px);opacity:0}to{transform:none;opacity:1}}
@keyframes toast-out{from{transform:none;opacity:1}to{transform:translateX(30px);opacity:0}}
.toast.dismissing{animation:toast-out .25s ease forwards}
.toast.success{border-color:var(--accent3)}.toast.success .toast-title{color:var(--accent3)}
.toast.error{border-color:var(--red)}.toast.error .toast-title{color:var(--red)}
.toast.info{border-color:var(--accent)}.toast.info .toast-title{color:var(--accent)}
.toast.warning{border-color:var(--accent4)}.toast.warning .toast-title{color:var(--accent4)}

/* ── TOOL CALLS ── */
.tool-card{padding:8px 10px;border-radius:8px;margin-bottom:6px;font-size:11px;border-left:3px solid var(--muted);background:var(--surface2);}
.tool-card.active{border-left-color:var(--accent)}.tool-card.success{border-left-color:var(--accent3)}.tool-card.failed{border-left-color:var(--red)}
.tc-head{display:flex;align-items:center;gap:6px;margin-bottom:4px}
.tc-name{font-weight:700;flex:1}
.tool-card.active .tc-name{color:var(--accent)}.tool-card.success .tc-name{color:var(--accent3)}.tool-card.failed .tc-name{color:var(--red)}
.tc-time{font-size:9px;color:var(--muted)}
.tc-params{color:var(--muted);font-family:var(--mono);font-size:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:3px}
.tc-result{font-size:10px;color:var(--text);opacity:.8;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

/* ── SCROLLBAR ── */
::-webkit-scrollbar{width:4px;height:4px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}

/* ── MODE MENU ── */
.mode-opt{padding:6px 10px;border-radius:5px;cursor:pointer;font-size:11px;color:var(--text);transition:background .1s;white-space:nowrap;}
.mode-opt:hover{background:rgba(0,212,255,.12);color:var(--accent)}

/* ── WELCOME ── */
#workspace-welcome{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;pointer-events:none;z-index:0;}
#workspace-welcome.hidden{display:none}
.ww-inner{text-align:center;opacity:.3}
.ww-title{font-family:var(--font-display);font-size:28px;font-weight:700;letter-spacing:6px;color:var(--accent);text-shadow:0 0 40px rgba(0,212,255,.4)}
.ww-sub{font-size:12px;color:var(--muted);margin-top:8px;letter-spacing:1px}
.ww-ring{width:120px;height:120px;border-radius:50%;border:1px solid rgba(0,212,255,.3);margin:0 auto 20px;display:flex;align-items:center;justify-content:center;font-size:60px;animation:pulse 4s infinite;box-shadow:0 0 60px rgba(0,212,255,.1) inset}
@keyframes pulse{0%,100%{box-shadow:0 0 0 0 rgba(0,212,255,.3),0 0 60px rgba(0,212,255,.1) inset}50%{box-shadow:0 0 0 20px rgba(0,212,255,0),0 0 80px rgba(0,212,255,.15) inset}}
</style>
</head>
<body class="cyan">

<!-- ══ CINEMATIC SHELL ══════════════════════════════════════════ -->
<div class="cs-stage" id="cs-stage"></div>
<div class="cs-corner tl"></div>
<div class="cs-corner tr"></div>
<div class="cs-corner bl"></div>
<div class="cs-corner br"></div>
<div id="cin-clock"></div>

<!-- ══ TOPBAR ══════════════════════════════════════════════════ -->
<div id="topbar">
  <div class="tb-logo" onclick="openPanel('chat')" title="Chat">J</div>
  <div class="tb-brand">JAVRIS</div>
  <div class="tb-sep"></div>

  <div style="position:relative;flex-shrink:0">
    <button class="panel-launcher" id="mode-btn" onclick="toggleModeMenu()" title="Switch workspace mode">
      <span id="mode-icon">&#x1F4BC;</span> <span id="mode-name">Work</span> &#x25BE;
    </button>
    <div id="mode-menu" style="display:none;position:absolute;top:40px;left:0;background:rgba(5,8,16,.97);border:1px solid var(--border);border-radius:8px;padding:6px;z-index:9999;min-width:160px;backdrop-filter:blur(12px)">
      <div class="mode-opt" onclick="switchMode('work')">&#x1F4BC; Work</div>
      <div class="mode-opt" onclick="switchMode('trading')">&#x1F4C8; Trading</div>
      <div class="mode-opt" onclick="switchMode('dev')">&#x2328;&#xFE0F; Dev</div>
      <div class="mode-opt" onclick="switchMode('research')">&#x1F52C; Research</div>
      <div class="mode-opt" onclick="switchMode('focus')">&#x1F3AF; Focus</div>
      <div class="mode-opt" onclick="switchMode('night')">&#x1F319; Night</div>
    </div>
  </div>
  <div class="tb-sep"></div>
  <button class="panel-launcher" id="btn-live-toggle" onclick="toggleGeminiLive()" style="background:var(--surface2);border-color:var(--accent4);color:var(--accent4);font-weight:bold;">&#x1F399;&#xFE0F; Live</button>
  <div class="tb-sep"></div>

  <button class="panel-launcher" id="pl-chat"          onclick="openPanel('chat')">&#x1F4AC; Chat</button>
  <button class="panel-launcher" id="pl-computer"      onclick="openPanel('computer')">&#x1F5A5; Computer</button>
  <button class="panel-launcher" id="pl-tasks"         onclick="openPanel('tasks')">&#x2705; Tasks</button>
  <button class="panel-launcher" id="pl-intelligence"  onclick="openPanel('intelligence')">&#x1F9E0; Intel</button>
  <button class="panel-launcher" id="pl-weather"       onclick="openPanel('weather')">&#x1F324; Weather</button>
  <button class="panel-launcher" id="pl-news"          onclick="openPanel('news')">&#x1F4F0; News</button>
  <button class="panel-launcher" id="pl-notifications" onclick="openPanel('notifications')">&#x1F514; Alerts</button>
  <button class="panel-launcher" id="pl-research"      onclick="openPanel('research')">&#x1F52C; Research</button>
  <button class="panel-launcher" id="pl-personality"   onclick="openPanel('personality')">&#x2699;&#xFE0F; Config</button>
  <button class="panel-launcher" id="pl-tools"         onclick="openPanel('tools')">&#x1F527; Tools</button>
  <button class="panel-launcher" id="pl-trace"         onclick="openPanel('trace')">&#x26A1; Trace</button>
  <button class="panel-launcher" id="pl-approvals"     onclick="openPanel('approvals')">&#x1F6E1; Approvals</button>
  <button class="panel-launcher" id="pl-memory"        onclick="openPanel('memory')">&#x1F9E0; Memory</button>

  <div class="tb-sep"></div>

  <div id="vitals-bar">
    <div class="vital-chip"><span class="vc-lbl">CPU</span>&nbsp;<span class="vc-val" id="vital-cpu">&#x2014;%</span></div>
    <div class="vital-chip"><span class="vc-lbl">RAM</span>&nbsp;<span class="vc-val" id="vital-ram">&#x2014;%</span></div>
  </div>

  <div id="provider-badge" data-provider="">&#x26A1;&nbsp;<span id="provider-name">&#x2014;</span></div>

  <div id="jarvis-status-badge">
    <div class="jsbdot"></div>
    <span id="jarvis-status-text">ONLINE</span>
  </div>

  <div id="waveform"></div>

  <div id="voice-area">
    <span id="voice-label">Say &quot;Javris&hellip;&quot; or click mic</span>
    <div id="voice-ring" onclick="toggleVoice()" title="Click to start/stop voice">&#x1F3A4;</div>
    <div id="notif-btn" onclick="openPanel('notifications')">&#x1F514;<span id="notif-count"></span></div>
    <div class="tb-badge"><div class="dot idle" id="ai-dot"></div><span id="ai-label">&#x2014;</span></div>
    <div class="tb-badge"><div class="dot idle" id="cloud-dot"></div><span id="cloud-label">Cloud</span></div>
  </div>
</div>

<!-- ══ AMBIENT STRIP ══════════════════════════════════════════ -->
<div id="ambient-strip">
  <span id="ambient-text">JAVRIS OS &#x2014; SYSTEMS NOMINAL</span>
  <span id="ambient-time"></span>
</div>

<!-- ══ WORKSPACE ══════════════════════════════════════════════ -->
<div id="workspace">
  <div id="workspace-welcome">
    <div class="ww-inner">
      <div class="ww-ring">&#x1F916;</div>
      <div class="ww-title">JAVRIS OS</div>
      <div class="ww-sub">Click any panel above or say &quot;Javris, open chat&quot;</div>
    </div>
  </div>
</div>

<!-- ══ TASKBAR ══════════════════════════════════════════════== -->
<div id="taskbar"></div>

<!-- ══ VOICE BAR ══════════════════════════════════════════════ -->
<div id="voice-bar"></div>

<!-- ══ TOAST CONTAINER ════════════════════════════════════════ -->
<div id="toast-container"></div>

<!-- ══ GESTURE HUD ════════════════════════════════════════════ -->
<div id="gesture-hud" title="Gesture control">
  <div class="gh-row">
    <span class="gh-label"><span id="gesture-dot"></span>GESTURE</span>
    <span class="gh-value" id="gh-gesture">&#x2014;</span>
  </div>
  <div class="gh-action" id="gh-action">waiting...</div>
  <div id="gh-cursor-badge" class="gh-cursor-badge" style="display:none">CURSOR MODE</div>
</div>

'''

HTML_BOTTOM = '''
</script>
<script>
(function(){
  const el=document.getElementById('cin-clock');
  function tick(){
    const n=new Date();
    const t=n.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false});
    const d=n.toLocaleDateString([],{weekday:'short',month:'short',day:'numeric'});
    if(el) el.innerHTML=t+'<br>'+d;
  }
  tick();setInterval(tick,1000);
})();
</script>
<script src="/static/src/panels/trace.js"></script>
<script src="/static/src/panels/approvals.js"></script>
<script src="/static/src/panels/memory.js"></script>
</body>
</html>
'''

result = HTML_TOP + '<script>\n' + script_inner + HTML_BOTTOM

with open('S:/Javris/frontend/index.html', 'w', encoding='utf-8') as f:
    f.write(result)

print(f'Written {len(result.splitlines())} lines')
