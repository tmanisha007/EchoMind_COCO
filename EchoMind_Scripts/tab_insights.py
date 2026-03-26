import streamlit as st
import pandas as pd
from utils import DB, _cortex, _sq, require_call

def render(session):
    st.markdown("## 📊 Insights")
    st.caption("Full analysis of your call — transcript, sentiment, key moments, topics, and AI diagnosis.")

    if not require_call("Insights"):
        return

    call_id = st.session_state['last_call_id']

    seg_df = session.sql(f"SELECT * FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{call_id}' ORDER BY START_TIME").to_pandas()
    ins_df = session.sql(f"SELECT * FROM {DB}.CALL_INSIGHTS WHERE CALL_ID='{call_id}'").to_pandas()
    km_df  = session.sql(f"SELECT * FROM {DB}.CALL_KEY_MOMENTS WHERE CALL_ID='{call_id}' ORDER BY START_TIME").to_pandas()

    if len(seg_df) == 0:
        st.warning("No segment data found for this call.")
        return

    # ── Hero: AI diagnosis ───────────────────────────────────────────────────
    st.markdown("### 🧠 AI Diagnosis")
    diag_key = f"diag_{call_id}"
    if diag_key not in st.session_state:
        with st.spinner("Generating AI diagnosis..."):
            tx_lines = [f"{r.get('SPEAKER_ROLE') or r.get('SPEAKER','?')}: {r['SEGMENT_TEXT']}" for _, r in seg_df.iterrows()]
            ins_ctx = ""
            if len(ins_df) > 0:
                row = ins_df.iloc[0]
                ins_ctx = (
                    f"\nResolution: {row.get('RESOLUTION_STATUS','?')}"
                    f" | Escalation: {row.get('ESCALATION_FLAG','?')}"
                    f" | CSAT: {row.get('CSAT_INDICATOR','?')}"
                    f" | Issue: {row.get('ISSUE_TYPE','?')}"
                    f" | Outcome: {row.get('CALL_OUTCOME','?')}"
                )
            prompt = (
                f"You are an expert call analyst. In 3 concise sentences, diagnose this call:{ins_ctx}\n\n"
                f"Cover: what the core problem was, how well the agent handled it, and the key risk or opportunity.\n\n"
                f"Transcript:\n" + "\n".join(tx_lines[:40])
            )
            st.session_state[diag_key] = _cortex(session, prompt)

    st.info(st.session_state[diag_key])

    # ── KPI bar ──────────────────────────────────────────────────────────────
    st.markdown("### 📈 KPIs at a glance")
    dur = seg_df['END_TIME'].max()
    avg_sent = seg_df['SENTIMENT'].mean()
    lead = int(ins_df['LEAD_INTENT_SCORE'].iloc[0]) if len(ins_df) > 0 else 0

    k1, k2, k3, k4, k5 = st.columns(5)
    with k1:
        with st.container(border=True):
            st.metric("⏱ Duration", f"{int(dur//60)}m {int(dur%60)}s")
    with k2:
        with st.container(border=True):
            st.metric("💬 Segments", len(seg_df))
    with k3:
        sent_label = "😊 Positive" if avg_sent > 0.1 else "😞 Negative" if avg_sent < -0.1 else "😐 Neutral"
        with st.container(border=True):
            st.metric("Avg Sentiment", f"{avg_sent:.2f}", delta=sent_label)
    with k4:
        with st.container(border=True):
            st.metric("🎯 Lead Score", f"{lead}/100")
    with k5:
        with st.container(border=True):
            st.metric("⭐ Key Moments", len(km_df))

    if len(ins_df) > 0 and ins_df.iloc[0].get('RESOLUTION_STATUS'):
        row = ins_df.iloc[0]
        r1, r2, r3, r4 = st.columns(4)
        res = row.get('RESOLUTION_STATUS','N/A')
        res_icon = {"Resolved":"✅","Unresolved":"❌","Partial":"🟡","Escalated":"🔺"}.get(res,"❓")
        csat = row.get('CSAT_INDICATOR','N/A')
        csat_icon = {"Positive":"😊","Neutral":"😐","Negative":"😞"}.get(csat,"❓")
        with r1:
            with st.container(border=True):
                st.metric(f"{res_icon} Resolution", res)
        with r2:
            with st.container(border=True):
                st.metric("🔺 Escalation", "Yes" if row.get('ESCALATION_FLAG') else "No")
        with r3:
            with st.container(border=True):
                st.metric(f"{csat_icon} CSAT", csat)
        with r4:
            with st.container(border=True):
                st.metric("🏷 Issue Type", row.get('ISSUE_TYPE','N/A'))
        if row.get('CALL_OUTCOME'):
            st.info(f"**Outcome:** {row['CALL_OUTCOME']}")
        if row.get('ROOT_CAUSE') and str(row['ROOT_CAUSE']).lower() not in ['none','null','']:
            st.warning(f"**Root Cause:** {row['ROOT_CAUSE']}")

    st.divider()

    # ── Sentiment timeline with key moment markers ───────────────────────────
    st.markdown("### 📉 Sentiment Timeline")
    chart_df = seg_df[['START_TIME','SENTIMENT']].copy().set_index('START_TIME')
    st.line_chart(chart_df)
    if len(km_df) > 0:
        st.caption("⚡ Key moments: " + "  |  ".join([
            f"{m['MOMENT_TYPE']} @ {int(m['START_TIME']//60):02d}:{int(m['START_TIME']%60):02d}"
            for _, m in km_df.iterrows()
        ]))

    st.divider()

    # ── Key Moments ──────────────────────────────────────────────────────────
    st.markdown("### ⭐ Key Moments")
    if len(km_df) == 0:
        st.caption("No key moments detected.")
    else:
        mi = {'Frustration':'😤','Escalation_Request':'🔺','Complaint':'😠',
              'Buying_Signal':'💰','Resolution':'✅','Positive_Feedback':'😊','Objection':'🚧'}
        sev_color = {'high':'🔴','medium':'🟡','low':'🟢'}

        # Group by moment type for cleaner visual hierarchy
        for mtype in km_df['MOMENT_TYPE'].unique():
            grp = km_df[km_df['MOMENT_TYPE'] == mtype]
            icon = mi.get(mtype,'📌')
            with st.expander(f"{icon} **{mtype}** — {len(grp)} occurrence(s)", expanded=(mtype in ['Frustration','Escalation_Request','Complaint'])):
                for _, m in grp.iterrows():
                    sev = sev_color.get(m.get('SEVERITY',''),'⚪')
                    mm, ss = int(m['START_TIME']//60), int(m['START_TIME']%60)
                    dur = m['END_TIME'] - m['START_TIME']
                    st.markdown(f"{sev} `{mm:02d}:{ss:02d}` ({dur:.1f}s) — {m['SEGMENT_TEXT']}")

    st.divider()

    # ── Topic flow ───────────────────────────────────────────────────────────
    st.markdown("### 🧩 Topic Flow")
    has_std = 'STANDARD_TOPIC' in seg_df.columns and seg_df['STANDARD_TOPIC'].notna().any()
    tcol = 'STANDARD_TOPIC' if has_std else 'TOPIC_LABEL'
    tcolors = {
        'Greeting':'🟦','Identity_Verification':'🟦','Intent_Discovery':'🟩',
        'Troubleshooting':'🟧','Frustration':'🟥','Escalation':'🟥',
        'Resolution':'✅','Pricing':'💰','Objection':'🟥',
        'Closing':'🟦','Follow_Up':'🟩','Product_Info':'🟧','Small_Talk':'⬜'
    }

    if has_std:
        # Phase strip — deduplicated
        seen = []
        for _, seg in seg_df.iterrows():
            t = seg.get(tcol)
            if t and (not seen or seen[-1] != t):
                seen.append(t)
        st.markdown("**Call phases:** " + " → ".join([f"{tcolors.get(t,'📌')} {t}" for t in seen]))
        st.caption("")

    # Critical segments highlighted first
    crit = seg_df[seg_df.get(tcol, pd.Series(dtype=str)).isin(['Frustration','Escalation'])] if has_std else pd.DataFrame()
    if len(crit) > 0:
        st.markdown("**🚨 Critical segments:**")
        for _, cs in crit.iterrows():
            mm, ss = int(cs['START_TIME']//60), int(cs['START_TIME']%60)
            st.error(f"**{cs[tcol]}** @ {mm:02d}:{ss:02d} — {cs['SEGMENT_TEXT'][:140]}")
        st.caption("")

    with st.expander("Full conversation flow"):
        for _, seg in seg_df.iterrows():
            topic = seg.get(tcol) or 'Unknown'
            role = seg.get('SPEAKER_ROLE') or 'Unknown'
            is_km = seg.get('IS_KEY_MOMENT', False)
            mm, ss = int(seg['START_TIME']//60), int(seg['START_TIME']%60)
            ti = tcolors.get(topic,'⬜')
            ri = "🔵" if role=='Agent' else "🟢" if role=='Customer' else "⚪"
            km = " ⚡" if is_km else ""
            st.markdown(f"`{mm:02d}:{ss:02d}` {ti} **{topic}** {ri} {role}{km} — _{seg['SEGMENT_TEXT'][:80]}_")

    st.divider()

    # ── Full Transcript ──────────────────────────────────────────────────────
    st.markdown("### 📜 Full Transcript")
    with st.expander("Show full transcript", expanded=False):
        for _, seg in seg_df.iterrows():
            role = seg.get('SPEAKER_ROLE') or seg.get('SPEAKER','Unknown')
            ri = "🔵" if role == 'Agent' else "🟢" if role == 'Customer' else "⚪"
            mm, ss = int(seg['START_TIME']//60), int(seg['START_TIME']%60)
            km_badge = " **⚡**" if seg.get('IS_KEY_MOMENT') else ""
            st.markdown(f"{ri} **{role}** `{mm:02d}:{ss:02d}`{km_badge}")
            st.markdown(f"> {seg['SEGMENT_TEXT']}")
            if seg.get('IS_KEY_MOMENT'):
                st.caption(f"{seg.get('MOMENT_TYPE','')} | {seg.get('MOMENT_SEVERITY','')}")

    st.divider()

    # ── Objections / Action items from insights ──────────────────────────────
    if len(ins_df) > 0:
        st.markdown("### 💡 Extracted Insights")
        ins_row = ins_df.iloc[0]
        icons = {
            'BUYING_SIGNALS':'💰','OBJECTIONS':'🚧','COMPETITOR_MENTIONS':'🏁',
            'PRICING_DISCUSSIONS':'💲','ACTION_ITEMS':'✅','NEXT_STEPS':'➡️'
        }
        cols = st.columns(2)
        items = [(c, str(ins_row.get(c,''))) for c in icons if str(ins_row.get(c,'')).strip().lower() not in ['','none','null','[]']]
        for i, (c, val) in enumerate(items):
            with cols[i % 2]:
                with st.expander(f"{icons[c]} {c.replace('_',' ').title()}"):
                    st.write(val)
