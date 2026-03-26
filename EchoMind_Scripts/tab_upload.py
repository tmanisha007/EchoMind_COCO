import streamlit as st
import json, re, tempfile, os
from utils import DB, CORTEX_MODEL, _sq, _clean_json, enhance_call, section_header

# ── Shared: store segments into DB and run full insights pipeline ─────────────
def _run_pipeline(session, call_id, segments, source_label):
    with st.status(f"⚙️ Processing {source_label}...", expanded=True) as status:
        st.write(f"💾 Storing **{len(segments)}** segments...")
        session.sql(f"DELETE FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{call_id}'").collect()
        for i, seg in enumerate(segments):
            text    = _sq(seg.get('text',''))
            speaker = _sq(seg.get('speaker','Unknown'))
            start   = float(seg.get('start', i * 30))
            end     = float(seg.get('end',   i * 30 + 30))
            session.sql(f"""INSERT INTO {DB}.CALL_SEGMENTS
                (CALL_ID,SEGMENT_ID,SPEAKER,START_TIME,END_TIME,SEGMENT_TEXT,SENTIMENT,EMBEDDING)
                SELECT '{call_id}',{i},'{speaker}',{start},{end},'{text}',
                SNOWFLAKE.CORTEX.SENTIMENT('{text}'),
                SNOWFLAKE.CORTEX.EMBED_TEXT_1024('snowflake-arctic-embed-l-v2.0','{text}')""").collect()

        st.write("🔗 Running topic clustering...")
        session.sql(f"CALL {DB}.RUN_CLUSTERING('{call_id}')").collect()

        st.write("💡 Generating insights...")
        full_text  = " ".join([s.get('text','') for s in segments])
        safe_tx    = _sq(full_text[:8000])
        ins_result = session.sql(f"""SELECT SNOWFLAKE.CORTEX.COMPLETE('{CORTEX_MODEL}',
            $$Analyze this conversation/data. Return JSON: {{"objections":"list",
            "competitor_mentions":"list","buying_signals":"list",
            "pricing_discussions":"list","action_items":"list",
            "next_steps":"list","lead_intent_score":0-100}}
            SCORING: order/purchased=85-100. Strong interest=60-84.
            Neutral=30-59. Rejected/complained=0-29.
            Content: {safe_tx}$$) AS R""").collect()[0]['R']
        try:
            ins = json.loads(_clean_json(ins_result))
        except Exception:
            ins = {}

        session.sql(f"DELETE FROM {DB}.CALL_INSIGHTS WHERE CALL_ID='{call_id}'").collect()
        session.sql(f"""INSERT INTO {DB}.CALL_INSIGHTS
            (CALL_ID,OBJECTIONS,COMPETITOR_MENTIONS,BUYING_SIGNALS,PRICING_DISCUSSIONS,
             ACTION_ITEMS,NEXT_STEPS,LEAD_INTENT_SCORE)
            VALUES('{call_id}','{_sq(str(ins.get("objections","")))}',
            '{_sq(str(ins.get("competitor_mentions","")))}',
            '{_sq(str(ins.get("buying_signals","")))}',
            '{_sq(str(ins.get("pricing_discussions","")))}',
            '{_sq(str(ins.get("action_items","")))}',
            '{_sq(str(ins.get("next_steps","")))}',
            {int(ins.get('lead_intent_score',50))})""").collect()

        status.update(label="✅ Base processing complete!", state="complete")

    enhance_call(session, call_id)
    st.session_state['last_call_id'] = call_id
    st.success(f"✅ **{call_id}** processed with {len(segments)} segments!")
    st.info("👉 Switch to the **Call Dashboard** tab to explore your insights.")


def _parse_text_into_segments(raw_text, source_type):
    segments = []
    lines    = [l.strip() for l in raw_text.strip().splitlines() if l.strip()]

    if source_type in ["Chat Conversation", "Email Thread"]:
        current_speaker = "Unknown"
        buffer          = []
        seg_idx         = 0
        for line in lines:
            m = re.match(r'^[\[\(]?([A-Za-z0-9_ ]{1,30})[\]\)>:\-]\s+(.+)$', line)
            if m:
                if buffer:
                    segments.append({'text':" ".join(buffer),'speaker':current_speaker,
                                     'start':seg_idx*30,'end':seg_idx*30+30})
                    seg_idx += 1
                    buffer  = []
                current_speaker = m.group(1).strip()
                buffer.append(m.group(2).strip())
            else:
                buffer.append(line)
        if buffer:
            segments.append({'text':" ".join(buffer),'speaker':current_speaker,
                             'start':seg_idx*30,'end':seg_idx*30+30})
    else:
        speaker_label = {
            "Support Ticket":  "Customer",
            "Survey/Feedback": "Customer",
            "CRM Notes":       "Agent",
            "Social/Review":   "Customer",
            "Knowledge Base":  "System",
            "Product Usage":   "System",
            "Call Metadata":   "System",
        }.get(source_type, "Unknown")

        para, idx = [], 0
        for line in lines:
            if line == "":
                if para:
                    segments.append({'text':" ".join(para),'speaker':speaker_label,
                                     'start':idx*30,'end':idx*30+30})
                    idx += 1
                    para = []
            else:
                para.append(line)
        if para:
            segments.append({'text':" ".join(para),'speaker':speaker_label,
                             'start':idx*30,'end':idx*30+30})

    if not segments:
        segments = [{'text':raw_text[:4000],'speaker':'Unknown','start':0,'end':30}]
    return segments


