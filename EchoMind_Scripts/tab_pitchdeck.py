import streamlit as st
import json
from utils import DB, _cortex, _sq, require_call, section_header

def _get_call_stats(session):
    """Pull live stats from DB for the presentation."""
    try:
        total = session.sql(f"SELECT COUNT(DISTINCT CALL_ID) AS N FROM {DB}.CALL_SEGMENTS").collect()[0]['N']
    except:
        total = 0
    try:
        segs = session.sql(f"SELECT COUNT(*) AS N FROM {DB}.CALL_SEGMENTS").collect()[0]['N']
    except:
        segs = 0
    try:
        km = session.sql(f"SELECT COUNT(*) AS N FROM {DB}.CALL_KEY_MOMENTS").collect()[0]['N']
    except:
        km = 0
    try:
        avg_s = session.sql(f"SELECT ROUND(AVG(SENTIMENT),2) AS S FROM {DB}.CALL_SEGMENTS").collect()[0]['S']
        avg_s = float(avg_s) if avg_s else 0.0
    except:
        avg_s = 0.0
    return total, segs, km, avg_s

def _get_active_call_data(session, call_id):
    """Pull active call insights for the presentation."""
    diagnosis, resolution, csat, lead, issue, km_types = "", "N/A", "N/A", 50, "N/A", []
    try:
        ins = session.sql(f"SELECT * FROM {DB}.CALL_INSIGHTS WHERE CALL_ID='{call_id}'").to_pandas()
        if len(ins) > 0:
            row        = ins.iloc[0]
            resolution = row.get('RESOLUTION_STATUS','N/A') or 'N/A'
            csat       = row.get('CSAT_INDICATOR','N/A') or 'N/A'
            lead       = int(row.get('LEAD_INTENT_SCORE', 50) or 50)
            issue      = row.get('ISSUE_TYPE','N/A') or 'N/A'
    except:
        pass
    try:
        km = session.sql(f"SELECT MOMENT_TYPE, COUNT(*) AS N FROM {DB}.CALL_KEY_MOMENTS WHERE CALL_ID='{call_id}' GROUP BY MOMENT_TYPE ORDER BY N DESC LIMIT 4").to_pandas()
        km_types = km['MOMENT_TYPE'].tolist()
    except:
        pass
    try:
        diag_key = f"diag_{call_id}"
        if st.session_state.get(diag_key):
            diagnosis = st.session_state[diag_key]
        else:
            seg_df = session.sql(f"SELECT COALESCE(SPEAKER_ROLE,SPEAKER) AS SPK, SEGMENT_TEXT FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{call_id}' ORDER BY START_TIME LIMIT 30").to_pandas()
            tx = "\n".join([f"{r['SPK']}: {r['SEGMENT_TEXT']}" for _, r in seg_df.iterrows()])[:3000]
            prompt = f"In 2 sentences max, diagnose this call: what went wrong and what's the key risk.\n\nTranscript:\n{tx}"
            diagnosis = _cortex(session, prompt)
    except:
        diagnosis = "AI-powered diagnosis available after processing a call."
    return diagnosis, resolution, csat, lead, issue, km_types

