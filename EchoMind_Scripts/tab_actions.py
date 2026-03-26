import streamlit as st
from utils import DB, _cortex, require_call, section_header, _default_index

def render(session):
    if not require_call("Actions"):
        return

    call_id = st.session_state['last_call_id']

    # ── Sub-tabs ─────────────────────────────────────────────────────────────
    sub1, sub2, sub3 = st.tabs([
        "💬 Ask EchoMind",
        "📧 Follow-Up Email",
        "🏷️ Tags & Notes",
    ])

    # ════════════════════════════════════════════════════════════════════════
    # SUB 1 — Ask EchoMind
    # ════════════════════════════════════════════════════════════════════════
    with sub1:
        section_header("💬", "Ask EchoMind", "Chat with AI about this call — ask anything")

        chat_key = f"ask_chat_{call_id}"
        if chat_key not in st.session_state:
            st.session_state[chat_key] = []

        st.markdown("**Quick questions:**")
        qc1,qc2,qc3,qc4 = st.columns(4)
        quick_prompts = {
            "📋 Summary":         "Give me a concise executive summary of this call in 3-5 bullet points.",
            "😤 Frustrations":    "What were the moments of customer frustration? What triggered them?",
            "✅ Was it resolved?": "Was the customer's issue resolved? What was the resolution and outcome?",
            "💡 Action items":    "What are the key action items and next steps identified in this call?"
        }
        for col, (label, prompt) in zip([qc1,qc2,qc3,qc4], quick_prompts.items()):
            with col:
                if st.button(label, key=f"quick_{label}_{call_id}"):
                    st.session_state[chat_key].append({"role":"user","content":prompt})

        for msg in st.session_state[chat_key]:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        user_q = st.chat_input("Ask anything about this call…", key=f"ask_input_{call_id}")
        if user_q:
            st.session_state[chat_key].append({"role":"user","content":user_q})

        if st.session_state[chat_key] and st.session_state[chat_key][-1]["role"] == "user":
            last_q   = st.session_state[chat_key][-1]["content"]
            ask_segs = session.sql(
                f"SELECT COALESCE(SPEAKER_ROLE,SPEAKER) AS SPK, SEGMENT_TEXT, SENTIMENT, "
                f"STANDARD_TOPIC, IS_KEY_MOMENT, MOMENT_TYPE "
                f"FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{call_id}' ORDER BY START_TIME"
            ).to_pandas()
            ask_ins = session.sql(f"SELECT * FROM {DB}.CALL_INSIGHTS WHERE CALL_ID='{call_id}'").to_pandas()

            tx_context = "\n".join([f"{r['SPK']}: {r['SEGMENT_TEXT']}" for _, r in ask_segs.iterrows()])[:6000]
            ins_context = ""
            if len(ask_ins) > 0:
                row = ask_ins.iloc[0]
                ins_context = (
                    f"\nKPIs: Resolution={row.get('RESOLUTION_STATUS','N/A')}, "
                    f"Escalation={row.get('ESCALATION_FLAG','N/A')}, "
                    f"CSAT={row.get('CSAT_INDICATOR','N/A')}, "
                    f"Issue={row.get('ISSUE_TYPE','N/A')}, "
                    f"Outcome={row.get('CALL_OUTCOME','N/A')}"
                )
            km_segs = ask_segs[ask_segs['IS_KEY_MOMENT'] == True]
            km_context = ("\nKey moments:\n" + "\n".join([f"[{r['MOMENT_TYPE']}] {r['SEGMENT_TEXT']}" for _, r in km_segs.iterrows()][:10])) if len(km_segs) > 0 else ""

            full_prompt = (
                f"You are EchoMind, an expert call analytics AI. Answer based solely on the call data provided. "
                f"Be concise and specific.{ins_context}{km_context}\n\n"
                f"Transcript:\n{tx_context}\n\nQuestion: {last_q}\n\nAnswer:"
            )
            with st.chat_message("assistant"):
                with st.spinner("EchoMind is thinking…"):
                    answer = _cortex(session, full_prompt)
                st.markdown(answer)
            st.session_state[chat_key].append({"role":"assistant","content":answer})

        if st.session_state[chat_key]:
            if st.button("🗑 Clear conversation", key=f"clear_chat_{call_id}"):
                st.session_state[chat_key] = []
                st.rerun()

    # ════════════════════════════════════════════════════════════════════════
    # SUB 2 — Follow-Up Email
    # ════════════════════════════════════════════════════════════════════════
    with sub2:
        section_header("📧", "Follow-Up Email", "Auto-generate a professional follow-up based on call outcome")

        fe_col1, fe_col2 = st.columns(2)
        with fe_col1:
            fe_sender    = st.text_input("From (Agent name)", placeholder="e.g. Priya Sharma", key="fe_sender")
            fe_company   = st.text_input("Company name",      placeholder="e.g. Acme Corp",    key="fe_company")
        with fe_col2:
            fe_recipient = st.text_input("Customer name",     placeholder="e.g. Rahul Verma",  key="fe_recipient")
            fe_tone      = st.selectbox("Tone", ["Professional","Friendly","Apologetic","Follow-up focused"], key="fe_tone")

        if st.button("✉️ Generate follow-up email", key="fe_generate_btn", type="primary"):
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
                )
            fe_prompt = (
                f"Write a {fe_tone.lower()} follow-up email from {fe_sender or 'the agent'} "
                f"at {fe_company or 'our company'} to {fe_recipient or 'the customer'} "
                f"after a customer support call. Include subject line, recap, action items, "
                f"next steps, and sign-off. Make it specific to the call context.{ins_ctx}\n\n"
                f"Transcript:\n{tx_snippet}"
            )
            with st.spinner("Drafting email…"):
                st.session_state[f'fe_email_{call_id}'] = _cortex(session, fe_prompt)

        if st.session_state.get(f'fe_email_{call_id}'):
            st.markdown("**Generated email:**")
            email_text = st.session_state[f'fe_email_{call_id}']
            st.text_area("Email draft (editable)", value=email_text, height=380, key=f"fe_edit_{call_id}")
            st.download_button("⬇️ Download (.txt)", data=email_text,
                file_name=f"followup_email_{call_id}.txt", mime="text/plain", key="fe_download")

    # ════════════════════════════════════════════════════════════════════════
    # SUB 3 — Tags & Notes
    # ════════════════════════════════════════════════════════════════════════
    with sub3:
        section_header("🏷️", "Tags & Notes", "Organise and annotate calls for follow-up")

        tag_calls = session.sql(f"SELECT DISTINCT CALL_ID FROM {DB}.CALL_SEGMENTS ORDER BY CALL_ID").to_pandas()
        _ids = tag_calls['CALL_ID'].tolist()
        sel_tag = st.selectbox("Select call", _ids, index=_default_index(_ids), key="tag_call")

        preset_tags = ["🔥 Hot Lead","❄️ Cold Lead","🔄 Follow-Up Needed","⚠️ Needs Escalation",
                       "👤 Decision Maker Present","💰 Budget Discussed","🏁 Competitor Mentioned",
                       "✅ Deal Closed","📅 Meeting Scheduled","🚧 Objection Heavy"]

        current_tags = st.session_state['call_tags'].get(sel_tag, [])
        selected_tags = st.multiselect("Apply tags", preset_tags, default=current_tags, key=f"tags_{sel_tag}")
        st.session_state['call_tags'][sel_tag] = selected_tags

        c_tag, c_btn = st.columns([4,1])
        with c_tag:
            custom_tag = st.text_input("Custom tag", placeholder="Type custom tag...", key="custom_tag", label_visibility="collapsed")
        with c_btn:
            if st.button("Add", key="add_custom_tag") and custom_tag:
                if custom_tag not in st.session_state['call_tags'].get(sel_tag, []):
                    st.session_state['call_tags'].setdefault(sel_tag, []).append(custom_tag)
                    st.rerun()

        if selected_tags:
            st.markdown("**Applied:** " + "  ".join([f"`{t}`" for t in selected_tags]))

        st.markdown("**Notes:**")
        current_notes = st.session_state['call_notes'].get(sel_tag, "")
        notes = st.text_area("Notes", value=current_notes, height=150, key=f"notes_{sel_tag}", label_visibility="collapsed", placeholder="Add call notes, follow-up reminders...")
        st.session_state['call_notes'][sel_tag] = notes

        st.divider()
        st.markdown("**All tagged calls:**")
        tagged = {k:v for k,v in st.session_state['call_tags'].items() if v}
        if tagged:
            for cid, tags in tagged.items():
                note_preview = st.session_state['call_notes'].get(cid,"")[:100]
                with st.expander(f"📞 {cid} — {', '.join(tags)}"):
                    st.markdown(f"**Tags:** {', '.join(tags)}")
                    if note_preview:
                        st.markdown(f"**Notes:** {note_preview}{'...' if len(st.session_state['call_notes'].get(cid,'')) > 100 else ''}")
        else:
            st.caption("No calls tagged yet.")
