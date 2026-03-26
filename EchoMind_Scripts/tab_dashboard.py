import streamlit as st
import pandas as pd
from utils import DB, _cortex, require_call, section_header

def render(session):
    if not require_call("Call Dashboard"):
        return

    call_id = st.session_state['last_call_id']
    seg_df  = session.sql(f"SELECT * FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{call_id}' ORDER BY START_TIME").to_pandas()
    ins_df  = session.sql(f"SELECT * FROM {DB}.CALL_INSIGHTS WHERE CALL_ID='{call_id}'").to_pandas()
    km_df   = session.sql(f"SELECT * FROM {DB}.CALL_KEY_MOMENTS WHERE CALL_ID='{call_id}' ORDER BY START_TIME").to_pandas()

    if len(seg_df) == 0:
        st.warning("No data found. Please re-process this call.")
        return

    # ── AI Diagnosis hero ────────────────────────────────────────────────────
    diag_key = f"diag_{call_id}"
    if diag_key not in st.session_state:
        with st.spinner("🧠 Generating AI diagnosis..."):
            tx_lines = [f"{r.get('SPEAKER_ROLE') or r.get('SPEAKER','?')}: {r['SEGMENT_TEXT']}" for _, r in seg_df.iterrows()]
            ins_ctx = ""
            if len(ins_df) > 0:
                row = ins_df.iloc[0]
                ins_ctx = (f" Resolution={row.get('RESOLUTION_STATUS','?')},"
                           f" Escalation={row.get('ESCALATION_FLAG','?')},"
                           f" CSAT={row.get('CSAT_INDICATOR','?')},"
                           f" Issue={row.get('ISSUE_TYPE','?')}.")
            prompt = (
                f"You are an expert call analyst. In exactly 3 sentences, diagnose this call.{ins_ctx} "
                f"Sentence 1: core problem. Sentence 2: agent effectiveness. Sentence 3: key risk or opportunity.\n\n"
                f"Transcript:\n" + "\n".join(tx_lines[:40])
            )
            st.session_state[diag_key] = _cortex(session, prompt)

    st.markdown(f"""
    <div style='background:linear-gradient(135deg,#1e3a5f,#2563eb);
                border-radius:14px;padding:24px 28px;margin-bottom:24px;'>
        <div style='color:#93c5fd;font-size:12px;font-weight:700;letter-spacing:1px;text-transform:uppercase;'>
            🧠 AI DIAGNOSIS — {call_id}
        </div>
        <div style='color:#fff;font-size:15px;line-height:1.7;margin-top:10px;'>
            {st.session_state[diag_key]}
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── KPI row ──────────────────────────────────────────────────────────────
    dur      = seg_df['END_TIME'].max()
    avg_sent = seg_df['SENTIMENT'].mean()
    lead     = int(ins_df['LEAD_INTENT_SCORE'].iloc[0]) if len(ins_df) > 0 else 0
    neg_pct  = (seg_df['SENTIMENT'] < -0.2).sum() / len(seg_df) * 100

    k1,k2,k3,k4,k5,k6 = st.columns(6)
    metrics = [
        (k1, "⏱️", "Duration",      f"{int(dur//60)}m {int(dur%60)}s", None),
        (k2, "💬", "Segments",      str(len(seg_df)),                  None),
        (k3, "⭐", "Key Moments",   str(len(km_df)),                   None),
        (k4, "🎯", "Lead Score",    f"{lead}/100",                     None),
        (k5, "😐", "Avg Sentiment", f"{avg_sent:.2f}",                 None),
        (k6, "📉", "Neg Segments",  f"{neg_pct:.1f}%",                 None),
    ]
    for col, icon, label, value, _ in metrics:
        with col:
            with st.container(border=True):
                st.metric(f"{icon} {label}", value)

    # ── Structured KPIs ──────────────────────────────────────────────────────
    if len(ins_df) > 0 and ins_df.iloc[0].get('RESOLUTION_STATUS'):
        row = ins_df.iloc[0]
        st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
        section_header("📊", "Structured KPIs")

        res   = row.get('RESOLUTION_STATUS','N/A')
        csat  = row.get('CSAT_INDICATOR','N/A')
        esc   = bool(row.get('ESCALATION_FLAG'))
        ri    = {"Resolved":"✅","Unresolved":"❌","Partial":"🟡","Escalated":"🔺"}.get(res,"❓")
        ci    = {"Positive":"😊","Neutral":"😐","Negative":"😞"}.get(csat,"❓")
        ei    = "🔺 Yes" if esc else "✅ No"
        esc_color = "#fef2f2" if esc else "#f0fdf4"
        esc_border= "#fca5a5" if esc else "#86efac"

        q1,q2,q3,q4 = st.columns(4)
        with q1:
            st.markdown(f"""<div style='background:#f0f9ff;border:1px solid #bae6fd;border-radius:10px;
                padding:14px;text-align:center;'>
                <div style='font-size:22px;'>{ri}</div>
                <div style='font-weight:700;font-size:13px;color:#0369a1;margin-top:4px;'>Resolution</div>
                <div style='font-size:15px;font-weight:800;color:#0c4a6e;'>{res}</div>
            </div>""", unsafe_allow_html=True)
        with q2:
            st.markdown(f"""<div style='background:{esc_color};border:1px solid {esc_border};border-radius:10px;
                padding:14px;text-align:center;'>
                <div style='font-size:22px;'>{'🚨' if esc else '🟢'}</div>
                <div style='font-weight:700;font-size:13px;color:#991b1b;margin-top:4px;'>Escalation</div>
                <div style='font-size:15px;font-weight:800;'>{ei}</div>
            </div>""", unsafe_allow_html=True)
        with q3:
            st.markdown(f"""<div style='background:#fefce8;border:1px solid #fde68a;border-radius:10px;
                padding:14px;text-align:center;'>
                <div style='font-size:22px;'>{ci}</div>
                <div style='font-weight:700;font-size:13px;color:#92400e;margin-top:4px;'>CSAT</div>
                <div style='font-size:15px;font-weight:800;color:#78350f;'>{csat}</div>
            </div>""", unsafe_allow_html=True)
        with q4:
            st.markdown(f"""<div style='background:#f5f3ff;border:1px solid #c4b5fd;border-radius:10px;
                padding:14px;text-align:center;'>
                <div style='font-size:22px;'>🏷️</div>
                <div style='font-weight:700;font-size:13px;color:#5b21b6;margin-top:4px;'>Issue Type</div>
                <div style='font-size:14px;font-weight:800;color:#4c1d95;'>{row.get('ISSUE_TYPE','N/A')}</div>
            </div>""", unsafe_allow_html=True)

        if row.get('CALL_OUTCOME'):
            st.info(f"**📌 Outcome:** {row['CALL_OUTCOME']}")
        if row.get('ROOT_CAUSE') and str(row['ROOT_CAUSE']).lower() not in ['none','null','']:
            st.warning(f"**🔎 Root Cause:** {row['ROOT_CAUSE']}")

    st.divider()

    # ── Sentiment timeline ───────────────────────────────────────────────────
    section_header("📉", "Sentiment Timeline", "Sentiment progression across the call with key moment markers")
    chart_df = seg_df[['START_TIME','SENTIMENT']].copy().set_index('START_TIME')
    st.line_chart(chart_df, color=["#3b82f6"])
    if len(km_df) > 0:
        moment_str = "  ·  ".join([
            f"{'😤' if m['MOMENT_TYPE']=='Frustration' else '🔺' if 'Escalat' in m['MOMENT_TYPE'] else '📌'} "
            f"**{m['MOMENT_TYPE']}** @ {int(m['START_TIME']//60):02d}:{int(m['START_TIME']%60):02d}"
            for _, m in km_df.iterrows()
        ])
        st.caption(f"⚡ Key moments: {moment_str}")

    st.divider()

    # ── Key Moments visual cards ─────────────────────────────────────────────
    section_header("⭐", "Key Moments", "Critical events detected in this call")
    if len(km_df) == 0:
        st.caption("No key moments detected.")
    else:
        sev_cfg = {
            'high':   ('#fef2f2','#fca5a5','#991b1b','🔴'),
            'medium': ('#fefce8','#fde68a','#92400e','🟡'),
            'low':    ('#f0fdf4','#86efac','#166534','🟢'),
        }
        mi = {'Frustration':'😤','Escalation_Request':'🔺','Complaint':'😠',
              'Buying_Signal':'💰','Resolution':'✅','Positive_Feedback':'😊','Objection':'🚧'}

        for mtype in km_df['MOMENT_TYPE'].unique():
            grp  = km_df[km_df['MOMENT_TYPE'] == mtype]
            icon = mi.get(mtype,'📌')
            is_critical = mtype in ['Frustration','Escalation_Request','Complaint']
            with st.expander(f"{icon} **{mtype}** — {len(grp)} occurrence(s)", expanded=is_critical):
                for _, m in grp.iterrows():
                    sev    = m.get('SEVERITY','low')
                    bg,bd,tc,dot = sev_cfg.get(sev, ('#f8fafc','#e2e8f0','#334155','⚪'))
                    mm, ss = int(m['START_TIME']//60), int(m['START_TIME']%60)
                    dur    = m['END_TIME'] - m['START_TIME']
                    st.markdown(f"""
                    <div style='background:{bg};border-left:4px solid {bd};border-radius:8px;
                                padding:12px 16px;margin-bottom:8px;'>
                        <div style='display:flex;justify-content:space-between;align-items:center;'>
                            <span style='font-weight:700;color:{tc};'>{dot} {mtype}</span>
                            <span style='color:#64748b;font-size:12px;'>⏱ {mm:02d}:{ss:02d} · {dur:.1f}s</span>
                        </div>
                        <div style='color:#334155;margin-top:6px;font-size:13px;line-height:1.5;'>
                            {m['SEGMENT_TEXT'][:200]}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

        st.markdown("**Moment distribution:**")
        st.bar_chart(km_df['MOMENT_TYPE'].value_counts())