def _build_html(total_calls, total_segs, total_km, avg_sent,
                call_id, diagnosis, resolution, csat, lead, issue, km_types):
    """Build the full animated HTML presentation."""

    res_color  = {"Resolved":"#22c55e","Unresolved":"#ef4444","Partial":"#f59e0b","Escalated":"#f97316","N/A":"#94a3b8"}.get(resolution,"#94a3b8")
    csat_color = {"Positive":"#22c55e","Neutral":"#f59e0b","Negative":"#ef4444","N/A":"#94a3b8"}.get(csat,"#94a3b8")
    lead_color = "#22c55e" if lead >= 70 else "#f59e0b" if lead >= 40 else "#ef4444"
    sent_color = "#22c55e" if avg_sent > 0.1 else "#ef4444" if avg_sent < -0.1 else "#f59e0b"

    # Key moment icon mapping
    mi = {'Frustration':'😤','Escalation_Request':'🔺','Complaint':'😠',
          'Buying_Signal':'💰','Resolution':'✅','Positive_Feedback':'😊','Objection':'🚧'}
    km_html = "".join([
        f"<div class='km-badge'>{mi.get(t,'📌')} {t}</div>"
        for t in km_types
    ]) if km_types else "<div class='km-badge'>⭐ Process a call to see key moments</div>"

    diagnosis_safe = diagnosis.replace('<','&lt;').replace('>','&gt;').replace('"','&quot;')
    issue_safe     = issue.replace('<','&lt;').replace('>','&gt;')
    call_id_safe   = call_id.replace('<','&lt;').replace('>','&gt;')

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>EchoMind — Cocothon Pitch</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:'Segoe UI',system-ui,sans-serif; background:#0f172a; color:#fff; overflow:hidden; }}

  .deck {{ width:100vw; height:100vh; position:relative; }}
  .slide {{
    position:absolute; top:0; left:0; width:100%; height:100%;
    display:flex; flex-direction:column; justify-content:center; align-items:center;
    padding:48px; opacity:0; pointer-events:none;
    transition:opacity 0.6s ease, transform 0.6s ease;
    transform:translateY(30px);
  }}
  .slide.active {{ opacity:1; pointer-events:all; transform:translateY(0); }}

  /* Navigation */
  .nav {{
    position:fixed; bottom:32px; left:50%; transform:translateX(-50%);
    display:flex; gap:12px; align-items:center; z-index:100;
    background:rgba(255,255,255,0.08); backdrop-filter:blur(12px);
    border-radius:99px; padding:10px 24px; border:1px solid rgba(255,255,255,0.12);
  }}
  .nav button {{
    background:rgba(255,255,255,0.15); border:none; color:#fff;
    width:36px; height:36px; border-radius:50%; cursor:pointer;
    font-size:16px; transition:all 0.2s;
  }}
  .nav button:hover {{ background:rgba(255,255,255,0.3); }}
  .nav button.active-dot {{ background:#3b82f6; }}
  .slide-counter {{ color:#94a3b8; font-size:13px; min-width:60px; text-align:center; }}
  .nav-arrow {{
    background:rgba(255,255,255,0.1); border:1px solid rgba(255,255,255,0.2);
    color:#fff; padding:8px 20px; border-radius:99px; cursor:pointer;
    font-size:14px; font-weight:600; transition:all 0.2s;
  }}
  .nav-arrow:hover {{ background:rgba(59,130,246,0.4); border-color:#3b82f6; }}

  /* Progress bar */
  .progress {{
    position:fixed; top:0; left:0; height:3px;
    background:linear-gradient(90deg,#3b82f6,#8b5cf6);
    transition:width 0.4s ease; z-index:200;
  }}

  /* Slide number */
  .slide-num {{
    position:fixed; top:20px; right:28px;
    color:rgba(255,255,255,0.3); font-size:12px; z-index:100;
    font-weight:600; letter-spacing:1px;
  }}

  /* Typography */
  .eyebrow {{ font-size:11px; font-weight:700; letter-spacing:2px; text-transform:uppercase; color:#3b82f6; margin-bottom:12px; }}
  .hero-title {{ font-size:72px; font-weight:900; letter-spacing:-2px; line-height:1; }}
  .hero-sub {{ font-size:20px; color:#94a3b8; margin-top:16px; max-width:600px; text-align:center; line-height:1.6; }}
  .section-title {{ font-size:44px; font-weight:800; letter-spacing:-1px; margin-bottom:8px; }}
  .section-sub {{ font-size:17px; color:#94a3b8; margin-bottom:40px; }}

  /* Cards */
  .card {{
    background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.1);
    border-radius:16px; padding:24px 28px;
  }}
  .card-grid {{ display:grid; gap:16px; width:100%; max-width:960px; }}
  .card-grid-2 {{ grid-template-columns:1fr 1fr; }}
  .card-grid-3 {{ grid-template-columns:1fr 1fr 1fr; }}
  .card-grid-4 {{ grid-template-columns:1fr 1fr 1fr 1fr; }}

  /* Stat cards */
  .stat-card {{
    background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.1);
    border-radius:16px; padding:24px; text-align:center;
  }}
  .stat-val {{ font-size:48px; font-weight:900; letter-spacing:-1px; }}
  .stat-label {{ font-size:13px; color:#94a3b8; margin-top:4px; font-weight:600; text-transform:uppercase; letter-spacing:0.5px; }}

  /* KPI pill */
  .kpi-pill {{
    display:inline-flex; align-items:center; gap:8px;
    padding:8px 18px; border-radius:99px; font-weight:700; font-size:14px;
  }}

  /* Key moment badge */
  .km-badge {{
    background:rgba(239,68,68,0.15); border:1px solid rgba(239,68,68,0.3);
    border-radius:8px; padding:8px 16px; font-size:14px; font-weight:600;
    display:inline-block; margin:4px;
  }}

  /* Source grid */
  .source-item {{
    background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.1);
    border-radius:12px; padding:14px 16px; display:flex; align-items:center; gap:10px;
    font-size:13px; font-weight:600;
  }}

  /* Gradient text */
  .grad {{ background:linear-gradient(135deg,#3b82f6,#8b5cf6,#ec4899); -webkit-background-clip:text; -webkit-text-fill-color:transparent; background-clip:text; }}
  .grad-green {{ background:linear-gradient(135deg,#10b981,#3b82f6); -webkit-background-clip:text; -webkit-text-fill-color:transparent; background-clip:text; }}

  /* Slide backgrounds */
  .bg-hero {{ background:radial-gradient(ellipse at 30% 50%,#1e3a5f 0%,#0f172a 60%); }}
  .bg-problem {{ background:radial-gradient(ellipse at 70% 30%,#1a1a2e 0%,#0f172a 70%); }}
  .bg-stats {{ background:radial-gradient(ellipse at 50% 50%,#0d2137 0%,#0f172a 60%); }}
  .bg-diagnosis {{ background:radial-gradient(ellipse at 20% 60%,#1e1b4b 0%,#0f172a 70%); }}
  .bg-moments {{ background:radial-gradient(ellipse at 80% 40%,#2d1515 0%,#0f172a 70%); }}
  .bg-kpis {{ background:radial-gradient(ellipse at 40% 60%,#0d2d1e 0%,#0f172a 70%); }}
  .bg-sources {{ background:radial-gradient(ellipse at 60% 30%,#1a0d2e 0%,#0f172a 70%); }}
  .bg-win {{ background:radial-gradient(ellipse at 50% 50%,#0f2d1e 0%,#0f172a 60%); }}

  /* Animations */
  @keyframes float {{ 0%,100%{{transform:translateY(0)}} 50%{{transform:translateY(-8px)}} }}
  @keyframes pulse-ring {{ 0%{{transform:scale(1);opacity:0.4}} 100%{{transform:scale(1.4);opacity:0}} }}
  @keyframes countup {{ from{{opacity:0;transform:translateY(20px)}} to{{opacity:1;transform:translateY(0)}} }}
  .float {{ animation:float 4s ease-in-out infinite; }}
  .anim-in {{ animation:countup 0.5s ease forwards; }}

  .tag {{
    display:inline-block; background:rgba(59,130,246,0.15);
    border:1px solid rgba(59,130,246,0.3); border-radius:6px;
    padding:4px 12px; font-size:12px; font-weight:600; color:#93c5fd;
    margin:3px;
  }}

  .divider {{ width:60px; height:3px; background:linear-gradient(90deg,#3b82f6,#8b5cf6); border-radius:99px; margin:16px auto; }}

  .quote-box {{
    background:rgba(59,130,246,0.08); border-left:4px solid #3b82f6;
    border-radius:0 12px 12px 0; padding:20px 24px;
    font-size:15px; line-height:1.7; color:#cbd5e1; font-style:italic;
    max-width:800px; text-align:left;
  }}

  .win-item {{
    display:flex; align-items:flex-start; gap:14px;
    padding:16px 20px; background:rgba(255,255,255,0.04);
    border:1px solid rgba(255,255,255,0.08); border-radius:12px; margin-bottom:10px;
  }}
  .win-icon {{ font-size:24px; flex-shrink:0; margin-top:2px; }}
  .win-title {{ font-weight:700; font-size:15px; margin-bottom:2px; }}
  .win-desc {{ font-size:13px; color:#94a3b8; }}
</style>
</head>
<body>

<div class="progress" id="progress"></div>
<div class="slide-num" id="slideNum">1 / 8</div>

<div class="deck" id="deck">

  <!-- SLIDE 1: HERO -->
  <div class="slide bg-hero active" id="s1">
    <div style="text-align:center;">
      <div class="eyebrow">Cocothon 2024 · Built on Snowflake Cortex AI</div>
      <div class="hero-title float">
        <span class="grad">EchoMind</span>
      </div>
      <div class="divider"></div>
      <div class="hero-sub">
        Turn every customer conversation into intelligence.<br>
        11 input types · Real-time AI analysis · Actionable insights.
      </div>
      <div style="margin-top:36px; display:flex; gap:12px; flex-wrap:wrap; justify-content:center;">
        <span class="tag">🎙️ Call Recordings</span>
        <span class="tag">💬 Chat / WhatsApp</span>
        <span class="tag">📧 Emails</span>
        <span class="tag">🎫 Tickets</span>
        <span class="tag">⭐ Surveys</span>
        <span class="tag">📋 CRM Notes</span>
        <span class="tag">🌐 Reviews</span>
        <span class="tag">🎤 Voice Notes</span>
        <span class="tag">📊 Product Usage</span>
        <span class="tag">📞 Metadata</span>
        <span class="tag">📚 Knowledge Base</span>
      </div>
    </div>
  </div>

  <!-- SLIDE 2: PROBLEM -->
  <div class="slide bg-problem" id="s2">
    <div style="max-width:860px; width:100%;">
      <div class="eyebrow">The Problem</div>
      <div class="section-title">Businesses are <span class="grad">flying blind</span><br>on customer conversations.</div>
      <div class="divider" style="margin:20px 0;"></div>
      <div class="card-grid card-grid-3" style="margin-top:32px;">
        <div class="card" style="border-color:rgba(239,68,68,0.3);background:rgba(239,68,68,0.05);">
          <div style="font-size:36px; margin-bottom:12px;">📞</div>
          <div style="font-weight:700; font-size:16px; margin-bottom:6px;">80% of calls unanalysed</div>
          <div style="font-size:13px; color:#94a3b8;">Most businesses review less than 2% of customer calls. The rest? Lost intelligence.</div>
        </div>
        <div class="card" style="border-color:rgba(245,158,11,0.3);background:rgba(245,158,11,0.05);">
          <div style="font-size:36px; margin-bottom:12px;">🔍</div>
          <div style="font-weight:700; font-size:16px; margin-bottom:6px;">Siloed data sources</div>
          <div style="font-size:13px; color:#94a3b8;">Calls, chats, emails, tickets, CRM — all separate. No unified view of the customer.</div>
        </div>
        <div class="card" style="border-color:rgba(139,92,246,0.3);background:rgba(139,92,246,0.05);">
          <div style="font-size:36px; margin-bottom:12px;">⏰</div>
          <div style="font-weight:700; font-size:16px; margin-bottom:6px;">Insights arrive too late</div>
          <div style="font-size:13px; color:#94a3b8;">By the time trends are spotted manually, customers have already churned.</div>
        </div>
      </div>
      <div class="quote-box" style="margin-top:24px;">
        "Companies that analyse customer conversations see 20-30% improvement in CSAT scores and 15% reduction in churn — yet most still rely on manual spot-checks."
      </div>
    </div>
  </div>

  <!-- SLIDE 3: LIVE STATS -->
  <div class="slide bg-stats" id="s3">
    <div style="text-align:center; max-width:900px; width:100%;">
      <div class="eyebrow">Live Data — From This Demo</div>
      <div class="section-title">EchoMind in <span class="grad">action</span></div>
      <div class="section-sub">Real numbers from calls processed right now in this session</div>
      <div class="card-grid card-grid-4" style="margin-top:8px;">
        <div class="stat-card">
          <div class="stat-val grad">{total_calls}</div>
          <div class="stat-label">Calls Analysed</div>
        </div>
        <div class="stat-card">
          <div class="stat-val" style="color:#8b5cf6;">{total_segs}</div>
          <div class="stat-label">Segments Processed</div>
        </div>
        <div class="stat-card">
          <div class="stat-val" style="color:#f59e0b;">{total_km}</div>
          <div class="stat-label">Key Moments Detected</div>
        </div>
        <div class="stat-card">
          <div class="stat-val" style="color:{sent_color};">{avg_sent:+.2f}</div>
          <div class="stat-label">Avg Sentiment Score</div>
        </div>
      </div>
      <div style="margin-top:28px;" class="card">
        <div style="font-size:14px; color:#94a3b8; margin-bottom:16px; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">What happens when you upload a call</div>
        <div style="display:flex; align-items:center; gap:0; flex-wrap:wrap; justify-content:center;">
          <div style="display:flex;align-items:center;gap:0;flex-wrap:wrap;justify-content:center;">
            <div style="background:rgba(59,130,246,0.15);border:1px solid rgba(59,130,246,0.3);border-radius:8px;padding:8px 14px;font-size:13px;font-weight:600;">Upload</div>
            <div style="color:#64748b;padding:0 6px;font-size:18px;">→</div>
            <div style="background:rgba(59,130,246,0.15);border:1px solid rgba(59,130,246,0.3);border-radius:8px;padding:8px 14px;font-size:13px;font-weight:600;">Transcribe</div>
            <div style="color:#64748b;padding:0 6px;font-size:18px;">→</div>
            <div style="background:rgba(59,130,246,0.15);border:1px solid rgba(59,130,246,0.3);border-radius:8px;padding:8px 14px;font-size:13px;font-weight:600;">Diarise</div>
            <div style="color:#64748b;padding:0 6px;font-size:18px;">→</div>
            <div style="background:rgba(59,130,246,0.15);border:1px solid rgba(59,130,246,0.3);border-radius:8px;padding:8px 14px;font-size:13px;font-weight:600;">Sentiment</div>
            <div style="color:#64748b;padding:0 6px;font-size:18px;">→</div>
            <div style="background:rgba(59,130,246,0.15);border:1px solid rgba(59,130,246,0.3);border-radius:8px;padding:8px 14px;font-size:13px;font-weight:600;">Topics</div>
            <div style="color:#64748b;padding:0 6px;font-size:18px;">→</div>
            <div style="background:rgba(59,130,246,0.15);border:1px solid rgba(59,130,246,0.3);border-radius:8px;padding:8px 14px;font-size:13px;font-weight:600;">KPIs</div>
            <div style="color:#64748b;padding:0 6px;font-size:18px;">→</div>
            <div style="background:rgba(59,130,246,0.15);border:1px solid rgba(59,130,246,0.3);border-radius:8px;padding:8px 14px;font-size:13px;font-weight:600;">Coaching</div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- SLIDE 4: AI DIAGNOSIS -->
  <div class="slide bg-diagnosis" id="s4">
    <div style="max-width:860px; width:100%;">
      <div class="eyebrow">Active Call · {call_id_safe}</div>
      <div class="section-title">AI <span class="grad">Diagnosis</span></div>
      <div class="divider" style="margin:16px 0;"></div>
      <div class="quote-box" style="font-size:17px; line-height:1.8; font-style:normal; color:#e2e8f0; margin-bottom:28px;">
        🧠 {diagnosis_safe}
      </div>
      <div class="card-grid card-grid-3">
        <div class="card" style="text-align:center;">
          <div style="font-size:13px;color:#94a3b8;margin-bottom:8px;text-transform:uppercase;letter-spacing:0.5px;">Resolution</div>
          <div class="kpi-pill" style="background:rgba(0,0,0,0.2);border:1px solid {res_color}33;color:{res_color};font-size:18px;font-weight:800;">
            {resolution}
          </div>
        </div>
        <div class="card" style="text-align:center;">
          <div style="font-size:13px;color:#94a3b8;margin-bottom:8px;text-transform:uppercase;letter-spacing:0.5px;">CSAT</div>
          <div class="kpi-pill" style="background:rgba(0,0,0,0.2);border:1px solid {csat_color}33;color:{csat_color};font-size:18px;font-weight:800;">
            {csat}
          </div>
        </div>
        <div class="card" style="text-align:center;">
          <div style="font-size:13px;color:#94a3b8;margin-bottom:8px;text-transform:uppercase;letter-spacing:0.5px;">Issue Type</div>
          <div style="font-size:16px;font-weight:700;color:#e2e8f0;word-break:break-word;">{issue_safe}</div>
        </div>
      </div>
    </div>
  </div>

  <!-- SLIDE 5: KEY MOMENTS -->
  <div class="slide bg-moments" id="s5">
    <div style="max-width:860px; width:100%; text-align:center;">
      <div class="eyebrow">Intelligence Layer</div>
      <div class="section-title">Key Moment <span style="color:#ef4444;">Detection</span></div>
      <div class="section-sub">Critical events automatically flagged — frustration, escalation, buying signals and more</div>
      <div style="margin:24px 0;">
        {km_html}
      </div>
      <div class="card-grid card-grid-3" style="margin-top:20px;">
        <div class="card" style="border-color:rgba(239,68,68,0.3);">
          <div style="font-size:28px; margin-bottom:8px;">😤</div>
          <div style="font-weight:700; margin-bottom:4px;">Frustration</div>
          <div style="font-size:12px;color:#94a3b8;">Detected automatically with severity scoring — High / Medium / Low</div>
        </div>
        <div class="card" style="border-color:rgba(245,158,11,0.3);">
          <div style="font-size:28px; margin-bottom:8px;">🔺</div>
          <div style="font-weight:700; margin-bottom:4px;">Escalation</div>
          <div style="font-size:12px;color:#94a3b8;">Catches escalation requests before they become complaints</div>
        </div>
        <div class="card" style="border-color:rgba(34,197,94,0.3);">
          <div style="font-size:28px; margin-bottom:8px;">💰</div>
          <div style="font-weight:700; margin-bottom:4px;">Buying Signal</div>
          <div style="font-size:12px;color:#94a3b8;">Identifies purchase intent and upsell opportunities in real time</div>
        </div>
      </div>
    </div>
  </div>

  <!-- SLIDE 6: KPI DASHBOARD -->
  <div class="slide bg-kpis" id="s6">
    <div style="max-width:900px; width:100%;">
      <div class="eyebrow">Structured Analytics</div>
      <div class="section-title">Instant <span class="grad-green">KPI Dashboard</span></div>
      <div class="section-sub">Every conversation scored, classified and benchmarked automatically</div>
      <div class="card-grid card-grid-4" style="margin-bottom:16px;">
        <div class="stat-card" style="border-color:{res_color}33;">
          <div style="font-size:13px;color:#94a3b8;margin-bottom:8px;">Resolution</div>
          <div style="font-size:20px;font-weight:800;color:{res_color};">{resolution}</div>
        </div>
        <div class="stat-card" style="border-color:{csat_color}33;">
          <div style="font-size:13px;color:#94a3b8;margin-bottom:8px;">CSAT</div>
          <div style="font-size:20px;font-weight:800;color:{csat_color};">{csat}</div>
        </div>
        <div class="stat-card" style="border-color:{lead_color}33;">
          <div style="font-size:13px;color:#94a3b8;margin-bottom:8px;">Lead Score</div>
          <div style="font-size:28px;font-weight:900;color:{lead_color};">{lead}<span style="font-size:14px;">/100</span></div>
          <div style="background:#1e293b;border-radius:99px;height:6px;margin-top:8px;">
            <div style="background:{lead_color};width:{lead}%;height:6px;border-radius:99px;"></div>
          </div>
        </div>
        <div class="stat-card">
          <div style="font-size:13px;color:#94a3b8;margin-bottom:8px;">Avg Sentiment</div>
          <div style="font-size:28px;font-weight:900;color:{sent_color};">{avg_sent:+.2f}</div>
        </div>
      </div>
      <div class="card-grid card-grid-3">
        <div class="card">
          <div style="font-size:13px;color:#3b82f6;font-weight:700;margin-bottom:8px;">🎯 COACHING REPORT</div>
          <div style="font-size:13px;color:#94a3b8;">What went wrong · Why it matters · What to say instead — automatically generated for every call</div>
        </div>
        <div class="card">
          <div style="font-size:13px;color:#8b5cf6;font-weight:700;margin-bottom:8px;">📧 FOLLOW-UP EMAIL</div>
          <div style="font-size:13px;color:#94a3b8;">AI drafts a professional follow-up email based on call outcome, action items, and next steps</div>
        </div>
        <div class="card">
          <div style="font-size:13px;color:#10b981;font-weight:700;margin-bottom:8px;">💬 ASK ECHOMIND</div>
          <div style="font-size:13px;color:#94a3b8;">Chat with AI about any call — ask questions, get summaries, probe insights instantly</div>
        </div>
      </div>
    </div>
  </div>

  <!-- SLIDE 7: 11 INPUT SOURCES -->
  <div class="slide bg-sources" id="s7">
    <div style="max-width:900px; width:100%; text-align:center;">
      <div class="eyebrow">Multi-Modal Intelligence</div>
      <div class="section-title"><span class="grad">11 Input Types</span></div>
      <div class="section-sub">One platform. Every customer touchpoint. All analysed the same way.</div>
      <div class="card-grid" style="grid-template-columns:repeat(4,1fr); gap:10px; margin-top:8px;">
        <div class="source-item">🎙️ Call Recordings</div>
        <div class="source-item">💬 Chat / WhatsApp</div>
        <div class="source-item">📧 Email Threads</div>
        <div class="source-item">🎫 Support Tickets</div>
        <div class="source-item">⭐ Surveys & NPS</div>
        <div class="source-item">📋 CRM Notes</div>
        <div class="source-item">🌐 Social Reviews</div>
        <div class="source-item">🎤 Voice Notes</div>
        <div class="source-item">📊 Product Usage</div>
        <div class="source-item">📞 Call Metadata</div>
        <div class="source-item">📚 Knowledge Base</div>
        <div class="source-item" style="border-color:rgba(59,130,246,0.4);color:#93c5fd;">+ More coming</div>
      </div>
      <div class="card" style="margin-top:16px; text-align:left;">
        <div style="font-size:13px; color:#94a3b8;">
          All sources feed into the <strong style="color:#fff;">same AI pipeline</strong> — transcription → sentiment → topics → key moments → KPIs → coaching → follow-up.
          Built natively on <strong style="color:#29b5e8;">Snowflake Cortex AI</strong> with zero data leaving your warehouse.
        </div>
      </div>
    </div>
  </div>

  <!-- SLIDE 8: WHY ECHOMIND WINS -->
  <div class="slide bg-win" id="s8">
    <div style="max-width:820px; width:100%;">
      <div class="eyebrow">Why EchoMind Wins</div>
      <div class="section-title">Built to <span class="grad-green">win Cocothon</span></div>
      <div style="margin-top:24px;">
        <div class="win-item">
          <div class="win-icon">❄️</div>
          <div>
            <div class="win-title">100% Snowflake Native</div>
            <div class="win-desc">Cortex AI, Snowpark, Streamlit in Snowflake — no external APIs, no data leaving the warehouse, enterprise-grade security built in.</div>
          </div>
        </div>
        <div class="win-item">
          <div class="win-icon">🧠</div>
          <div>
            <div class="win-title">End-to-End AI Pipeline</div>
            <div class="win-desc">From raw audio to actionable coaching report in under 60 seconds. Speaker detection, sentiment, topics, KPIs, key moments — fully automated.</div>
          </div>
        </div>
        <div class="win-item">
          <div class="win-icon">🎯</div>
          <div>
            <div class="win-title">11 Input Types — Widest Coverage</div>
            <div class="win-desc">Audio, chat, email, tickets, surveys, CRM, reviews, voice notes, product data, metadata, knowledge base. No other tool covers this breadth.</div>
          </div>
        </div>
        <div class="win-item">
          <div class="win-icon">⚡</div>
          <div>
            <div class="win-title">Demo-Ready, Production-Ready</div>
            <div class="win-desc">Live data. Real results. Every tab works with actual processed calls — this presentation is generated from real-time Snowflake queries.</div>
          </div>
        </div>
      </div>
    </div>
  </div>

</div>

<!-- Navigation -->
<div class="nav">
  <button class="nav-arrow" onclick="changeSlide(-1)">← Prev</button>
  <span class="slide-counter" id="counter">1 / 8</span>
  <button class="nav-arrow" onclick="changeSlide(1)">Next →</button>
</div>

<script>
  const total  = 8;
  let current  = 1;

  function showSlide(n) {{
    document.querySelectorAll('.slide').forEach(s => s.classList.remove('active'));
    document.getElementById('s' + n).classList.add('active');
    document.getElementById('progress').style.width = (n / total * 100) + '%';
    document.getElementById('slideNum').textContent  = n + ' / ' + total;
    document.getElementById('counter').textContent   = n + ' / ' + total;
    current = n;
  }}

  function changeSlide(dir) {{
    let next = current + dir;
    if (next < 1) next = total;
    if (next > total) next = 1;
    showSlide(next);
  }}

  // Keyboard navigation
  document.addEventListener('keydown', e => {{
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown' || e.key === ' ') changeSlide(1);
    if (e.key === 'ArrowLeft'  || e.key === 'ArrowUp')                    changeSlide(-1);
  }});

  // Auto-advance option (disabled by default)
  // setInterval(() => changeSlide(1), 8000);

  showSlide(1);
</script>
</body>
</html>"""


def render(session):
    section_header("🎬", "Pitch Deck", "Animated HTML presentation — ready for Cocothon demo")

    st.caption("Full-screen animated presentation generated from your live call data. Use arrow keys or buttons to navigate.")

    # ── Controls ─────────────────────────────────────────────────────────────
    col1, col2, col3 = st.columns([2,2,2])
    with col1:
        call_id = st.session_state.get('last_call_id','DEMO_CALL')
        st.metric("Active call", call_id or "None loaded")
    with col2:
        total_calls, total_segs, total_km, avg_sent = _get_call_stats(session)
        st.metric("Total calls in DB", total_calls)
    with col3:
        if st.button("🔄 Regenerate Deck", key="regen_deck", type="primary", use_container_width=True):
            if 'pitch_html' in st.session_state:
                del st.session_state['pitch_html']
            st.rerun()

    st.divider()

    # ── Generate HTML ─────────────────────────────────────────────────────────
    if 'pitch_html' not in st.session_state:
        with st.spinner("🎬 Building your pitch deck from live call data..."):
            if call_id and call_id != 'DEMO_CALL':
                diagnosis, resolution, csat, lead, issue, km_types = _get_active_call_data(session, call_id)
            else:
                diagnosis  = "Upload and process a call to see live AI diagnosis in your pitch deck."
                resolution = "N/A"
                csat       = "N/A"
                lead       = 0
                issue      = "N/A"
                km_types   = []

            st.session_state['pitch_html'] = _build_html(
                total_calls, total_segs, total_km, avg_sent,
                call_id or "DEMO", diagnosis, resolution, csat, lead, issue, km_types
            )

    # ── Render presentation ───────────────────────────────────────────────────
    st.components.v1.html(
        st.session_state['pitch_html'],
        height=700,
        scrolling=False
    )

    st.divider()

    # ── Download ──────────────────────────────────────────────────────────────
    st.download_button(
        "⬇️ Download as standalone HTML file",
        data=st.session_state['pitch_html'],
        file_name="echomind_pitchdeck.html",
        mime="text/html",
        key="dl_pitchdeck",
        help="Download and open in any browser for full-screen presentation mode"
    )
    st.caption("💡 **Tip:** Download the HTML file and open it in Chrome for full-screen mode (F11). Use ← → arrow keys to navigate slides.")