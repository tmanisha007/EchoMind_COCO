import streamlit as st
from utils import DB, _cortex, require_call

def render(session):
    st.markdown("## 💬 Ask EchoMind")
    st.caption("Chat with AI about the processed call — ask anything, get instant answers.")

    if not require_call("Ask EchoMind"):
        return

    call_id = st.session_state['last_call_id']
    chat_key = f"ask_chat_{call_id}"
    if chat_key not in st.session_state:
        st.session_state[chat_key] = []

    # ── Quick-start buttons ──────────────────────────────────────────────────
    st.markdown("**Quick questions:**")
    qcol1, qcol2, qcol3, qcol4 = st.columns(4)
    quick_prompts = {
        "📋 Summary":        "Give me a concise executive summary of this call in 3-5 bullet points covering purpose, key points, and outcome.",
        "😤 Frustrations":   "What were the moments of customer frustration in this call? What triggered them?",
        "✅ Was it resolved?":"Was the customer's issue resolved? What was the resolution status and outcome?",
        "💡 Action items":   "What are the key action items and next steps identified in this call?"
    }
    for col, (label, prompt) in zip([qcol1, qcol2, qcol3, qcol4], quick_prompts.items()):
        with col:
            if st.button(label, key=f"quick_{label}_{call_id}"):
                st.session_state[chat_key].append({"role": "user", "content": prompt})

    # ── Chat history display ─────────────────────────────────────────────────
    for msg in st.session_state[chat_key]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # ── Chat input ───────────────────────────────────────────────────────────
    user_q = st.chat_input("Ask anything about this call…", key=f"ask_input_{call_id}")
    if user_q:
        st.session_state[chat_key].append({"role": "user", "content": user_q})

    # ── Generate response if last message is from user ───────────────────────
    if st.session_state[chat_key] and st.session_state[chat_key][-1]["role"] == "user":
        last_q = st.session_state[chat_key][-1]["content"]

        ask_segs = session.sql(
            f"SELECT COALESCE(SPEAKER_ROLE,SPEAKER) AS SPK, SEGMENT_TEXT, SENTIMENT, "
            f"STANDARD_TOPIC, IS_KEY_MOMENT, MOMENT_TYPE "
            f"FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{call_id}' ORDER BY START_TIME"
        ).to_pandas()
        ask_ins = session.sql(f"SELECT * FROM {DB}.CALL_INSIGHTS WHERE CALL_ID='{call_id}'").to_pandas()

        tx_lines = [f"{r['SPK']}: {r['SEGMENT_TEXT']}" for _, r in ask_segs.iterrows()]
        tx_context = "\n".join(tx_lines)[:6000]

        ins_context = ""
        if len(ask_ins) > 0:
            row = ask_ins.iloc[0]
            ins_context = (
                f"\nCall KPIs: Resolution={row.get('RESOLUTION_STATUS','N/A')}, "
                f"Escalation={row.get('ESCALATION_FLAG','N/A')}, "
                f"CSAT={row.get('CSAT_INDICATOR','N/A')}, "
                f"Issue={row.get('ISSUE_TYPE','N/A')}, "
                f"Outcome={row.get('CALL_OUTCOME','N/A')}"
            )

        km_segs = ask_segs[ask_segs['IS_KEY_MOMENT'] == True]
        km_context = ""
        if len(km_segs) > 0:
            km_lines = [f"[{r['MOMENT_TYPE']}] {r['SEGMENT_TEXT']}" for _, r in km_segs.iterrows()]
            km_context = "\nKey moments:\n" + "\n".join(km_lines[:10])

        system_ctx = (
            f"You are EchoMind, an expert call analytics AI. "
            f"Answer questions about this call based solely on the data provided. "
            f"Be concise, specific, and cite timestamps or speakers where relevant."
            f"{ins_context}{km_context}"
        )
        full_prompt = (
            f"{system_ctx}\n\nCall transcript (call ID: {call_id}):\n{tx_context}"
            f"\n\nUser question: {last_q}\n\nAnswer:"
        )

        with st.chat_message("assistant"):
            with st.spinner("EchoMind is thinking…"):
                answer = _cortex(session, full_prompt)
            st.markdown(answer)
        st.session_state[chat_key].append({"role": "assistant", "content": answer})

    if st.session_state[chat_key]:
        if st.button("🗑 Clear conversation", key=f"clear_chat_{call_id}"):
            st.session_state[chat_key] = []
            st.rerun()
