import streamlit as st
from utils import DB, _cortex, require_call, section_header

def render(session):
    if not require_call("Scorecard & Coaching"):
        return

    call_id  = st.session_state['last_call_id']
    sc_seg   = session.sql(f"SELECT * FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{call_id}' ORDER BY START_TIME").to_pandas()
    sc_ins   = session.sql(f"SELECT * FROM {DB}.CALL_INSIGHTS WHERE CALL_ID='{call_id}'").to_pandas()
    sc_kpis  = session.sql(f"SELECT * FROM {DB}.CALL_INSIGHTS WHERE CALL_ID='{call_id}'").to_pandas()

    if len(sc_seg) == 0:
        st.info("No data available. Process a call first.")
        return

    sc_dur      = sc_seg['END_TIME'].max()
    sc_lead     = int(sc_ins['LEAD_INTENT_SCORE'].iloc[0]) if len(sc_ins) > 0 else 0
    sc_avg_sent = sc_seg['SENTIMENT'].mean()
    sc_seg['dur'] = sc_seg['END_TIME'] - sc_seg['START_TIME']
    role_col    = 'SPEAKER_ROLE' if 'SPEAKER_ROLE' in sc_seg.columns and sc_seg['SPEAKER_ROLE'].notna().any() else 'SPEAKER'
    talk_by_spk = sc_seg.groupby(role_col)['dur'].sum()
    balance     = talk_by_spk.min()/talk_by_spk.max()*100 if talk_by_spk.max() > 0 else 0

    has_kpis = len(sc_kpis) > 0 and sc_kpis.iloc[0].get('RESOLUTION_STATUS')
    kr = sc_kpis.iloc[0] if has_kpis else None

    # ── Grade calculation ────────────────────────────────────────────────────
    if has_kpis and kr is not None:
        resolved  = kr.get('RESOLUTION_STATUS') == 'Resolved'
        escalated = bool(kr.get('ESCALATION_FLAG'))
        positive  = kr.get('CSAT_INDICATOR') == 'Positive'
        if resolved and not escalated and positive:
            grade, grade_color, grade_bg = "🌟 Excellent", "#15803d", "#f0fdf4"
        elif resolved:
            grade, grade_color, grade_bg = "✅ Good",      "#1d4ed8", "#eff6ff"
        elif escalated:
            grade, grade_color, grade_bg = "⚠️ Escalated", "#b45309", "#fffbeb"
        elif kr.get('RESOLUTION_STATUS') == 'Unresolved':
            grade, grade_color, grade_bg = "🔴 Needs Improvement", "#dc2626", "#fef2f2"
        else:
            grade, grade_color, grade_bg = "⚠️ Average",  "#b45309", "#fffbeb"
    else:
        if sc_lead >= 70 and sc_avg_sent > 0.1 and balance > 30:
            grade, grade_color, grade_bg = "🌟 Excellent", "#15803d", "#f0fdf4"
        elif sc_lead >= 50 and sc_avg_sent > 0:
            grade, grade_color, grade_bg = "✅ Good",      "#1d4ed8", "#eff6ff"
        elif sc_lead >= 30:
            grade, grade_color, grade_bg = "⚠️ Average",  "#b45309", "#fffbeb"
        else:
            grade, grade_color, grade_bg = "🔴 Needs Improvement", "#dc2626", "#fef2f2"

    # ── Grade hero ───────────────────────────────────────────────────────────
    st.markdown(f"""
    <div style='background:{grade_bg};border:2px solid {grade_color}33;
                border-radius:16px;padding:24px 28px;margin-bottom:20px;
                display:flex;justify-content:space-between;align-items:center;'>
        <div>
            <div style='color:{grade_color};font-size:13px;font-weight:700;letter-spacing:1px;
                        text-transform:uppercase;'>Overall Grade · {call_id}</div>
            <div style='font-size:32px;font-weight:800;color:{grade_color};margin-top:4px;'>{grade}</div>
        </div>
        <div style='text-align:right;'>
            <div style='color:#64748b;font-size:13px;'>Lead Score</div>
            <div style='font-size:28px;font-weight:800;color:{grade_color};'>{sc_lead}/100</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Metric row ───────────────────────────────────────────────────────────
    c1,c2,c3,c4 = st.columns(4)
    with c1:
        with st.container(border=True):
            st.metric("⏱️ Duration",        f"{int(sc_dur//60)}m {int(sc_dur%60)}s")
            st.metric("👥 Speakers",         sc_seg[role_col].nunique())
    with c2:
        with st.container(border=True):
            st.metric("😐 Avg Sentiment",    f"{sc_avg_sent:.2f}")
            st.metric("📉 Negative Segs",    f"{(sc_seg['SENTIMENT']<-0.2).sum()/len(sc_seg)*100:.1f}%")
    with c3:
        with st.container(border=True):
            st.metric("⚖️ Talk Balance",     f"{balance:.0f}%")
            st.metric("💬 Total Segments",   len(sc_seg))
    with c4:
        with st.container(border=True):
            if has_kpis and kr is not None:
                st.metric("Resolution", kr.get('RESOLUTION_STATUS','N/A'))
                st.metric("CSAT",       kr.get('CSAT_INDICATOR','N/A'))

    # ── KPIs ─────────────────────────────────────────────────────────────────
    if has_kpis and kr is not None:
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        section_header("📊", "KPI Details")

        k1,k2,k3,k4 = st.columns(4)
        res  = kr.get('RESOLUTION_STATUS','N/A')
        csat = kr.get('CSAT_INDICATOR','N/A')
        esc  = bool(kr.get('ESCALATION_FLAG'))
        with k1:
            with st.container(border=True): st.metric("Resolution", res)
        with k2:
            with st.container(border=True): st.metric("Escalation", "🔺 Yes" if esc else "✅ No")
        with k3:
            with st.container(border=True): st.metric("CSAT",       csat)
        with k4:
            with st.container(border=True): st.metric("Issue Type", kr.get('ISSUE_TYPE','N/A'))

        if kr.get('CALL_OUTCOME'):
            st.info(f"**📌 Outcome:** {kr['CALL_OUTCOME']}")
        if kr.get('ROOT_CAUSE') and str(kr['ROOT_CAUSE']).lower() not in ['none','null','']:
            st.warning(f"**🔎 Root Cause:** {kr['ROOT_CAUSE']}")

    # ── Key Insights ─────────────────────────────────────────────────────────
    if len(sc_ins) > 0:
        st.divider()
        section_header("💡", "Key Insights")
        ins_row = sc_ins.iloc[0]
        icons   = {'BUYING_SIGNALS':'💰','OBJECTIONS':'🚧','COMPETITOR_MENTIONS':'🏁',
                   'PRICING_DISCUSSIONS':'💲','ACTION_ITEMS':'✅','NEXT_STEPS':'➡️'}
        cols = st.columns(2)
        items = [(c, str(ins_row.get(c,''))) for c in icons
                 if str(ins_row.get(c,'')).strip().lower() not in ['','none','null','[]']]
        for i, (c, val) in enumerate(items):
            with cols[i % 2]:
                with st.expander(f"{icons[c]} {c.replace('_',' ').title()}"):
                    st.write(val)

    st.divider()

    # ── Coaching Report ──────────────────────────────────────────────────────
    section_header("🎯", "AI Coaching Report", "What went wrong · Why it matters · What to say instead")

    coach_key = f"coach_report_{call_id}"
    if st.button("🎯 Generate coaching report", key="gen_coach_report", type="primary") or st.session_state.get(coach_key):
        if not st.session_state.get(coach_key):
            ct_seg = session.sql(
                f"SELECT COALESCE(SPEAKER_ROLE,SPEAKER) AS SPK, SEGMENT_TEXT, SENTIMENT "
                f"FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{call_id}' ORDER BY START_TIME"
            ).to_pandas()
            lines   = [f"{r['SPK']} (sent:{r['SENTIMENT']:.2f}): {r['SEGMENT_TEXT']}" for _, r in ct_seg.iterrows()]
            kpi_ctx = f"\nKPIs: Resolution={kr.get('RESOLUTION_STATUS')}, CSAT={kr.get('CSAT_INDICATOR')}, Root cause={kr.get('ROOT_CAUSE')}" if has_kpis and kr is not None else ""
            prompt  = (
                f"You are a senior call center coach. Produce a structured coaching report for the agent.{kpi_ctx}\n\n"
                f"For each issue you find, structure it as:\n"
                f"### Issue [N]: [Issue Title]\n"
                f"**What went wrong:** specific description\n"
                f"**Why it matters:** business/customer impact\n"
                f"**What should have been said:** exact alternative script\n\n"
                f"End with:\n### Top 3 Priority Actions\n"
                f"Numbered list of the most important improvements.\n\n"
                f"Call transcript:\n" + "\n".join(lines[:50])
            )
            with st.spinner("🧠 Generating coaching report..."):
                st.session_state[coach_key] = _cortex(session, prompt)

        st.markdown(st.session_state[coach_key])

    st.divider()

    # ── Download ─────────────────────────────────────────────────────────────
    scorecard_text = (
        f"{'='*60}\n        ECHOMIND CALL SCORECARD & COACHING\n{'='*60}\n"
        f"CALL ID: {call_id}\nGRADE: {grade}\n"
        f"Duration: {int(sc_dur//60)}m {int(sc_dur%60)}s | Segments: {len(sc_seg)} "
        f"| Lead: {sc_lead}/100 | Sentiment: {sc_avg_sent:.2f}\n"
    )
    if has_kpis and kr is not None:
        scorecard_text += (
            f"Resolution: {kr.get('RESOLUTION_STATUS','N/A')} | "
            f"Escalation: {'Yes' if bool(kr.get('ESCALATION_FLAG')) else 'No'} | "
            f"CSAT: {kr.get('CSAT_INDICATOR','N/A')}\n"
        )
    if st.session_state.get(coach_key):
        scorecard_text += f"\n{'='*60}\nCOACHING REPORT\n{'='*60}\n{st.session_state[coach_key]}\n"

    st.download_button(
        "⬇️ Download full scorecard + coaching (.txt)",
        data=scorecard_text,
        file_name=f"echomind_scorecard_{call_id}.txt",
        mime="text/plain",
        key="dl_scorecard"
    )