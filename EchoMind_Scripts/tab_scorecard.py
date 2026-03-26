import streamlit as st
from utils import DB, _cortex, _sq, require_call

def render(session):
    st.markdown("## 📋 Call Scorecard & Coaching")
    st.caption("Performance score, structured KPIs, what went wrong, and AI-powered coaching recommendations.")

    if not require_call("Call Scorecard"):
        return

    call_id = st.session_state['last_call_id']

    sc_seg  = session.sql(f"SELECT * FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{call_id}' ORDER BY START_TIME").to_pandas()
    sc_ins  = session.sql(f"SELECT * FROM {DB}.CALL_INSIGHTS WHERE CALL_ID='{call_id}'").to_pandas()
    sc_kpis = session.sql(f"SELECT RESOLUTION_STATUS,ESCALATION_FLAG,CSAT_INDICATOR,CALL_OUTCOME,ISSUE_TYPE,ROOT_CAUSE FROM {DB}.CALL_INSIGHTS WHERE CALL_ID='{call_id}'").to_pandas()

    if len(sc_seg) == 0:
        st.info("No data available for this call.")
        return

    sc_dur      = sc_seg['END_TIME'].max()
    sc_lead     = int(sc_ins['LEAD_INTENT_SCORE'].iloc[0]) if len(sc_ins) > 0 else 0
    sc_avg_sent = sc_seg['SENTIMENT'].mean()
    sc_seg['dur'] = sc_seg['END_TIME'] - sc_seg['START_TIME']
    role_col    = 'SPEAKER_ROLE' if 'SPEAKER_ROLE' in sc_seg.columns and sc_seg['SPEAKER_ROLE'].notna().any() else 'SPEAKER'
    talk_by_spk = sc_seg.groupby(role_col)['dur'].sum()
    balance     = talk_by_spk.min()/talk_by_spk.max()*100 if talk_by_spk.max() > 0 else 0

    has_kpis = len(sc_kpis) > 0 and sc_kpis.iloc[0].get('RESOLUTION_STATUS')

    # ── Grade ────────────────────────────────────────────────────────────────
    if has_kpis:
        kr = sc_kpis.iloc[0]
        resolved  = kr.get('RESOLUTION_STATUS') == 'Resolved'
        escalated = bool(kr.get('ESCALATION_FLAG'))
        positive  = kr.get('CSAT_INDICATOR') == 'Positive'
        if resolved and not escalated and positive: grade = "🌟 Excellent"
        elif resolved:                               grade = "✅ Good"
        elif escalated:                              grade = "⚠️ Escalated"
        elif kr.get('RESOLUTION_STATUS') == 'Unresolved': grade = "🔴 Needs Improvement"
        else:                                        grade = "⚠️ Average"
    else:
        kr = None
        if sc_lead >= 70 and sc_avg_sent > 0.1 and balance > 30: grade = "🌟 Excellent"
        elif sc_lead >= 50 and sc_avg_sent > 0:                   grade = "✅ Good"
        elif sc_lead >= 30:                                        grade = "⚠️ Average"
        else:                                                      grade = "🔴 Needs Improvement"

    st.markdown(f"### Overall grade: {grade}")

    # ── Stats ────────────────────────────────────────────────────────────────
    col1, col2, col3 = st.columns(3)
    with col1:
        with st.container(border=True):
            st.metric("Duration",  f"{int(sc_dur//60)}m {int(sc_dur%60)}s")
            st.metric("Speakers",  sc_seg[role_col].nunique())
    with col2:
        with st.container(border=True):
            st.metric("Lead score",    f"{sc_lead}/100")
            st.metric("Avg sentiment", f"{sc_avg_sent:.2f}")
    with col3:
        with st.container(border=True):
            st.metric("Talk balance",      f"{balance:.0f}%")
            st.metric("Negative segments", f"{(sc_seg['SENTIMENT']<-0.2).sum()/len(sc_seg)*100:.1f}%")

    # ── Structured KPIs ──────────────────────────────────────────────────────
    if has_kpis and kr is not None:
        st.markdown("### Structured KPIs")
        k1, k2, k3, k4 = st.columns(4)
        with k1:
            with st.container(border=True): st.metric("Resolution", kr.get('RESOLUTION_STATUS','N/A'))
        with k2:
            with st.container(border=True): st.metric("Escalation", "Yes" if kr.get('ESCALATION_FLAG') else "No")
        with k3:
            with st.container(border=True): st.metric("CSAT",       kr.get('CSAT_INDICATOR','N/A'))
        with k4:
            with st.container(border=True): st.metric("Issue Type", kr.get('ISSUE_TYPE','N/A'))
        if kr.get('CALL_OUTCOME'):
            st.info(f"**Outcome:** {kr['CALL_OUTCOME']}")
        if kr.get('ROOT_CAUSE') and str(kr['ROOT_CAUSE']).lower() not in ['none','null','']:
            st.warning(f"**Root Cause:** {kr['ROOT_CAUSE']}")

    st.divider()

    # ── AI Coaching — merged, actionable ─────────────────────────────────────
    st.markdown("### 🎯 AI Coaching Recommendations")
    st.caption("What went wrong, why it matters, and what the agent should have said.")

    coach_key = f"coaching_merged_{call_id}"
    if st.button("Generate coaching report", key="gen_coaching_merged") or st.session_state.get(coach_key):
        if not st.session_state.get(coach_key):
            ct_seg = session.sql(
                f"SELECT COALESCE(SPEAKER_ROLE,SPEAKER) AS SPK, SEGMENT_TEXT, SENTIMENT, IS_KEY_MOMENT, MOMENT_TYPE "
                f"FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{call_id}' ORDER BY START_TIME"
            ).to_pandas()
            lines = [f"{r['SPK']} (sent:{r['SENTIMENT']:.2f}): {r['SEGMENT_TEXT']}" for _, r in ct_seg.iterrows()]
            kpi_ctx = ""
            if has_kpis and kr is not None:
                kpi_ctx = (
                    f"\nKPIs: Resolution={kr.get('RESOLUTION_STATUS')}, "
                    f"Escalation={kr.get('ESCALATION_FLAG')}, "
                    f"CSAT={kr.get('CSAT_INDICATOR')}, "
                    f"Root cause={kr.get('ROOT_CAUSE')}"
                )

            prompt = (
                f"You are a senior call center coach. Analyze this call and produce a structured coaching report.{kpi_ctx}\n\n"
                f"For each issue you find, provide:\n"
                f"1. WHAT WENT WRONG — be specific with timestamps if possible\n"
                f"2. WHY IT MATTERS — business/customer impact\n"
                f"3. WHAT SHOULD HAVE BEEN SAID — give the exact alternative phrasing\n\n"
                f"End with 3 PRIORITY ACTIONS the agent should focus on.\n\n"
                f"Call transcript:\n" + "\n".join(lines[:50])
            )
            with st.spinner("Generating coaching report…"):
                st.session_state[coach_key] = _cortex(session, prompt)

        st.markdown(st.session_state[coach_key])

    st.divider()

    # ── Download ─────────────────────────────────────────────────────────────
    scorecard_text = (
        f"{'='*60}\n        ECHOMIND CALL SCORECARD\n{'='*60}\n"
        f"CALL ID: {call_id}\nGRADE: {grade}\n"
        f"Duration: {int(sc_dur//60)}m {int(sc_dur%60)}s | Segments: {len(sc_seg)} | Lead: {sc_lead}/100 | Sentiment: {sc_avg_sent:.2f}\n"
    )
    if has_kpis and kr is not None:
        scorecard_text += (
            f"Resolution: {kr.get('RESOLUTION_STATUS','N/A')} | "
            f"Escalation: {'Yes' if kr.get('ESCALATION_FLAG') else 'No'} | "
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