def render(session):

    # ── Hero ─────────────────────────────────────────────────────────────────
    st.markdown("""
    <div style='background:linear-gradient(135deg,#0f2027,#203a43,#2c5364);
                border-radius:16px;padding:40px 36px;margin-bottom:28px;'>
        <div style='color:#fff;font-size:32px;font-weight:800;letter-spacing:-0.5px;'>
            🎧 EchoMind
        </div>
        <div style='color:#a8c7e8;font-size:16px;margin-top:6px;'>
            Analyse any customer interaction — 11 input types supported.
            Audio calls, chats, emails, tickets, surveys, CRM notes,
            social reviews, voice notes, product data, metadata and knowledge base.
        </div>
        <div style='margin-top:20px;display:flex;gap:10px;flex-wrap:wrap;'>
            <span style='background:rgba(255,255,255,0.12);color:#fff;border-radius:20px;padding:4px 12px;font-size:12px;'>🎙️ Call Recordings</span>
            <span style='background:rgba(255,255,255,0.12);color:#fff;border-radius:20px;padding:4px 12px;font-size:12px;'>💬 Chat / WhatsApp</span>
            <span style='background:rgba(255,255,255,0.12);color:#fff;border-radius:20px;padding:4px 12px;font-size:12px;'>📧 Email Threads</span>
            <span style='background:rgba(255,255,255,0.12);color:#fff;border-radius:20px;padding:4px 12px;font-size:12px;'>🎫 Support Tickets</span>
            <span style='background:rgba(255,255,255,0.12);color:#fff;border-radius:20px;padding:4px 12px;font-size:12px;'>⭐ Surveys & NPS</span>
            <span style='background:rgba(255,255,255,0.12);color:#fff;border-radius:20px;padding:4px 12px;font-size:12px;'>📋 CRM Notes</span>
            <span style='background:rgba(255,255,255,0.12);color:#fff;border-radius:20px;padding:4px 12px;font-size:12px;'>🌐 Social Reviews</span>
            <span style='background:rgba(255,255,255,0.12);color:#fff;border-radius:20px;padding:4px 12px;font-size:12px;'>🎤 Voice Notes</span>
            <span style='background:rgba(255,255,255,0.12);color:#fff;border-radius:20px;padding:4px 12px;font-size:12px;'>📊 Product Usage</span>
            <span style='background:rgba(255,255,255,0.12);color:#fff;border-radius:20px;padding:4px 12px;font-size:12px;'>📞 Call Metadata</span>
            <span style='background:rgba(255,255,255,0.12);color:#fff;border-radius:20px;padding:4px 12px;font-size:12px;'>📚 Knowledge Base</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    section_header("📥", "Choose Input Type", "Select the type of conversation or data you want to analyse")

    (src1, src2, src3, src4, src5,
     src6, src7, src8, src9, src10, src11) = st.tabs([
        "🎙️ Call Recording",
        "💬 Chat / WhatsApp",
        "📧 Email Thread",
        "🎫 Support Ticket",
        "⭐ Survey / Feedback",
        "📋 CRM Notes",
        "🌐 Social / Reviews",
        "🎤 Voice Notes",
        "📊 Product Usage",
        "📞 Call Metadata",
        "📚 Knowledge Base",
    ])

    # ════════════════════════════════════════════════════════════════════════
    # 1 — Call Recording (original pipeline, untouched)
    # ════════════════════════════════════════════════════════════════════════
    with src1:
        st.caption("Upload an audio or video call recording. AI transcribes, detects speakers, and analyses.")
        uploaded = st.file_uploader("Drop your audio or video file here",
            type=['mp3','wav','mp4','ogg','flac','webm','mkv'],
            label_visibility="collapsed", key="audio_uploader")

        if uploaded:
            col_info, col_btn = st.columns([3,1])
            with col_info:
                with st.container(border=True):
                    st.markdown(f"🎵 **{uploaded.name}**")
                    st.caption(f"{uploaded.size/1024:.1f} KB · Ready to process")
            with col_btn:
                st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
                process = st.button("🚀 Process", key="process_audio_btn",
                                    use_container_width=True, type="primary")
            if process:
                with tempfile.NamedTemporaryFile(delete=False,
                        suffix=os.path.splitext(uploaded.name)[1]) as f:
                    f.write(uploaded.read())
                    temp_path = f.name
                original_name  = uploaded.name
                safe_filename  = re.sub(r'[^A-Za-z0-9._-]', '_', original_name)
                call_id        = re.sub(r'[^A-Za-z0-9]', '_', original_name).upper()
                safe_temp_path = os.path.join(os.path.dirname(temp_path), safe_filename)
                os.rename(temp_path, safe_temp_path)
                temp_path = safe_temp_path

                with st.status("⚙️ Processing call...", expanded=True) as status:
                    st.write(f"📤 Uploading **{safe_filename}** to stage...")
                    session.file.put(temp_path, f"@{DB}.AUDIO_STAGE",
                                     auto_compress=False, overwrite=True)
                    st.write("🎙️ Transcribing with speaker diarization...")
                    tx_result = session.sql(f"""SELECT TO_VARCHAR(AI_TRANSCRIBE(
                        TO_FILE('@{DB}.AUDIO_STAGE','{safe_filename}'),
                        {{'timestamp_granularity':'speaker'}})) AS T""").collect()[0]['T']
                    tx_data  = json.loads(tx_result)
                    segments = tx_data.get('segments', [])
                    if not segments:
                        full_text = tx_data.get('text', '')
                        duration  = tx_data.get('audio_duration', 0)
                        segments  = [{'start':0,'end':duration,'text':full_text,'speaker':'UNKNOWN'}]

                    st.write(f"💾 Storing **{len(segments)}** segments...")
                    session.sql(f"DELETE FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{call_id}'").collect()
                    for i, seg in enumerate(segments):
                        text    = _sq(seg.get('text', ''))
                        speaker = seg.get('speaker', seg.get('speaker_label', 'UNKNOWN'))
                        start   = float(seg.get('start', 0))
                        end     = float(seg.get('end', 0))
                        session.sql(f"""INSERT INTO {DB}.CALL_SEGMENTS
                            (CALL_ID,SEGMENT_ID,SPEAKER,START_TIME,END_TIME,
                             SEGMENT_TEXT,SENTIMENT,EMBEDDING)
                            SELECT '{call_id}',{i},'{speaker}',{start},{end},'{text}',
                            SNOWFLAKE.CORTEX.SENTIMENT('{text}'),
                            SNOWFLAKE.CORTEX.EMBED_TEXT_1024(
                                'snowflake-arctic-embed-l-v2.0','{text}')""").collect()

                    st.write("🔗 Running topic clustering...")
                    session.sql(f"CALL {DB}.RUN_CLUSTERING('{call_id}')").collect()
                    st.write("💡 Generating insights...")
                    full_transcript = " ".join([s.get('text','') for s in segments])
                    safe_tx = _sq(full_transcript[:8000])
                    ins_result = session.sql(f"""SELECT SNOWFLAKE.CORTEX.COMPLETE('{CORTEX_MODEL}',
                        $$Analyze this call. Return JSON: {{"objections":"list",
                        "competitor_mentions":"list","buying_signals":"list",
                        "pricing_discussions":"list","action_items":"list",
                        "next_steps":"list","lead_intent_score":0-100}}
                        SCORING: order/purchased=85-100. Strong interest=60-84.
                        Neutral=30-59. Rejected/complained=0-29.
                        Call: {safe_tx}$$) AS R""").collect()[0]['R']
                    try:
                        ins = json.loads(_clean_json(ins_result))
                    except Exception:
                        ins = {}
                    session.sql(f"DELETE FROM {DB}.CALL_INSIGHTS WHERE CALL_ID='{call_id}'").collect()
                    session.sql(f"""INSERT INTO {DB}.CALL_INSIGHTS
                        (CALL_ID,OBJECTIONS,COMPETITOR_MENTIONS,BUYING_SIGNALS,
                         PRICING_DISCUSSIONS,ACTION_ITEMS,NEXT_STEPS,LEAD_INTENT_SCORE)
                        VALUES('{call_id}','{_sq(str(ins.get("objections","")))}',
                        '{_sq(str(ins.get("competitor_mentions","")))}',
                        '{_sq(str(ins.get("buying_signals","")))}',
                        '{_sq(str(ins.get("pricing_discussions","")))}',
                        '{_sq(str(ins.get("action_items","")))}',
                        '{_sq(str(ins.get("next_steps","")))}',
                        {int(ins.get('lead_intent_score',50))})""").collect()
                    status.update(label="✅ Base processing complete!", state="complete")

                enhance_call(session, call_id)
                st.session_state['last_call_id'] = call_id
                st.success(f"✅ **{call_id}** processed with {len(segments)} segments!")
                st.info("👉 Switch to the **Call Dashboard** tab to explore your insights.")
        else:
            c1, c2, c3, c4 = st.columns(4)
            for col, (num, title, desc) in zip([c1,c2,c3,c4],[
                ("1️⃣","Upload","Audio or video file"),
                ("2️⃣","Transcribe","AI detects speakers"),
                ("3️⃣","Analyse","Sentiment, KPIs, moments"),
                ("4️⃣","Act","Coaching & insights"),
            ]):
                with col:
                    with st.container(border=True):
                        st.markdown(f"**{num} {title}**")
                        st.caption(desc)

    # ════════════════════════════════════════════════════════════════════════
    # 2 — Chat / WhatsApp
    # ════════════════════════════════════════════════════════════════════════
    with src2:
        st.caption("Paste a chat transcript — WhatsApp, live chat, or in-app messaging.")
        with st.expander("📌 Accepted formats"):
            st.code("Agent: Hi, how can I help?\nCustomer: I have an issue with my order\n[Support] Let me check that for you\nJohn > The payment keeps failing")
        chat_name = st.text_input("Conversation name / ID", placeholder="e.g. LiveChat_2024_01_15", key="chat_name")
        chat_text = st.text_area("Paste chat transcript", height=280,
            placeholder="Agent: Hello, welcome to support!\nCustomer: Hi, I need help with my order...", key="chat_text")
        if st.button("🚀 Analyse Chat", key="process_chat_btn", type="primary"):
            if not chat_text.strip():
                st.warning("Please paste a chat transcript first.")
            else:
                call_id = re.sub(r'[^A-Za-z0-9]', '_', chat_name.strip() or "CHAT_CONVERSATION").upper()
                _run_pipeline(session, call_id, _parse_text_into_segments(chat_text, "Chat Conversation"), "Chat Conversation")

    # ════════════════════════════════════════════════════════════════════════
    # 3 — Email Thread
    # ════════════════════════════════════════════════════════════════════════
    with src3:
        st.caption("Paste a full email support thread. Each reply becomes a segment.")
        with st.expander("📌 Tips"):
            st.markdown("- Include `From:` headers for automatic speaker detection\n- Paste the full chain from oldest to newest\n- Supports forwarded threads and reply chains")
        email_name = st.text_input("Email thread / ticket ID", placeholder="e.g. Support_Ticket_98234", key="email_name")
        email_text = st.text_area("Paste email thread", height=280,
            placeholder="From: customer@email.com\nSubject: Issue with my order\n\nHi team, I have been waiting 5 days...\n\n---\nFrom: support@company.com\n\nHi, thank you for reaching out. I can see your order...", key="email_text")
        if st.button("🚀 Analyse Email Thread", key="process_email_btn", type="primary"):
            if not email_text.strip():
                st.warning("Please paste an email thread first.")
            else:
                call_id = re.sub(r'[^A-Za-z0-9]', '_', email_name.strip() or "EMAIL_THREAD").upper()
                _run_pipeline(session, call_id, _parse_text_into_segments(email_text, "Email Thread"), "Email Thread")

    # ════════════════════════════════════════════════════════════════════════
    # 4 — Support Ticket
    # ════════════════════════════════════════════════════════════════════════
    with src4:
        st.caption("Paste a support ticket — description, agent responses, and resolution notes.")
        t1, t2 = st.columns(2)
        with t1:
            ticket_id  = st.text_input("Ticket ID", placeholder="e.g. TKT-48291", key="ticket_id")
            ticket_cat = st.selectbox("Category", ["Technical","Billing","Shipping","Returns","Account","Product","Other"], key="ticket_cat")
        with t2:
            ticket_pri = st.selectbox("Priority", ["Critical","High","Medium","Low"], key="ticket_pri")
            ticket_sta = st.selectbox("Status", ["Open","In Progress","Resolved","Closed","Escalated"], key="ticket_sta")
        ticket_text = st.text_area("Paste ticket content", height=250,
            placeholder="Customer: My internet has been down for 3 days...\nAgent: Thank you for contacting us...\nCustomer: This is unacceptable!", key="ticket_text")
        if st.button("🚀 Analyse Ticket", key="process_ticket_btn", type="primary"):
            if not ticket_text.strip():
                st.warning("Please paste the ticket content first.")
            else:
                call_id = re.sub(r'[^A-Za-z0-9]', '_', ticket_id.strip() or "SUPPORT_TICKET").upper()
                meta    = f"Category: {ticket_cat}. Priority: {ticket_pri}. Status: {ticket_sta}.\n\n"
                _run_pipeline(session, call_id, _parse_text_into_segments(meta + ticket_text, "Support Ticket"), "Support Ticket")

    # ════════════════════════════════════════════════════════════════════════
    # 5 — Survey / Feedback / NPS
    # ════════════════════════════════════════════════════════════════════════
    with src5:
        st.caption("Paste customer survey responses, NPS feedback, or form submissions.")
        s1, s2 = st.columns(2)
        with s1:
            survey_name = st.text_input("Survey name", placeholder="e.g. NPS_Q1_2024", key="survey_name")
            survey_type = st.selectbox("Feedback type", ["NPS Survey","CSAT Survey","Product Feedback","Post-Call Survey","App Review","Exit Survey"], key="survey_type")
        with s2:
            nps_score  = st.slider("NPS / Rating (if applicable)", 0, 10, 5, key="nps_score")
            survey_sent= st.selectbox("Overall sentiment", ["Positive","Neutral","Negative"], key="survey_sent")
        survey_text = st.text_area("Paste feedback / responses", height=250,
            placeholder="Q: How satisfied are you with our service?\nA: Very disappointed. The agent didn't solve my problem.\n\nQ: Would you recommend us?\nA: Absolutely not.", key="survey_text")
        if st.button("🚀 Analyse Feedback", key="process_survey_btn", type="primary"):
            if not survey_text.strip():
                st.warning("Please paste the survey/feedback content first.")
            else:
                call_id = re.sub(r'[^A-Za-z0-9]', '_', survey_name.strip() or "SURVEY_FEEDBACK").upper()
                meta    = f"Type: {survey_type}. Score: {nps_score}/10. Sentiment: {survey_sent}.\n\n"
                _run_pipeline(session, call_id, _parse_text_into_segments(meta + survey_text, "Survey/Feedback"), "Survey/Feedback")

    # ════════════════════════════════════════════════════════════════════════
    # 6 — CRM Notes / Activity Logs
    # ════════════════════════════════════════════════════════════════════════
    with src6:
        st.caption("Paste CRM activity logs, call notes, meeting notes, or field sales notes.")
        c1, c2 = st.columns(2)
        with c1:
            crm_name  = st.text_input("Record / Deal name", placeholder="e.g. Deal_Acme_Corp_Q1", key="crm_name")
            crm_type  = st.selectbox("Note type", ["Call Notes","Meeting Notes","Field Sales Notes","Activity Log","Voice Note Transcript","Follow-Up Notes"], key="crm_type")
        with c2:
            crm_agent = st.text_input("Agent / Rep name", placeholder="e.g. Priya Sharma", key="crm_agent")
            crm_stage = st.selectbox("Deal / Case stage", ["Prospecting","Discovery","Proposal","Negotiation","Closed Won","Closed Lost","Support","Escalated"], key="crm_stage")
        crm_text = st.text_area("Paste CRM notes / activity log", height=250,
            placeholder="Date: 2024-01-15\nSpoke with John at Acme Corp. Strong interest in Enterprise plan but raised pricing concerns. Competitor mentioned: Salesforce. Follow-up scheduled for Monday.", key="crm_text")
        if st.button("🚀 Analyse CRM Notes", key="process_crm_btn", type="primary"):
            if not crm_text.strip():
                st.warning("Please paste the CRM notes first.")
            else:
                call_id = re.sub(r'[^A-Za-z0-9]', '_', crm_name.strip() or "CRM_NOTES").upper()
                agent   = crm_agent.strip() or "Agent"
                meta    = f"Type: {crm_type}. Stage: {crm_stage}. Rep: {agent}.\n\n"
                segs    = _parse_text_into_segments(meta + crm_text, "CRM Notes")
                for s in segs:
                    if s['speaker'] in ('Unknown','Agent','System'):
                        s['speaker'] = agent
                _run_pipeline(session, call_id, segs, "CRM Notes")

    # ════════════════════════════════════════════════════════════════════════
    # 7 — Social Media & Reviews
    # ════════════════════════════════════════════════════════════════════════
    with src7:
        st.caption("Paste social media comments, app store reviews, or online feedback for AI sentiment and insight analysis.")
        r1, r2 = st.columns(2)
        with r1:
            review_name = st.text_input("Batch name / product name", placeholder="e.g. AppStore_Reviews_Jan2024", key="review_name")
            review_platform = st.selectbox("Platform", ["App Store","Google Play","Trustpilot","G2","Twitter/X","LinkedIn","Facebook","Reddit","Other"], key="review_platform")
        with r2:
            review_product = st.text_input("Product / Service name", placeholder="e.g. EchoMind App", key="review_product")
            review_period  = st.text_input("Time period (optional)", placeholder="e.g. Jan 2024", key="review_period")
        with st.expander("📌 Format tips"):
            st.markdown("""
- Paste one review per paragraph (blank line between reviews)
- Optionally prefix with star rating: `★★★☆☆ The product is okay but...`
- Or paste raw review text without formatting — AI will interpret it
            """)
        review_text = st.text_area("Paste reviews / comments", height=280,
            placeholder="★☆☆☆☆ Terrible experience. The app crashed 3 times and customer support was unhelpful.\n\n★★★★★ Amazing product! Support team resolved my issue within minutes. Highly recommend.\n\n★★☆☆☆ Decent product but pricing is way too high compared to competitors.", key="review_text")
        if st.button("🚀 Analyse Reviews", key="process_review_btn", type="primary"):
            if not review_text.strip():
                st.warning("Please paste reviews or comments first.")
            else:
                call_id = re.sub(r'[^A-Za-z0-9]', '_', review_name.strip() or "SOCIAL_REVIEWS").upper()
                meta    = f"Platform: {review_platform}. Product: {review_product}. Period: {review_period}.\n\n"
                segs    = _parse_text_into_segments(meta + review_text, "Social/Review")
                # Each paragraph = one reviewer = one Customer segment
                for s in segs:
                    s['speaker'] = 'Customer'
                _run_pipeline(session, call_id, segs, "Social/Reviews")

    # ════════════════════════════════════════════════════════════════════════
    # 8 — Voice Notes / Field Sales
    # ════════════════════════════════════════════════════════════════════════
    with src8:
        st.caption("Upload a voice note or field sales audio recording for transcription and analysis.")
        with st.container(border=True):
            st.markdown("**Two options:**")
            vn_option = st.radio("Input method", ["Upload audio file","Paste transcript text"], key="vn_option", horizontal=True)

        if vn_option == "Upload audio file":
            vn_uploaded = st.file_uploader("Upload voice note / field recording",
                type=['mp3','wav','mp4','ogg','flac','webm','m4a'],
                label_visibility="collapsed", key="vn_audio_uploader")
            vn_agent = st.text_input("Sales rep / Field agent name", placeholder="e.g. Rahul Verma", key="vn_agent")
            vn_name  = st.text_input("Note / Visit name", placeholder="e.g. ClientVisit_TataMotors_Jan15", key="vn_name")

            if vn_uploaded:
                with st.container(border=True):
                    st.markdown(f"🎤 **{vn_uploaded.name}**")
                    st.caption(f"{vn_uploaded.size/1024:.1f} KB · Ready to process")
                if st.button("🚀 Process Voice Note", key="process_vn_audio_btn", type="primary"):
                    with tempfile.NamedTemporaryFile(delete=False,
                            suffix=os.path.splitext(vn_uploaded.name)[1]) as f:
                        f.write(vn_uploaded.read())
                        temp_path = f.name
                    original_name  = vn_uploaded.name
                    safe_filename  = re.sub(r'[^A-Za-z0-9._-]', '_', original_name)
                    base_name      = vn_name.strip() or original_name
                    call_id        = re.sub(r'[^A-Za-z0-9]', '_', base_name).upper()
                    safe_temp_path = os.path.join(os.path.dirname(temp_path), safe_filename)
                    os.rename(temp_path, safe_temp_path)

                    with st.status("⚙️ Processing voice note...", expanded=True) as status:
                        st.write(f"📤 Uploading to stage...")
                        session.file.put(safe_temp_path, f"@{DB}.AUDIO_STAGE",
                                         auto_compress=False, overwrite=True)
                        st.write("🎙️ Transcribing...")
                        tx_result = session.sql(f"""SELECT TO_VARCHAR(AI_TRANSCRIBE(
                            TO_FILE('@{DB}.AUDIO_STAGE','{safe_filename}'),
                            {{'timestamp_granularity':'speaker'}})) AS T""").collect()[0]['T']
                        tx_data  = json.loads(tx_result)
                        segments = tx_data.get('segments', [])
                        if not segments:
                            full_text = tx_data.get('text','')
                            duration  = tx_data.get('audio_duration', 0)
                            segments  = [{'start':0,'end':duration,'text':full_text,'speaker': vn_agent.strip() or 'Agent'}]
                        else:
                            agent_name = vn_agent.strip() or 'Agent'
                            for seg in segments:
                                if not seg.get('speaker') or seg.get('speaker') == 'UNKNOWN':
                                    seg['speaker'] = agent_name
                        status.update(label="✅ Transcription complete!", state="complete")

                    _run_pipeline(session, call_id, [
                        {'text': _sq(s.get('text','')),
                         'speaker': s.get('speaker', vn_agent.strip() or 'Agent'),
                         'start': float(s.get('start',0)),
                         'end': float(s.get('end',30))}
                        for s in segments
                    ], "Voice Note")

        else:
            vn_agent2 = st.text_input("Sales rep / Field agent name", placeholder="e.g. Rahul Verma", key="vn_agent2")
            vn_name2  = st.text_input("Note / Visit name", placeholder="e.g. ClientVisit_TataMotors_Jan15", key="vn_name2")
            vn_text   = st.text_area("Paste voice note transcript", height=250,
                placeholder="Visited Tata Motors today. Met with procurement head. They're interested in the full suite. Main concern is integration timeline. Competitor pitch from SAP happened last week. Need to send proposal by Friday and schedule a demo for next Wednesday.", key="vn_text")
            if st.button("🚀 Analyse Voice Note", key="process_vn_text_btn", type="primary"):
                if not vn_text.strip():
                    st.warning("Please paste the voice note transcript first.")
                else:
                    call_id = re.sub(r'[^A-Za-z0-9]', '_', vn_name2.strip() or "VOICE_NOTE").upper()
                    agent   = vn_agent2.strip() or "Agent"
                    meta    = f"Type: Voice Note / Field Sales. Rep: {agent}.\n\n"
                    segs    = _parse_text_into_segments(meta + vn_text, "CRM Notes")
                    for s in segs:
                        s['speaker'] = agent
                    _run_pipeline(session, call_id, segs, "Voice Note")

    # ════════════════════════════════════════════════════════════════════════
    # 9 — Product Usage Data
    # ════════════════════════════════════════════════════════════════════════
    with src9:
        st.caption("Paste or describe product usage events, user behaviour logs, or feature interaction data. AI will interpret patterns and generate insights.")
        with st.expander("📌 What to include"):
            st.markdown("""
- Feature usage frequency (e.g. "User clicked Export 12 times, never used Reports")
- Drop-off points (e.g. "User abandoned checkout at payment step 3 times")
- Error logs with user context
- Session summaries from analytics tools (Mixpanel, Amplitude, etc.)
- CSV data pasted as text
            """)
        pu1, pu2 = st.columns(2)
        with pu1:
            pu_name    = st.text_input("User / Segment name", placeholder="e.g. User_12345 or Enterprise_Segment", key="pu_name")
            pu_product = st.text_input("Product / Feature name", placeholder="e.g. EchoMind Dashboard", key="pu_product")
        with pu2:
            pu_period  = st.text_input("Time period", placeholder="e.g. Last 30 days", key="pu_period")
            pu_type    = st.selectbox("Data type", ["Feature Usage Log","Session Summary","Drop-off Analysis","Error Log","Behavioural Events","Cohort Data"], key="pu_type")

        pu_text = st.text_area("Paste product usage data / events", height=280,
            placeholder="User: Enterprise_Client_Acme\nPeriod: Jan 2024\n\nFeature: Dashboard — 45 visits\nFeature: Reports — 2 visits (low engagement)\nFeature: Export — 0 visits (never used)\nAction: Clicked upgrade button 3 times but did not complete\nError: Payment failed 2 times\nDrop-off: Abandoned onboarding at Step 3 (integrations setup)\nSession length: Avg 4 mins (below benchmark of 12 mins)", key="pu_text")

        if st.button("🚀 Analyse Product Usage", key="process_pu_btn", type="primary"):
            if not pu_text.strip():
                st.warning("Please paste product usage data first.")
            else:
                call_id = re.sub(r'[^A-Za-z0-9]', '_', pu_name.strip() or "PRODUCT_USAGE").upper()
                meta    = f"Product: {pu_product}. Period: {pu_period}. Data type: {pu_type}.\n\n"
                # Convert usage data into interpretable narrative segments
                segs    = _parse_text_into_segments(meta + pu_text, "Product Usage")
                for s in segs:
                    s['speaker'] = 'Customer'  # product user = customer perspective
                _run_pipeline(session, call_id, segs, "Product Usage Data")

    # ════════════════════════════════════════════════════════════════════════
    # 10 — Call Center Metadata
    # ════════════════════════════════════════════════════════════════════════
    with src10:
        st.caption("Enter call center metadata — queue time, hold time, transfers, channel, agent info. AI will diagnose operational issues and generate insights.")

        st.markdown("#### Call Details")
        m1, m2, m3 = st.columns(3)
        with m1:
            meta_call_id   = st.text_input("Call / Case ID", placeholder="e.g. CALL-20240115-4829", key="meta_call_id")
            meta_agent     = st.text_input("Agent ID / Name", placeholder="e.g. AGT-042 / Priya", key="meta_agent")
            meta_channel   = st.selectbox("Channel", ["Inbound Call","Outbound Call","Chat","Email","Social","Walk-in"], key="meta_channel")
        with m2:
            meta_queue     = st.number_input("Queue wait time (seconds)", 0, 3600, 120, key="meta_queue")
            meta_handle    = st.number_input("Handle time (seconds)", 0, 7200, 300, key="meta_handle")
            meta_hold      = st.number_input("Total hold time (seconds)", 0, 3600, 0, key="meta_hold")
        with m3:
            meta_transfers = st.number_input("Number of transfers", 0, 10, 0, key="meta_transfers")
            meta_repeat    = st.checkbox("Repeat caller?", key="meta_repeat")
            meta_resolved  = st.selectbox("Resolution", ["Resolved","Unresolved","Escalated","Callback Scheduled","Partial"], key="meta_resolved")

        st.markdown("#### Issue & Outcome")
        m4, m5 = st.columns(2)
        with m4:
            meta_issue    = st.text_input("Issue type / category", placeholder="e.g. Billing dispute", key="meta_issue")
            meta_csat     = st.selectbox("CSAT (if captured)", ["Not captured","Positive","Neutral","Negative"], key="meta_csat")
        with m5:
            meta_outcome  = st.text_input("Call outcome / notes", placeholder="e.g. Refund issued, customer satisfied", key="meta_outcome")
            meta_followup = st.text_input("Follow-up required", placeholder="e.g. Email confirmation in 24h", key="meta_followup")

        meta_notes = st.text_area("Additional notes (optional)", height=120,
            placeholder="Customer mentioned they had called 3 times before. Agent struggled with the billing system. Supervisor approval needed for refund.", key="meta_notes")

        if st.button("🚀 Analyse Call Metadata", key="process_meta_btn", type="primary"):
            if not meta_call_id.strip():
                st.warning("Please enter a Call / Case ID.")
            else:
                call_id = re.sub(r'[^A-Za-z0-9]', '_', meta_call_id.strip()).upper()
                agent   = meta_agent.strip() or "Agent"
                # Build a narrative from metadata fields
                narrative = f"""Call Metadata Analysis:
Agent: {agent} | Channel: {meta_channel} | Resolution: {meta_resolved}
Queue wait: {meta_queue}s | Handle time: {meta_handle}s | Hold time: {meta_hold}s
Transfers: {meta_transfers} | Repeat caller: {'Yes' if meta_repeat else 'No'}
Issue type: {meta_issue} | CSAT: {meta_csat}
Outcome: {meta_outcome}
Follow-up required: {meta_followup}

Operational observations:
Queue time of {meta_queue} seconds {'is high and may indicate staffing issues' if meta_queue > 180 else 'is within acceptable range'}.
Handle time of {meta_handle} seconds {'suggests a complex issue' if meta_handle > 600 else 'is standard'}.
Hold time of {meta_hold} seconds {'indicates the agent needed supervisor or system help' if meta_hold > 60 else 'was minimal'}.
{'Multiple transfers occurred which indicates routing or knowledge gaps.' if meta_transfers > 1 else ''}
{'This is a repeat caller indicating first call resolution failure.' if meta_repeat else ''}

Additional notes: {meta_notes}"""

                segs = [
                    {'text': narrative, 'speaker': agent, 'start': 0, 'end': meta_handle or 300},
                ]
                if meta_notes.strip():
                    segs.append({'text': meta_notes, 'speaker': agent, 'start': meta_handle or 300, 'end': (meta_handle or 300) + 60})
                _run_pipeline(session, call_id, segs, "Call Metadata")

    # ════════════════════════════════════════════════════════════════════════
    # 11 — Knowledge Base & FAQs
    # ════════════════════════════════════════════════════════════════════════
    with src11:
        st.caption("Paste KB articles or FAQs. AI will analyse gaps, flag unclear answers, and map content to common customer issues.")
        with st.expander("📌 What you get from this"):
            st.markdown("""
- **Gap analysis** — which customer issues aren't covered
- **Clarity score** — are answers clear and actionable?
- **Topic mapping** — which KB articles map to which call topics
- **Improvement suggestions** — what should be added or rewritten
- **Action items** — specific KB updates recommended
            """)
        kb1, kb2 = st.columns(2)
        with kb1:
            kb_name    = st.text_input("KB article / FAQ batch name", placeholder="e.g. Billing_FAQ_v3", key="kb_name")
            kb_product = st.text_input("Product / Service", placeholder="e.g. EchoMind", key="kb_product")
        with kb2:
            kb_type    = st.selectbox("Content type", ["FAQ Document","KB Article","Help Center Page","Product Manual","Troubleshooting Guide","Onboarding Guide"], key="kb_type")
            kb_audience= st.selectbox("Target audience", ["End Customer","Support Agent","Both"], key="kb_audience")

        kb_text = st.text_area("Paste KB content / FAQ here", height=300,
            placeholder="Q: How do I reset my password?\nA: Click Forgot Password on the login page.\n\nQ: Why is my payment failing?\nA: Check your card details are correct.\n\nQ: How do I cancel my subscription?\nA: Contact support.", key="kb_text")

        if st.button("🚀 Analyse Knowledge Base", key="process_kb_btn", type="primary"):
            if not kb_text.strip():
                st.warning("Please paste KB / FAQ content first.")
            else:
                call_id = re.sub(r'[^A-Za-z0-9]', '_', kb_name.strip() or "KNOWLEDGE_BASE").upper()
                meta    = f"Type: {kb_type}. Product: {kb_product}. Audience: {kb_audience}.\nAnalyse this knowledge base for gaps, clarity issues, and improvement opportunities.\n\n"
                segs    = _parse_text_into_segments(meta + kb_text, "Knowledge Base")
                for s in segs:
                    s['speaker'] = 'System'
                _run_pipeline(session, call_id, segs, "Knowledge Base")

    # ── Previously processed ─────────────────────────────────────────────────
    st.markdown("---")
    section_header("🗂️", "Previously Processed")

    prev = session.sql(f"""
        SELECT c.CALL_ID, COUNT(c.SEGMENT_ID) AS SEGS,
               ROUND(MAX(c.END_TIME),0) AS DUR,
               COALESCE(i.RESOLUTION_STATUS,'—') AS RES,
               COALESCE(i.CSAT_INDICATOR,'—') AS CSAT,
               COALESCE(i.LEAD_INTENT_SCORE,0) AS LEAD
        FROM {DB}.CALL_SEGMENTS c
        LEFT JOIN {DB}.CALL_INSIGHTS i ON c.CALL_ID=i.CALL_ID
        GROUP BY c.CALL_ID,i.RESOLUTION_STATUS,i.CSAT_INDICATOR,i.LEAD_INTENT_SCORE
        ORDER BY c.CALL_ID DESC LIMIT 10
    """).to_pandas()

    if len(prev) == 0:
        st.caption("No records processed yet.")
    else:
        for _, row in prev.iterrows():
            res_icon  = {"Resolved":"✅","Unresolved":"❌","Partial":"🟡","Escalated":"🔺","—":"—"}.get(row['RES'],"—")
            csat_icon = {"Positive":"😊","Neutral":"😐","Negative":"😞","—":"—"}.get(row['CSAT'],"—")
            dur_m, dur_s = int(row['DUR']//60), int(row['DUR']%60)
            is_active = row['CALL_ID'] == st.session_state.get('last_call_id')
            rc1, rc2  = st.columns([5, 1])
            with rc1:
                with st.container(border=True):
                    active_badge = " 🔵 **ACTIVE**" if is_active else ""
                    st.markdown(f"**{row['CALL_ID']}**{active_badge}")
                    st.caption(
                        f"⏱ {dur_m}m {dur_s}s  ·  💬 {int(row['SEGS'])} segs  ·  "
                        f"{res_icon} {row['RES']}  ·  {csat_icon} {row['CSAT']}  ·  "
                        f"🎯 {int(row['LEAD'])}/100"
                    )
            with rc2:
                st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
                if st.button("Load", key=f"load_{row['CALL_ID']}", use_container_width=True):
                    st.session_state['last_call_id'] = row['CALL_ID']
                    st.rerun()