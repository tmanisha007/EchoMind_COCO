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
            ins_ctx  = ""
            if len(ins_df) > 0:
                row     = ins_df.iloc[0]
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

    st.info(f"🧠 **AI Diagnosis — {call_id}**\n\n{st.session_state[diag_key]}")

    # ── KPI row ──────────────────────────────────────────────────────────────
    dur      = seg_df['END_TIME'].max()
    avg_sent = seg_df['SENTIMENT'].mean()
    lead     = int(ins_df['LEAD_INTENT_SCORE'].iloc[0]) if len(ins_df) > 0 else 0
    neg_pct  = (seg_df['SENTIMENT'] < -0.2).sum() / len(seg_df) * 100

    k1,k2,k3,k4,k5,k6 = st.columns(6)
    with k1:
        with st.container(border=True): st.metric("⏱️ Duration",     f"{int(dur//60)}m {int(dur%60)}s")
    with k2:
        with st.container(border=True): st.metric("💬 Segments",     len(seg_df))
    with k3:
        with st.container(border=True): st.metric("⭐ Key Moments",  len(km_df))
    with k4:
        with st.container(border=True): st.metric("🎯 Lead Score",   f"{lead}/100")
    with k5:
        with st.container(border=True): st.metric("😐 Avg Sentiment",f"{avg_sent:.2f}")
    with k6:
        with st.container(border=True): st.metric("📉 Neg Segments", f"{neg_pct:.1f}%")

    # ── Structured KPIs ──────────────────────────────────────────────────────
    if len(ins_df) > 0 and ins_df.iloc[0].get('RESOLUTION_STATUS'):
        row  = ins_df.iloc[0]
        res  = row.get('RESOLUTION_STATUS','N/A')
        csat = row.get('CSAT_INDICATOR','N/A')
        esc  = bool(row.get('ESCALATION_FLAG'))
        ri   = {"Resolved":"✅","Unresolved":"❌","Partial":"🟡","Escalated":"🔺"}.get(res,"❓")
        ci   = {"Positive":"😊","Neutral":"😐","Negative":"😞"}.get(csat,"❓")

        st.markdown("---")
        section_header("📊", "Structured KPIs")

        # Resolution color
        res_bg  = {"Resolved":"#f0fdf4","Unresolved":"#fef2f2","Partial":"#fefce8","Escalated":"#fff7ed"}.get(res,"#f8fafc")
        res_bd  = {"Resolved":"#86efac","Unresolved":"#fca5a5","Partial":"#fde68a","Escalated":"#fdba74"}.get(res,"#e2e8f0")
        # Escalation color
        esc_bg  = "#fef2f2" if esc else "#f0fdf4"
        esc_bd  = "#fca5a5" if esc else "#86efac"
        # CSAT color
        csat_bg = {"Positive":"#f0fdf4","Neutral":"#fefce8","Negative":"#fef2f2"}.get(csat,"#f8fafc")
        csat_bd = {"Positive":"#86efac","Neutral":"#fde68a","Negative":"#fca5a5"}.get(csat,"#e2e8f0")

        issue       = row.get('ISSUE_TYPE','N/A') or 'N/A'
        issue_icon  = {"Technical":"🔵","Billing":"🟡","Complaint":"🔴","Product":"🟢",
                       "Shipping":"🟠","Account":"🟣","Returns":"🟤","Support":"🔷"}.get(issue,"🏷️")

        q1,q2,q3,q4 = st.columns(4)
        with q1:
            st.markdown(f"""
            <div style="background:{res_bg};border:1px solid {res_bd};border-radius:10px;padding:14px 16px;">
                <div style="font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:0.5px;">{ri} Resolution</div>
                <div style="font-size:20px;font-weight:800;margin-top:4px;">{res}</div>
            </div>""", unsafe_allow_html=True)
        with q2:
            st.markdown(f"""
            <div style="background:{esc_bg};border:1px solid {esc_bd};border-radius:10px;padding:14px 16px;">
                <div style="font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:0.5px;">{"🚨 Escalation" if esc else "✅ Escalation"}</div>
                <div style="font-size:20px;font-weight:800;margin-top:4px;">{"Yes" if esc else "No"}</div>
            </div>""", unsafe_allow_html=True)
        with q3:
            st.markdown(f"""
            <div style="background:{csat_bg};border:1px solid {csat_bd};border-radius:10px;padding:14px 16px;">
                <div style="font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:0.5px;">{ci} CSAT</div>
                <div style="font-size:20px;font-weight:800;margin-top:4px;">{csat}</div>
            </div>""", unsafe_allow_html=True)
        with q4:
            # Issue type uses full text — no truncation, word-wrap enabled
            st.markdown(f"""
            <div style="background:#f5f3ff;border:1px solid #c4b5fd;border-radius:10px;padding:14px 16px;">
                <div style="font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:0.5px;">{issue_icon} Issue Type</div>
                <div style="font-size:16px;font-weight:800;margin-top:4px;word-wrap:break-word;white-space:normal;line-height:1.3;">{issue}</div>
            </div>""", unsafe_allow_html=True)

        if row.get('CALL_OUTCOME'):
            st.info(f"**📌 Outcome:** {row['CALL_OUTCOME']}")
        if row.get('ROOT_CAUSE') and str(row['ROOT_CAUSE']).lower() not in ['none','null','']:
            st.warning(f"**🔎 Root Cause:** {row['ROOT_CAUSE']}")

    st.divider()

    # ── Sentiment timeline ───────────────────────────────────────────────────
    section_header("📉", "Sentiment Timeline", "Sentiment progression with key moment markers")
    st.line_chart(seg_df[['START_TIME','SENTIMENT']].set_index('START_TIME'), color=["#3b82f6"])
    if len(km_df) > 0:
        mi = {'Frustration':'😤','Escalation_Request':'🔺','Complaint':'😠',
              'Buying_Signal':'💰','Resolution':'✅','Positive_Feedback':'😊','Objection':'🚧'}
        moment_str = "  ·  ".join([
            f"{mi.get(m['MOMENT_TYPE'],'📌')} **{m['MOMENT_TYPE']}** @ {int(m['START_TIME']//60):02d}:{int(m['START_TIME']%60):02d}"
            for _, m in km_df.iterrows()
        ])
        st.caption(f"⚡ Key moments: {moment_str}")

    st.divider()

    # ── Key Moments ──────────────────────────────────────────────────────────
    section_header("⭐", "Key Moments", "Critical events detected in this call")
    if len(km_df) == 0:
        st.caption("No key moments detected.")
    else:
        mi      = {'Frustration':'😤','Escalation_Request':'🔺','Complaint':'😠',
                   'Buying_Signal':'💰','Resolution':'✅','Positive_Feedback':'😊','Objection':'🚧'}
        sev_dot = {'high':'🔴','medium':'🟡','low':'🟢'}

        for mtype in km_df['MOMENT_TYPE'].unique():
            grp         = km_df[km_df['MOMENT_TYPE'] == mtype]
            icon        = mi.get(mtype,'📌')
            is_critical = mtype in ['Frustration','Escalation_Request','Complaint']
            with st.expander(f"{icon} **{mtype}** — {len(grp)} occurrence(s)", expanded=is_critical):
                for _, m in grp.iterrows():
                    sev    = m.get('SEVERITY','low') or 'low'
                    dot    = sev_dot.get(sev,'⚪')
                    mm, ss = int(m['START_TIME']//60), int(m['START_TIME']%60)
                    dur    = m['END_TIME'] - m['START_TIME']
                    with st.container(border=True):
                        c1, c2 = st.columns([5,1])
                        with c1:
                            st.markdown(f"{dot} **{mtype}** · severity: `{sev}`")
                        with c2:
                            st.caption(f"⏱ {mm:02d}:{ss:02d}")
                            st.caption(f"{dur:.1f}s")
                        st.write(m['SEGMENT_TEXT'][:300])

        st.markdown("**Moment distribution:**")
        st.bar_chart(km_df['MOMENT_TYPE'].value_counts())