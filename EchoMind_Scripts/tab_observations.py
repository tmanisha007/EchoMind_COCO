import streamlit as st
from utils import DB, _cortex, require_call

def render(session):
    st.markdown("## 🔍 Observations")
    st.caption("AI-generated UX and analysis improvement suggestions based on this call's data.")

    if not require_call("Observations"):
        return

    call_id = st.session_state['last_call_id']

    obs_key = f"observations_{call_id}"

    st.markdown("""
    This tab surfaces patterns, gaps, and improvement opportunities identified from the call analysis.
    Use these to improve agent training, product flows, and call handling processes.
    """)

    if st.button("🔍 Generate observations", key="gen_obs") or st.session_state.get(obs_key):
        if not st.session_state.get(obs_key):
            seg_df = session.sql(
                f"SELECT COALESCE(SPEAKER_ROLE,SPEAKER) AS SPK, SEGMENT_TEXT, SENTIMENT, "
                f"STANDARD_TOPIC, IS_KEY_MOMENT, MOMENT_TYPE "
                f"FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{call_id}' ORDER BY START_TIME"
            ).to_pandas()
            ins_df = session.sql(f"SELECT * FROM {DB}.CALL_INSIGHTS WHERE CALL_ID='{call_id}'").to_pandas()
            km_df  = session.sql(f"SELECT * FROM {DB}.CALL_KEY_MOMENTS WHERE CALL_ID='{call_id}'").to_pandas()

            tx_lines = [f"{r['SPK']}: {r['SEGMENT_TEXT']}" for _, r in seg_df.iterrows()]
            ins_ctx = ""
            if len(ins_df) > 0:
                row = ins_df.iloc[0]
                ins_ctx = (
                    f"\nResolution: {row.get('RESOLUTION_STATUS','?')}"
                    f" | Escalation: {row.get('ESCALATION_FLAG','?')}"
                    f" | CSAT: {row.get('CSAT_INDICATOR','?')}"
                    f" | Root cause: {row.get('ROOT_CAUSE','?')}"
                    f" | Issue type: {row.get('ISSUE_TYPE','?')}"
                )
            km_ctx = ""
            if len(km_df) > 0:
                km_ctx = "\nKey moments: " + ", ".join([f"{m['MOMENT_TYPE']}({m.get('SEVERITY','')})" for _, m in km_df.iterrows()])

            prompt = (
                f"You are a product and process improvement expert analyzing a customer service call.{ins_ctx}{km_ctx}\n\n"
                f"Based on the call data below, provide structured observations under these headings:\n\n"
                f"1. AGENT BEHAVIOUR PATTERNS — what repeated behaviours (positive or negative) did you notice?\n"
                f"2. CUSTOMER EXPERIENCE GAPS — where did the customer feel unheard, confused, or frustrated?\n"
                f"3. PROCESS IMPROVEMENTS — what process or script changes could prevent similar issues?\n"
                f"4. PRODUCT/TOOL GAPS — any hints that the agent lacked tools, info, or authority to resolve faster?\n"
                f"5. TRAINING RECOMMENDATIONS — what specific skills should this agent develop?\n\n"
                f"Be specific and actionable. Reference exact moments where possible.\n\n"
                f"Call transcript:\n" + "\n".join(tx_lines[:50])
            )

            with st.spinner("Generating observations…"):
                st.session_state[obs_key] = _cortex(session, prompt)

        st.markdown(st.session_state[obs_key])

        st.divider()
        st.download_button(
            "⬇️ Download observations (.txt)",
            data=st.session_state[obs_key],
            file_name=f"echomind_observations_{call_id}.txt",
            mime="text/plain",
            key="dl_obs"
        )
