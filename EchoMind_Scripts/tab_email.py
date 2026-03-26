import streamlit as st
from utils import DB, _cortex, require_call

def render(session):
    st.markdown("## 📧 Follow-Up Email")
    st.caption("Auto-generate a professional follow-up email based on call outcomes, action items, and next steps.")

    if not require_call("Follow-Up Email"):
        return

    call_id = st.session_state['last_call_id']

    fe_col1, fe_col2 = st.columns(2)
    with fe_col1:
        fe_sender    = st.text_input("From (Agent name)", placeholder="e.g. Priya Sharma", key="fe_sender")
        fe_company   = st.text_input("Company name",      placeholder="e.g. Acme Corp",    key="fe_company")
    with fe_col2:
        fe_recipient = st.text_input("Customer name",     placeholder="e.g. Rahul Verma",  key="fe_recipient")
        fe_tone      = st.selectbox("Email tone", ["Professional","Friendly","Apologetic","Follow-up focused"], key="fe_tone")

    if st.button("✉️ Generate follow-up email", key="fe_generate_btn"):
        fe_segs = session.sql(
            f"SELECT COALESCE(SPEAKER_ROLE,SPEAKER) AS SPK, SEGMENT_TEXT "
            f"FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{call_id}' ORDER BY START_TIME"
        ).to_pandas()
        fe_ins = session.sql(f"SELECT * FROM {DB}.CALL_INSIGHTS WHERE CALL_ID='{call_id}'").to_pandas()

        tx_snippet = "\n".join([f"{r['SPK']}: {r['SEGMENT_TEXT']}" for _, r in fe_segs.iterrows()][:40])

        ins_ctx = ""
        if len(fe_ins) > 0:
            row = fe_ins.iloc[0]
            ins_ctx = (
                f"\nResolution: {row.get('RESOLUTION_STATUS','Unknown')}"
                f"\nOutcome: {row.get('CALL_OUTCOME','')}"
                f"\nAction items: {row.get('ACTION_ITEMS','')}"
                f"\nNext steps: {row.get('NEXT_STEPS','')}"
                f"\nIssue type: {row.get('ISSUE_TYPE','')}"
            )

        fe_prompt = (
            f"Write a {fe_tone.lower()} follow-up email from {fe_sender or 'the agent'} "
            f"at {fe_company or 'our company'} to {fe_recipient or 'the customer'} after a customer support call.\n"
            f"Use the call context below to make the email specific and relevant.\n"
            f"Include: subject line, greeting, brief call recap, action items or commitments made, "
            f"next steps, and a professional sign-off.\n"
            f"Format as a ready-to-send email.\n"
            f"{ins_ctx}\n\nCall transcript (excerpt):\n{tx_snippet}"
        )

        with st.spinner("Drafting your follow-up email…"):
            fe_result = _cortex(session, fe_prompt)
        st.session_state[f'fe_email_{call_id}'] = fe_result

    if st.session_state.get(f'fe_email_{call_id}'):
        st.markdown("### Generated email")
        email_text = st.session_state[f'fe_email_{call_id}']
        st.text_area("Email draft (editable)", value=email_text, height=400, key=f"fe_edit_{call_id}")
        st.download_button(
            "⬇️ Download email (.txt)",
            data=email_text,
            file_name=f"followup_email_{call_id}.txt",
            mime="text/plain",
            key="fe_download"
        )
