import streamlit as st
import json
import re
import tempfile
import os
from utils import DB, CORTEX_MODEL, _sq, _clean_json, enhance_call

def render(session):
    st.markdown("## 📤 Upload & Process")
    st.caption("Upload a call recording to begin analysis.")

    uploaded = st.file_uploader(
        "Upload audio/video file",
        type=['mp3','wav','mp4','ogg','flac','webm','mkv']
    )

    if uploaded:
        st.success(f"**{uploaded.name}** uploaded ({uploaded.size / 1024:.1f} KB) — ready to process.")

    if uploaded and st.button("Process call", key="process_btn"):
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded.name)[1]) as f:
            f.write(uploaded.read())
            temp_path = f.name

        filename = uploaded.name
        call_id = re.sub(r'[^A-Za-z0-9]', '_', filename).upper()
        st.session_state['last_call_id'] = call_id

        with st.status("Processing call...", expanded=True) as status:
            st.write(f"Uploading {filename} to stage...")
            session.file.put(temp_path, f"@{DB}.AUDIO_STAGE", auto_compress=False, overwrite=True)

            st.write("Transcribing with speaker diarization...")
            tx_result = session.sql(f"""SELECT TO_VARCHAR(AI_TRANSCRIBE(TO_FILE('@{DB}.AUDIO_STAGE','{filename}'),
                {{'timestamp_granularity':'speaker'}})) AS T""").collect()[0]['T']
            tx_data = json.loads(tx_result)
            segments = tx_data.get('segments', [])
            if not segments:
                full_text = tx_data.get('text', '')
                duration = tx_data.get('audio_duration', 0)
                segments = [{'start': 0, 'end': duration, 'text': full_text, 'speaker': 'UNKNOWN'}]

            st.write(f"Processing {len(segments)} segments...")
            session.sql(f"DELETE FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{call_id}'").collect()
            for i, seg in enumerate(segments):
                text = _sq(seg.get('text', ''))
                speaker = seg.get('speaker', seg.get('speaker_label', 'UNKNOWN'))
                start = float(seg.get('start', 0))
                end = float(seg.get('end', 0))
                session.sql(f"""INSERT INTO {DB}.CALL_SEGMENTS (CALL_ID,SEGMENT_ID,SPEAKER,START_TIME,END_TIME,SEGMENT_TEXT,SENTIMENT,EMBEDDING)
                    SELECT '{call_id}',{i},'{speaker}',{start},{end},'{text}',
                    SNOWFLAKE.CORTEX.SENTIMENT('{text}'),
                    SNOWFLAKE.CORTEX.EMBED_TEXT_1024('snowflake-arctic-embed-l-v2.0','{text}')""").collect()

            st.write("Running clustering...")
            session.sql(f"CALL {DB}.RUN_CLUSTERING('{call_id}')").collect()

            st.write("Generating insights...")
            full_transcript = " ".join([s.get('text','') for s in segments])
            safe_tx = _sq(full_transcript[:8000])
            ins_result = session.sql(f"""SELECT SNOWFLAKE.CORTEX.COMPLETE('{CORTEX_MODEL}',
                $$Analyze this call. Return JSON: {{"objections":"list","competitor_mentions":"list","buying_signals":"list","pricing_discussions":"list","action_items":"list","next_steps":"list","lead_intent_score":0-100}}
                SCORING: If customer placed order/purchased = 85-100. Strong interest = 60-84. Neutral = 30-59. Rejected/complained = 0-29. Consider action items and positive sentiment as positive signals.
                Call: {safe_tx}$$) AS R""").collect()[0]['R']
            try:
                ins = json.loads(_clean_json(ins_result))
            except Exception:
                ins = {}

            session.sql(f"DELETE FROM {DB}.CALL_INSIGHTS WHERE CALL_ID='{call_id}'").collect()
            session.sql(f"""INSERT INTO {DB}.CALL_INSIGHTS (CALL_ID,OBJECTIONS,COMPETITOR_MENTIONS,BUYING_SIGNALS,PRICING_DISCUSSIONS,ACTION_ITEMS,NEXT_STEPS,LEAD_INTENT_SCORE)
                VALUES('{call_id}','{_sq(str(ins.get("objections","")))}','{_sq(str(ins.get("competitor_mentions","")))}',
                '{_sq(str(ins.get("buying_signals","")))}','{_sq(str(ins.get("pricing_discussions","")))}',
                '{_sq(str(ins.get("action_items","")))}','{_sq(str(ins.get("next_steps","")))}',
                {int(ins.get('lead_intent_score',50))})""").collect()

            status.update(label="Base processing complete!", state="complete")

        enhance_call(session, call_id)
        st.success(f"✅ Call `{call_id}` fully processed with {len(segments)} segments!")
        st.info("👉 Head to the **Insights** tab to explore the analysis.")
