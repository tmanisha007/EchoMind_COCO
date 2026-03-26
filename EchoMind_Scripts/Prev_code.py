import streamlit as st
import json
import pandas as pd
from snowflake.snowpark.context import get_active_session
from collections import Counter

st.set_page_config(page_title="EchoMind", page_icon="🎧", layout="wide")
session = get_active_session()

CORTEX_MODEL = 'claude-4-sonnet'
DB = 'ECHOMIND_DB.APP'

# ── Helper: default selectbox index to last processed call ──────────────────
def _default_index(call_list, default_id=None):
    cid = default_id or st.session_state.get('last_call_id')
    if cid and cid in call_list:
        return call_list.index(cid)
    return 0

def _cortex(prompt):
    safe = prompt.replace('$$', '$ $')
    return session.sql(f"SELECT SNOWFLAKE.CORTEX.COMPLETE('{CORTEX_MODEL}', $${safe}$$) AS R").collect()[0]['R']

def _clean_json(raw):
    return raw.strip().replace('```json', '').replace('```', '').strip()

def _sq(v):
    return str(v or '').replace("'", "''")

def map_speaker_roles(call_id):
    segs = session.sql(f"SELECT SEGMENT_ID, SPEAKER, SEGMENT_TEXT FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{call_id}' ORDER BY START_TIME").to_pandas()
    if len(segs) == 0:
        return
    lines = [f"[{r['SEGMENT_ID']}] ({r['SPEAKER']}) {r['SEGMENT_TEXT']}" for _, r in segs.iterrows()]
    transcript = "\n".join(lines)
    prompt = f"""Given this call transcript with speaker labels, map each speaker to "Agent" or "Customer".
Rules: Agent greets first, states company name, asks how to help, provides solutions. Customer describes problems, asks about products, expresses frustration.
Return ONLY a JSON object mapping speaker labels to roles, e.g. {{"SPEAKER_00":"Agent","SPEAKER_01":"Customer","UNKNOWN":"Unknown"}}

Transcript:
{transcript}"""
    try:
        result = _cortex(prompt)
        mapping = json.loads(_clean_json(result))
        for label, role in mapping.items():
            session.sql(f"UPDATE {DB}.CALL_SEGMENTS SET SPEAKER_ROLE='{_sq(role)}' WHERE CALL_ID='{call_id}' AND SPEAKER='{_sq(label)}'").collect()
    except Exception as e:
        st.warning(f"Speaker role mapping partial: {e}")

def standardize_topics_and_moments(call_id):
    segs = session.sql(f"SELECT SEGMENT_ID, SEGMENT_TEXT, SENTIMENT FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{call_id}' ORDER BY START_TIME").to_pandas()
    if len(segs) == 0:
        return
    lines = [f"[{r['SEGMENT_ID']}] (sent:{r['SENTIMENT']:.2f}) {r['SEGMENT_TEXT']}" for _, r in segs.iterrows()]
    prompt = f"""Analyze each segment of this call. For each, provide:
1. Standard topic from EXACTLY: Greeting, Identity_Verification, Intent_Discovery, Troubleshooting, Frustration, Escalation, Resolution, Pricing, Objection, Closing, Follow_Up, Product_Info, Small_Talk
2. Whether it's a key moment (frustration, escalation request, complaint, buying signal, resolution, positive feedback)

Return ONLY a JSON array for ALL segments:
[{{"id":0,"topic":"Greeting","key_moment":false,"moment_type":null,"severity":null}},...]
moment_type options: Frustration, Escalation_Request, Buying_Signal, Objection, Resolution, Complaint, Positive_Feedback
severity: high, medium, low (only when key_moment true)

Segments:
{chr(10).join(lines)}"""
    try:
        items = json.loads(_clean_json(_cortex(prompt)))
        session.sql(f"DELETE FROM {DB}.CALL_KEY_MOMENTS WHERE CALL_ID='{call_id}'").collect()
        for item in items:
            sid = int(item['id'])
            topic = _sq(item['topic'])
            is_km = bool(item.get('key_moment', False))
            mt = _sq(item.get('moment_type') or '')
            sev = _sq(item.get('severity') or '')
            session.sql(f"""UPDATE {DB}.CALL_SEGMENTS SET STANDARD_TOPIC='{topic}', IS_KEY_MOMENT={is_km},
                MOMENT_TYPE=NULLIF('{mt}',''), MOMENT_SEVERITY=NULLIF('{sev}','')
                WHERE CALL_ID='{call_id}' AND SEGMENT_ID={sid}""").collect()
            if is_km and mt:
                session.sql(f"""INSERT INTO {DB}.CALL_KEY_MOMENTS (CALL_ID,SEGMENT_ID,MOMENT_TYPE,SEVERITY,START_TIME,END_TIME,SEGMENT_TEXT)
                    SELECT '{call_id}',{sid},'{mt}','{sev}',START_TIME,END_TIME,SEGMENT_TEXT
                    FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{call_id}' AND SEGMENT_ID={sid}""").collect()
    except Exception as e:
        st.warning(f"Topic/moment analysis partial: {e}")

def extract_call_kpis(call_id):
    segs = session.sql(f"SELECT COALESCE(SPEAKER_ROLE,SPEAKER) AS SPK, SEGMENT_TEXT FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{call_id}' ORDER BY START_TIME").to_pandas()
    if len(segs) == 0:
        return
    lines = [f"{r['SPK']}: {r['SEGMENT_TEXT']}" for _, r in segs.iterrows()]
    prompt = f"""Analyze this call and extract KPIs. Return ONLY valid JSON:
{{"resolution_status":"Resolved|Unresolved|Partial|Escalated","escalation_flag":true|false,"csat_indicator":"Positive|Neutral|Negative","call_outcome":"one sentence","issue_type":"category","root_cause":"brief or null"}}

Transcript:
{chr(10).join(lines)}"""
    try:
        kpis = json.loads(_clean_json(_cortex(prompt)))
        session.sql(f"""UPDATE {DB}.CALL_INSIGHTS SET
            RESOLUTION_STATUS='{_sq(kpis.get("resolution_status"))}',
            ESCALATION_FLAG={bool(kpis.get('escalation_flag',False))},
            CSAT_INDICATOR='{_sq(kpis.get("csat_indicator"))}',
            CALL_OUTCOME='{_sq(kpis.get("call_outcome"))}',
            ISSUE_TYPE='{_sq(kpis.get("issue_type"))}',
            ROOT_CAUSE='{_sq(kpis.get("root_cause"))}'
            WHERE CALL_ID='{call_id}'""").collect()
    except Exception as e:
        st.warning(f"KPI extraction partial: {e}")

def enhance_call(call_id):
    with st.status("Enhancing call analysis...", expanded=True) as status:
        st.write("Mapping speaker roles (Agent vs Customer)...")
        map_speaker_roles(call_id)
        st.write("Standardizing topics & detecting key moments...")
        standardize_topics_and_moments(call_id)
        st.write("Extracting structured KPIs...")
        extract_call_kpis(call_id)
        status.update(label="Enhancement complete!", state="complete")

if 'last_call_id' not in st.session_state:
    st.session_state['last_call_id'] = None
if 'call_tags' not in st.session_state:
    st.session_state['call_tags'] = {}
if 'call_notes' not in st.session_state:
    st.session_state['call_notes'] = {}

st.title("🎧 EchoMind")
st.caption("AI-Powered Call Analytics · Snowflake Cortex AI")

# ── Tab order: matches requested flow, all 19 tabs present ──────────────────
# Upload & Process → Call Dashboard → Key Moments → Topic Clusters →
# Full Transcript → Call Scorecard → Ask EchoMind → Coaching Tips →
# Tags & Notes → Follow-Up Email → Topic Trends → Previous Runs →
# Compare Calls → Speaker Dynamics → Leaderboard →
# (remaining originals) AI Summary, Sentiment, Call Journey, Re-Analyze
(tab1, tab3, tab5, tab6, tab2, tab15,
 tab_ask, tab7, tab13, tab_email,
 tab14, tab_prev, tab9, tab12, tab10,
 tab4, tab8, tab11, tab16) = st.tabs([
    "📤 Upload & Process",
    "📊 Call Dashboard",
    "⭐ Key Moments",
    "🧩 Topic Clusters",
    "📜 Full Transcript",
    "📋 Call Scorecard",
    "💬 Ask EchoMind",
    "💡 Coaching Tips",
    "🏷️ Tags & Notes",
    "📧 Follow-Up Email",
    "🔄 Topic Trends",
    "🗂️ Previous Runs",
    "🔍 Compare Calls",
    "🗣️ Speaker Dynamics",
    "🏆 Leaderboard",
    "🤖 AI Summary",
    "📈 Sentiment",
    "🗺️ Call Journey",
    "🔄 Re-Analyze",
])

# ── Tab 1 · Upload & Process ─────────────────────────────────────────────────
with tab1:
    st.markdown("## Upload & process")
    uploaded = st.file_uploader("Upload audio/video file", type=['mp3','wav','mp4','ogg','flac','webm','mkv'])
    if uploaded:
        st.success(f"**{uploaded.name}** uploaded ({uploaded.size / 1024:.1f} KB) — ready to process.")
    if uploaded and st.button("Process call", key="process_btn"):
        import tempfile, os, re
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
            except:
                ins = {}
            session.sql(f"DELETE FROM {DB}.CALL_INSIGHTS WHERE CALL_ID='{call_id}'").collect()
            session.sql(f"""INSERT INTO {DB}.CALL_INSIGHTS (CALL_ID,OBJECTIONS,COMPETITOR_MENTIONS,BUYING_SIGNALS,PRICING_DISCUSSIONS,ACTION_ITEMS,NEXT_STEPS,LEAD_INTENT_SCORE)
                VALUES('{call_id}','{_sq(str(ins.get("objections","")))}','{_sq(str(ins.get("competitor_mentions","")))}',
                '{_sq(str(ins.get("buying_signals","")))}','{_sq(str(ins.get("pricing_discussions","")))}',
                '{_sq(str(ins.get("action_items","")))}','{_sq(str(ins.get("next_steps","")))}',
                {int(ins.get('lead_intent_score',50))})""").collect()

            status.update(label="Base processing complete!", state="complete")

        enhance_call(call_id)
        st.success(f"Call `{call_id}` processed with {len(segments)} segments!")

# ── Tab 2 · Full Transcript ──────────────────────────────────────────────────
with tab2:
    st.markdown("## Full transcript")
    tx_calls = session.sql(f"SELECT DISTINCT CALL_ID FROM {DB}.CALL_SEGMENTS ORDER BY CALL_ID").to_pandas()
    if len(tx_calls) == 0:
        st.info("No calls processed yet.")
    else:
        _ids = tx_calls['CALL_ID'].tolist()
        sel_tx = st.selectbox("Select call", _ids, index=_default_index(_ids), key="tx_call")
        tx_seg = session.sql(f"SELECT * FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{sel_tx}' ORDER BY START_TIME").to_pandas()
        for _, seg in tx_seg.iterrows():
            role = seg.get('SPEAKER_ROLE') or seg.get('SPEAKER', 'Unknown')
            ri = "🔵" if role == 'Agent' else "🟢" if role == 'Customer' else "⚪"
            mm, ss = int(seg['START_TIME'] // 60), int(seg['START_TIME'] % 60)
            km_badge = " **⚡**" if seg.get('IS_KEY_MOMENT') else ""
            st.markdown(f"{ri} **{role}** `{mm:02d}:{ss:02d}`{km_badge}")
            st.markdown(f"> {seg['SEGMENT_TEXT']}")
            if seg.get('IS_KEY_MOMENT'):
                st.caption(f"{seg.get('MOMENT_TYPE','')} | {seg.get('MOMENT_SEVERITY','')}")

# ── Tab 3 · Call Dashboard ───────────────────────────────────────────────────
with tab3:
    st.markdown("## Call dashboard")
    db_calls = session.sql(f"SELECT DISTINCT CALL_ID FROM {DB}.CALL_SEGMENTS ORDER BY CALL_ID").to_pandas()
    if len(db_calls) == 0:
        st.info("No calls processed yet.")
    else:
        _ids = db_calls['CALL_ID'].tolist()
        sel_db = st.selectbox("Select call", _ids, index=_default_index(_ids), key="db_call")
        db_seg = session.sql(f"SELECT * FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{sel_db}' ORDER BY START_TIME").to_pandas()
        db_ins = session.sql(f"SELECT * FROM {DB}.CALL_INSIGHTS WHERE CALL_ID='{sel_db}'").to_pandas()
        if len(db_seg) > 0:
            dur = db_seg['END_TIME'].max()
            avg_s = db_seg['SENTIMENT'].mean()
            c1,c2,c3,c4 = st.columns(4)
            with c1:
                with st.container(border=True):
                    st.metric("Duration", f"{int(dur//60)}m {int(dur%60)}s")
            with c2:
                with st.container(border=True):
                    st.metric("Segments", len(db_seg))
            with c3:
                with st.container(border=True):
                    st.metric("Avg Sentiment", f"{avg_s:.2f}")
            with c4:
                with st.container(border=True):
                    lead = int(db_ins['LEAD_INTENT_SCORE'].iloc[0]) if len(db_ins) > 0 else 0
                    st.metric("Lead Score", f"{lead}/100")

            if len(db_ins) > 0 and 'RESOLUTION_STATUS' in db_ins.columns and db_ins.iloc[0].get('RESOLUTION_STATUS'):
                row = db_ins.iloc[0]
                st.markdown("### Structured KPIs")
                k1,k2,k3,k4 = st.columns(4)
                with k1:
                    res = row.get('RESOLUTION_STATUS','N/A')
                    ri = {"Resolved":"✅","Unresolved":"❌","Partial":"🟡","Escalated":"🔺"}.get(res,"❓")
                    with st.container(border=True):
                        st.metric(f"{ri} Resolution", res)
                with k2:
                    with st.container(border=True):
                        st.metric("Escalation", "Yes" if row.get('ESCALATION_FLAG') else "No")
                with k3:
                    csat = row.get('CSAT_INDICATOR','N/A')
                    ci = {"Positive":"😊","Neutral":"😐","Negative":"😞"}.get(csat,"❓")
                    with st.container(border=True):
                        st.metric(f"{ci} CSAT", csat)
                with k4:
                    with st.container(border=True):
                        st.metric("Issue Type", row.get('ISSUE_TYPE','N/A'))
                if row.get('CALL_OUTCOME'):
                    st.info(f"**Outcome:** {row['CALL_OUTCOME']}")
                if row.get('ROOT_CAUSE') and str(row['ROOT_CAUSE']).lower() not in ['none','null','']:
                    st.warning(f"**Root Cause:** {row['ROOT_CAUSE']}")

            st.markdown("### Sentiment over time")
            chart_df = db_seg[['START_TIME','SENTIMENT']].copy()
            chart_df = chart_df.set_index('START_TIME')
            st.line_chart(chart_df)

# ── Tab 4 · AI Summary ───────────────────────────────────────────────────────
with tab4:
    st.markdown("## AI summary")
    sm_calls = session.sql(f"SELECT DISTINCT CALL_ID FROM {DB}.CALL_SEGMENTS ORDER BY CALL_ID").to_pandas()
    if len(sm_calls) == 0:
        st.info("No calls processed yet.")
    else:
        _ids = sm_calls['CALL_ID'].tolist()
        sel_sm = st.selectbox("Select call", _ids, index=_default_index(_ids), key="sm_call")
        if st.button("Generate summary", key="gen_summary"):
            sm_seg = session.sql(f"SELECT COALESCE(SPEAKER_ROLE,SPEAKER) AS SPK, SEGMENT_TEXT FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{sel_sm}' ORDER BY START_TIME").to_pandas()
            tx_lines = [f"{r['SPK']}: {r['SEGMENT_TEXT']}" for _, r in sm_seg.iterrows()]
            prompt = f"Provide a concise executive summary of this call in 3-5 bullet points. Include: purpose, key discussion points, outcome, and any follow-up needed.\n\nTranscript:\n{chr(10).join(tx_lines[:50])}"
            summary = _cortex(prompt)
            st.session_state[f'ai_summary_{sel_sm}'] = summary
        if st.session_state.get(f'ai_summary_{sel_sm}'):
            st.markdown(st.session_state[f'ai_summary_{sel_sm}'])

# ── Tab 5 · Key Moments ──────────────────────────────────────────────────────
with tab5:
    st.markdown("## Key moments")
    st.caption("Critical events — frustration, escalation, buying signals, and more.")
    km_calls = session.sql(f"SELECT DISTINCT CALL_ID FROM {DB}.CALL_KEY_MOMENTS ORDER BY CALL_ID").to_pandas()
    if len(km_calls) == 0:
        st.info("No key moments detected yet. Process a call to generate analysis.")
    else:
        _ids = km_calls['CALL_ID'].tolist()
        sel_km = st.selectbox("Select call", _ids, index=_default_index(_ids), key="km_call")
        km_data = session.sql(f"SELECT * FROM {DB}.CALL_KEY_MOMENTS WHERE CALL_ID='{sel_km}' ORDER BY START_TIME").to_pandas()

        # ── fetch the original file from stage for audio playback ──────────
        # We retrieve the audio bytes once and store in session_state so we
        # don't re-download on every rerun.
        audio_key = f"audio_bytes_{sel_km}"
        if audio_key not in st.session_state:
            try:
                # Reconstruct original filename from call_id (underscores → .)
                # Works for common patterns like MY_CALL_MP3 → my_call.mp3
                # We list the stage and find the matching file.
                stage_files = session.sql(f"LIST @{DB}.AUDIO_STAGE").to_pandas()
                # stage 'name' column contains paths like: echomind_db/app/audio_stage/filename
                matched = None
                call_id_clean = sel_km.upper()
                for _, sf in stage_files.iterrows():
                    fname = sf['name'].split('/')[-1]
                    fname_norm = fname.upper().replace('.','_').replace('-','_').replace(' ','_')
                    # strip extension from call_id if it was added
                    if call_id_clean.startswith(fname_norm.rsplit('_',1)[0]) or fname_norm.startswith(call_id_clean.split('_')[0]):
                        matched = fname
                        break
                if matched:
                    local_tmp = f"/tmp/{matched}"
                    session.file.get(f"@{DB}.AUDIO_STAGE/{matched}", "/tmp/")
                    with open(local_tmp, "rb") as af:
                        st.session_state[audio_key] = af.read()
                else:
                    st.session_state[audio_key] = None
            except Exception:
                st.session_state[audio_key] = None

        audio_bytes = st.session_state.get(audio_key)

        if len(km_data) == 0:
            st.info("No key moments for this call.")
        else:
            mi = {'Frustration':'😤','Escalation_Request':'🔺','Complaint':'😠','Buying_Signal':'💰','Resolution':'✅','Positive_Feedback':'😊','Objection':'🚧'}
            sc = {'high':'🔴','medium':'🟡','low':'🟢'}
            mc1,mc2,mc3,mc4 = st.columns(4)
            with mc1:
                with st.container(border=True): st.metric("Total", len(km_data))
            with mc2:
                with st.container(border=True): st.metric("🔴 High", len(km_data[km_data['SEVERITY']=='high']))
            with mc3:
                with st.container(border=True): st.metric("🟡 Medium", len(km_data[km_data['SEVERITY']=='medium']))
            with mc4:
                with st.container(border=True): st.metric("🟢 Low", len(km_data[km_data['SEVERITY']=='low']))

            st.markdown("### Moment timeline")
            for _, m in km_data.iterrows():
                icon = mi.get(m['MOMENT_TYPE'],'📌')
                sev = sc.get(m.get('SEVERITY',''),'⚪')
                mm_t, ss_t = int(m['START_TIME']//60), int(m['START_TIME']%60)
                dur = m['END_TIME'] - m['START_TIME']
                with st.expander(f"{sev} {icon} {m['MOMENT_TYPE']} @ {mm_t:02d}:{ss_t:02d} ({dur:.1f}s)"):
                    st.write(m['SEGMENT_TEXT'])
                    # ── Audio clip playback ─────────────────────────────────
                    if audio_bytes:
                        try:
                            import io
                            # Use pydub to slice the audio to the segment window
                            # Add a 1-second buffer before/after for context
                            from pydub import AudioSegment
                            full_audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
                            start_ms = max(0, int((m['START_TIME'] - 1.0) * 1000))
                            end_ms = min(len(full_audio), int((m['END_TIME'] + 1.0) * 1000))
                            clip = full_audio[start_ms:end_ms]
                            clip_buf = io.BytesIO()
                            clip.export(clip_buf, format="mp3")
                            clip_buf.seek(0)
                            st.caption(f"🎵 Audio clip ({mm_t:02d}:{ss_t:02d} — {int(m['END_TIME']//60):02d}:{int(m['END_TIME']%60):02d})")
                            st.audio(clip_buf.read(), format="audio/mp3")
                        except Exception as e:
                            st.caption(f"⚠️ Audio clip unavailable: {e}")
                    else:
                        st.caption("🔇 Audio file not available for playback.")

            st.markdown("### Distribution")
            st.bar_chart(km_data['MOMENT_TYPE'].value_counts())

# ── Tab 6 · Topic Clusters ───────────────────────────────────────────────────
with tab6:
    st.markdown("## Topic clusters")
    st.caption("Standardized topic classification with conversation flow.")
    tc_calls = session.sql(f"SELECT DISTINCT CALL_ID FROM {DB}.CALL_SEGMENTS WHERE STANDARD_TOPIC IS NOT NULL OR TOPIC_LABEL IS NOT NULL ORDER BY CALL_ID").to_pandas()
    if len(tc_calls) == 0:
        st.info("No topic data available.")
    else:
        _ids = tc_calls['CALL_ID'].tolist()
        sel_tc = st.selectbox("Select call", _ids, index=_default_index(_ids), key="tc_call")
        tc_seg = session.sql(f"SELECT * FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{sel_tc}' ORDER BY START_TIME").to_pandas()
        has_std = 'STANDARD_TOPIC' in tc_seg.columns and tc_seg['STANDARD_TOPIC'].notna().any()
        tcol = 'STANDARD_TOPIC' if has_std else 'TOPIC_LABEL'
        tcolors = {'Greeting':'🟦','Identity_Verification':'🟦','Intent_Discovery':'🟩','Troubleshooting':'🟧','Frustration':'🟥','Escalation':'🟥','Resolution':'✅','Pricing':'💰','Objection':'🟥','Closing':'🟦','Follow_Up':'🟩','Product_Info':'🟧','Small_Talk':'⬜'}

        st.markdown("### Conversation flow")
        for _, seg in tc_seg.iterrows():
            topic = seg.get(tcol) or 'Unknown'
            role = seg.get('SPEAKER_ROLE') or 'Unknown'
            is_km = seg.get('IS_KEY_MOMENT', False)
            mm, ss = int(seg['START_TIME']//60), int(seg['START_TIME']%60)
            ti = tcolors.get(topic,'⬜')
            ri = "🔵" if role=='Agent' else "🟢" if role=='Customer' else "⚪"
            km = " ⚡" if is_km else ""
            st.markdown(f"`{mm:02d}:{ss:02d}` {ti} **{topic}** {ri} {role}{km} — _{seg['SEGMENT_TEXT'][:80]}_")

        st.markdown("### Topic distribution")
        st.bar_chart(tc_seg[tcol].value_counts())

        crit = tc_seg[tc_seg[tcol].isin(['Frustration','Escalation'])]
        if len(crit) > 0:
            st.markdown("### Critical segments")
            for _, cs in crit.iterrows():
                mm, ss = int(cs['START_TIME']//60), int(cs['START_TIME']%60)
                st.error(f"**{cs[tcol]}** @ {mm:02d}:{ss:02d} — {cs['SEGMENT_TEXT'][:120]}")

        if has_std:
            st.markdown("### Topic sentiment")
            ts = tc_seg.groupby('STANDARD_TOPIC')['SENTIMENT'].agg(['mean','count']).reset_index()
            ts.columns = ['Topic','Avg Sentiment','Segments']
            st.dataframe(ts.sort_values('Avg Sentiment'), use_container_width=True, hide_index=True)

# ── Tab 7 · Coaching Tips ────────────────────────────────────────────────────
with tab7:
    st.markdown("## Coaching tips")
    ct_calls = session.sql(f"SELECT DISTINCT CALL_ID FROM {DB}.CALL_SEGMENTS ORDER BY CALL_ID").to_pandas()
    if len(ct_calls) == 0:
        st.info("No calls processed yet.")
    else:
        _ids = ct_calls['CALL_ID'].tolist()
        sel_ct = st.selectbox("Select call", _ids, index=_default_index(_ids), key="ct_call")
        if st.button("Generate coaching tips", key="gen_coaching"):
            ct_seg = session.sql(f"SELECT COALESCE(SPEAKER_ROLE,SPEAKER) AS SPK, SEGMENT_TEXT, SENTIMENT FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{sel_ct}' ORDER BY START_TIME").to_pandas()
            lines = [f"{r['SPK']} (sent:{r['SENTIMENT']:.2f}): {r['SEGMENT_TEXT']}" for _, r in ct_seg.iterrows()]
            tips = _cortex(f"You are a call center coach. Analyze this call and provide 5 specific, actionable coaching tips for the agent. Focus on communication, empathy, problem resolution, and customer satisfaction.\n\nCall:\n{chr(10).join(lines[:40])}")
            st.session_state[f'coaching_{sel_ct}'] = tips
        if st.session_state.get(f'coaching_{sel_ct}'):
            st.markdown(st.session_state[f'coaching_{sel_ct}'])

# ── Tab 8 · Sentiment ────────────────────────────────────────────────────────
with tab8:
    st.markdown("## Sentiment deep dive")
    se_calls = session.sql(f"SELECT DISTINCT CALL_ID FROM {DB}.CALL_SEGMENTS ORDER BY CALL_ID").to_pandas()
    if len(se_calls) == 0:
        st.info("No calls processed yet.")
    else:
        _ids = se_calls['CALL_ID'].tolist()
        sel_se = st.selectbox("Select call", _ids, index=_default_index(_ids), key="se_call")
        se_seg = session.sql(f"SELECT * FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{sel_se}' ORDER BY START_TIME").to_pandas()
        if len(se_seg) > 0:
            st.markdown("### Sentiment timeline")
            st.line_chart(se_seg.set_index('START_TIME')['SENTIMENT'])
            st.markdown("### Distribution")
            se_seg['Sentiment_Bucket'] = pd.cut(se_seg['SENTIMENT'], bins=[-1,-0.3,0.3,1], labels=['Negative','Neutral','Positive'])
            st.bar_chart(se_seg['Sentiment_Bucket'].value_counts())
            neg = se_seg[se_seg['SENTIMENT'] < -0.2].sort_values('SENTIMENT')
            if len(neg) > 0:
                st.markdown("### Most negative segments")
                for _, n in neg.head(5).iterrows():
                    mm, ss = int(n['START_TIME']//60), int(n['START_TIME']%60)
                    role = n.get('SPEAKER_ROLE') or n.get('SPEAKER','')
                    st.warning(f"**{role}** @ {mm:02d}:{ss:02d} (sent: {n['SENTIMENT']:.2f}) — {n['SEGMENT_TEXT'][:100]}")

# ── Tab 9 · Compare Calls ────────────────────────────────────────────────────
with tab9:
    st.markdown("## Compare calls")
    cp_calls = session.sql(f"SELECT DISTINCT CALL_ID FROM {DB}.CALL_SEGMENTS ORDER BY CALL_ID").to_pandas()
    if len(cp_calls) < 2:
        st.info("Need at least 2 calls to compare.")
    else:
        _ids = cp_calls['CALL_ID'].tolist()
        cl1, cl2 = st.columns(2)
        with cl1:
            cp1 = st.selectbox("Call A", _ids, index=_default_index(_ids), key="cp1")
        with cl2:
            default_b = 1 if len(_ids) > 1 else 0
            cp2 = st.selectbox("Call B", _ids, index=default_b, key="cp2")
        if cp1 != cp2:
            for cid, col in [(cp1,cl1),(cp2,cl2)]:
                with col:
                    s = session.sql(f"SELECT * FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{cid}'").to_pandas()
                    ins = session.sql(f"SELECT * FROM {DB}.CALL_INSIGHTS WHERE CALL_ID='{cid}'").to_pandas()
                    st.caption(f"**{cid}**")
                    st.metric("Duration", f"{int(s['END_TIME'].max()//60)}m")
                    st.metric("Segments", len(s))
                    st.metric("Avg Sentiment", f"{s['SENTIMENT'].mean():.2f}")
                    if len(ins)>0:
                        st.metric("Lead Score", int(ins['LEAD_INTENT_SCORE'].iloc[0]))
                        if ins.iloc[0].get('RESOLUTION_STATUS'):
                            st.metric("Resolution", ins.iloc[0]['RESOLUTION_STATUS'])

# ── Tab 10 · Leaderboard ─────────────────────────────────────────────────────
with tab10:
    st.markdown("## Leaderboard")
    lb = session.sql(f"""SELECT c.CALL_ID, COUNT(*) AS SEGMENTS,
        ROUND(MAX(c.END_TIME),0) AS DURATION_S, ROUND(AVG(c.SENTIMENT),3) AS AVG_SENTIMENT,
        COALESCE(i.LEAD_INTENT_SCORE,0) AS LEAD_SCORE, i.RESOLUTION_STATUS
        FROM {DB}.CALL_SEGMENTS c LEFT JOIN {DB}.CALL_INSIGHTS i ON c.CALL_ID=i.CALL_ID
        GROUP BY c.CALL_ID, i.LEAD_INTENT_SCORE, i.RESOLUTION_STATUS ORDER BY LEAD_SCORE DESC""").to_pandas()
    if len(lb) == 0:
        st.info("No calls processed yet.")
    else:
        st.dataframe(lb, use_container_width=True, hide_index=True)

# ── Tab 11 · Call Journey ────────────────────────────────────────────────────
with tab11:
    st.markdown("## Call journey")
    st.caption("End-to-end visual flow of the conversation.")
    tj_calls = session.sql(f"SELECT DISTINCT CALL_ID FROM {DB}.CALL_SEGMENTS ORDER BY CALL_ID").to_pandas()
    if len(tj_calls) == 0:
        st.info("No calls processed yet.")
    else:
        _ids = tj_calls['CALL_ID'].tolist()
        sel_tj = st.selectbox("Select call", _ids, index=_default_index(_ids), key="tj_call")
        tj_seg = session.sql(f"SELECT * FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{sel_tj}' ORDER BY START_TIME").to_pandas()
        has_roles = 'SPEAKER_ROLE' in tj_seg.columns and tj_seg['SPEAKER_ROLE'].notna().any()
        has_topics = 'STANDARD_TOPIC' in tj_seg.columns and tj_seg['STANDARD_TOPIC'].notna().any()
        rc = 'SPEAKER_ROLE' if has_roles else 'SPEAKER'
        tc = 'STANDARD_TOPIC' if has_topics else 'TOPIC_LABEL'
        pi = {'Greeting':'👋','Identity_Verification':'🪪','Intent_Discovery':'🔍','Troubleshooting':'🔧','Product_Info':'📦','Pricing':'💲','Objection':'🚧','Frustration':'😤','Escalation':'🔺','Resolution':'✅','Follow_Up':'📋','Closing':'👋','Small_Talk':'💬'}

        if has_topics:
            seen = []
            for _, seg in tj_seg.iterrows():
                t = seg.get(tc)
                if t and (not seen or seen[-1] != t):
                    seen.append(t)
            st.markdown("### Call phases")
            st.markdown(" → ".join([f"{pi.get(t,'📌')} {t}" for t in seen]))

        st.markdown("### Detailed timeline")
        for _, seg in tj_seg.iterrows():
            topic = seg.get(tc) or 'Unknown'
            role = seg.get(rc) or 'Unknown'
            is_km = seg.get('IS_KEY_MOMENT', False)
            mm, ss = int(seg['START_TIME']//60), int(seg['START_TIME']%60)
            dur = seg['END_TIME'] - seg['START_TIME']
            rm = "🔵" if role=='Agent' else "🟢" if role=='Customer' else "⚪"
            ti = pi.get(topic,'📌')
            km = " **⚡**" if is_km else ""
            sent = seg.get('SENTIMENT',0)
            sb = "🟢" if sent>0.1 else "🔴" if sent<-0.2 else "🟡"
            col_t, col_c = st.columns([1,5])
            with col_t:
                st.caption(f"{mm:02d}:{ss:02d}")
                st.caption(f"{dur:.1f}s")
            with col_c:
                with st.container(border=is_km):
                    st.markdown(f"{rm} {ti} **{topic}** — {role}{km}")
                    st.caption(f"{seg['SEGMENT_TEXT'][:120]} | {sb} {sent:.2f}")

        if has_topics:
            st.markdown("### Phase duration")
            tj_seg['dur'] = tj_seg['END_TIME'] - tj_seg['START_TIME']
            st.bar_chart(tj_seg.groupby(tc)['dur'].sum().sort_values(ascending=False))

# ── Tab 12 · Speaker Dynamics ────────────────────────────────────────────────
with tab12:
    st.markdown("## Speaker dynamics")
    st.caption("Agent vs Customer analysis with coaching metrics.")
    sd_call_ids = session.sql(f"SELECT DISTINCT CALL_ID FROM {DB}.CALL_SEGMENTS ORDER BY CALL_ID").to_pandas()
    if len(sd_call_ids) == 0:
        st.info("No calls processed yet.")
    else:
        _ids = sd_call_ids['CALL_ID'].tolist()
        selected_sd = st.selectbox("Select call", _ids, index=_default_index(_ids), key="sd_call")
        sd_seg = session.sql(f"SELECT * FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{selected_sd}' ORDER BY START_TIME").to_pandas()
        has_roles = 'SPEAKER_ROLE' in sd_seg.columns and sd_seg['SPEAKER_ROLE'].notna().any()
        role_col = 'SPEAKER_ROLE' if has_roles else 'SPEAKER'
        if not has_roles:
            st.warning("Speaker diarization not yet run. Re-process this call to enable Agent/Customer analytics.")
        sd_seg['dur'] = sd_seg['END_TIME'] - sd_seg['START_TIME']
        speakers = sd_seg[role_col].dropna().unique().tolist()
        if len(speakers) > 0:
            st.markdown("### Talk time breakdown")
            talk_time = sd_seg.groupby(role_col)['dur'].sum()
            total_time = talk_time.sum()
            cols = st.columns(len(speakers))
            for i, spk in enumerate(speakers):
                with cols[i]:
                    pct = (talk_time.get(spk,0)/total_time*100) if total_time>0 else 0
                    icon = "🔵" if spk=='Agent' else "🟢" if spk=='Customer' else "⚪"
                    with st.container(border=True):
                        st.metric(f"{icon} {spk}", f"{pct:.1f}%")
                        st.caption(f"{talk_time.get(spk,0):.0f}s")
            if has_roles and 'Agent' in speakers:
                agent_pct = talk_time.get('Agent',0)/total_time*100 if total_time>0 else 50
                ls = max(0, min(100, int(100-abs(agent_pct-40)*2)))
                st.markdown("### Listening score")
                st.progress(ls)
                st.caption(f"Score: {ls}/100 (Agent talk: {agent_pct:.0f}%)")

            st.markdown("### Monologue analysis")
            for spk in speakers:
                spk_segs = sd_seg[sd_seg[role_col]==spk].copy()
                if len(spk_segs)>0:
                    longest = spk_segs.loc[spk_segs['dur'].idxmax()]
                    mm = int(longest['START_TIME']//60)
                    ss = int(longest['START_TIME']%60)
                    icon = "🔵" if spk=='Agent' else "🟢" if spk=='Customer' else "⚪"
                    with st.expander(f"{icon} {spk} — longest: {longest['dur']:.1f}s at {mm:02d}:{ss:02d}"):
                        st.write(longest['SEGMENT_TEXT'])

            st.markdown("### Turn-taking patterns")
            transitions = []
            for i in range(1, len(sd_seg)):
                if sd_seg.iloc[i][role_col] != sd_seg.iloc[i-1][role_col]:
                    gap = sd_seg.iloc[i]['START_TIME'] - sd_seg.iloc[i-1]['END_TIME']
                    transitions.append({'from':sd_seg.iloc[i-1][role_col],'to':sd_seg.iloc[i][role_col],'gap':gap})
            ct1,ct2,ct3 = st.columns(3)
            with ct1:
                with st.container(border=True): st.metric("Total turns", len(transitions))
            with ct2:
                avg_gap = sum(t['gap'] for t in transitions)/len(transitions) if transitions else 0
                with st.container(border=True): st.metric("Avg gap", f"{avg_gap:.1f}s")
            with ct3:
                interruptions = [t for t in transitions if t['gap']<0]
                with st.container(border=True): st.metric("Interruptions", len(interruptions))
            if transitions:
                quick = [t for t in transitions if 0<=t['gap']<1.0]
                if quick: st.caption(f"⚡ {len(quick)} quick responses (<1s)")
                if interruptions: st.caption(f"🚫 {len(interruptions)} overlaps")

            if has_roles:
                st.markdown("### Repetition detection")
                agent_segs = sd_seg[sd_seg[role_col]=='Agent']['SEGMENT_TEXT'].tolist()
                if len(agent_segs)>2:
                    words = ' '.join(agent_segs).lower().split()
                    trigrams = [' '.join(words[j:j+3]) for j in range(len(words)-2)]
                    repeated = [(p,c) for p,c in Counter(trigrams).most_common(5) if c>2]
                    if repeated:
                        for p,c in repeated: st.caption(f"🔁 \"{p}\" repeated {c}x")
                    else: st.success("No excessive repetition detected")
            st.markdown("### Segments per speaker")
            st.bar_chart(sd_seg[role_col].value_counts())
            st.markdown("### Avg segment length")
            st.bar_chart(sd_seg.groupby(role_col)['dur'].mean())

# ── Tab 13 · Tags & Notes ────────────────────────────────────────────────────
with tab13:
    st.markdown("## Tags & notes")
    st.caption("Add custom tags and notes to organize your calls.")
    tag_calls = session.sql(f"SELECT DISTINCT CALL_ID FROM {DB}.CALL_SEGMENTS ORDER BY CALL_ID").to_pandas()
    if len(tag_calls) == 0:
        st.info("No calls processed yet.")
    else:
        _ids = tag_calls['CALL_ID'].tolist()
        selected_tag_call = st.selectbox("Select call", _ids, index=_default_index(_ids), key="tag_call")
        st.markdown("### Tags")
        preset_tags = ["🔥 Hot Lead","❄️ Cold Lead","🔄 Follow-Up Needed","⚠️ Needs Escalation",
                       "👤 Decision Maker Present","💰 Budget Discussed","🏁 Competitor Mentioned",
                       "✅ Deal Closed","📅 Meeting Scheduled","🚧 Objection Heavy"]
        current_tags = st.session_state['call_tags'].get(selected_tag_call, [])
        selected_tags = st.multiselect("Select tags", preset_tags, default=current_tags, key=f"tags_{selected_tag_call}")
        st.session_state['call_tags'][selected_tag_call] = selected_tags
        custom_tag = st.text_input("Add custom tag", key="custom_tag", placeholder="Type and press Enter...")
        if custom_tag and st.button("Add tag", key="add_custom_tag"):
            if custom_tag not in st.session_state['call_tags'].get(selected_tag_call, []):
                st.session_state['call_tags'].setdefault(selected_tag_call, []).append(custom_tag)
                st.rerun()
        if selected_tags:
            st.markdown("**Applied:** " + "  ".join([f"`{t}`" for t in selected_tags]))
        st.markdown("### Notes")
        current_notes = st.session_state['call_notes'].get(selected_tag_call, "")
        notes = st.text_area("Notes", value=current_notes, height=150, key=f"notes_{selected_tag_call}")
        st.session_state['call_notes'][selected_tag_call] = notes
        st.divider()
        st.markdown("### All tagged calls")
        tagged = {k:v for k,v in st.session_state['call_tags'].items() if v}
        if tagged:
            for cid, tags in tagged.items():
                note_preview = st.session_state['call_notes'].get(cid,"")[:100]
                with st.expander(f"📞 {cid} — {', '.join(tags)}"):
                    st.markdown(f"**Tags:** {', '.join(tags)}")
                    if note_preview: st.markdown(f"**Notes:** {note_preview}...")
        else:
            st.caption("No calls tagged yet.")

# ── Tab 14 · Topic Trends ────────────────────────────────────────────────────
with tab14:
    st.markdown("## Topic trends")
    trend_seg = session.sql(f"""SELECT CALL_ID, COALESCE(STANDARD_TOPIC,TOPIC_LABEL) AS TOPIC, COUNT(*) AS SEG_COUNT, ROUND(AVG(SENTIMENT),3) AS AVG_SENTIMENT
        FROM {DB}.CALL_SEGMENTS WHERE COALESCE(STANDARD_TOPIC,TOPIC_LABEL) IS NOT NULL
        GROUP BY CALL_ID, COALESCE(STANDARD_TOPIC,TOPIC_LABEL) ORDER BY CALL_ID""").to_pandas()
    if len(trend_seg) == 0:
        st.info("No topic data available.")
    else:
        st.markdown("### Topic frequency across calls")
        tp = trend_seg.pivot_table(index='CALL_ID', columns='TOPIC', values='SEG_COUNT', fill_value=0)
        st.bar_chart(tp)
        st.markdown("### Topic sentiment across calls")
        sp = trend_seg.pivot_table(index='CALL_ID', columns='TOPIC', values='AVG_SENTIMENT', fill_value=0)
        st.line_chart(sp)
        st.markdown("### Most discussed topics")
        st.bar_chart(trend_seg.groupby('TOPIC')['SEG_COUNT'].sum().sort_values(ascending=False).head(10))

# ── Tab 15 · Call Scorecard ──────────────────────────────────────────────────
with tab15:
    st.markdown("## Call scorecard")
    if not st.session_state.get('last_call_id'):
        st.info("No call processed in this session yet. Head to **Upload & Process**.")
    else:
        selected_call = st.session_state['last_call_id']
        st.caption(f"Scorecard for: `{selected_call}`")
        sc_seg = session.sql(f"SELECT * FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{selected_call}' ORDER BY START_TIME").to_pandas()
        sc_ins = session.sql(f"SELECT * FROM {DB}.CALL_INSIGHTS WHERE CALL_ID='{selected_call}'").to_pandas()
        if len(sc_seg) == 0:
            st.info("No data available.")
        else:
            sc_dur = sc_seg['END_TIME'].max()
            sc_lead = int(sc_ins['LEAD_INTENT_SCORE'].iloc[0]) if len(sc_ins)>0 else 0
            sc_avg_sent = sc_seg['SENTIMENT'].mean()
            sc_seg['dur'] = sc_seg['END_TIME'] - sc_seg['START_TIME']
            role_col = 'SPEAKER_ROLE' if 'SPEAKER_ROLE' in sc_seg.columns and sc_seg['SPEAKER_ROLE'].notna().any() else 'SPEAKER'
            talk_by_spk = sc_seg.groupby(role_col)['dur'].sum()
            total_talk = talk_by_spk.sum()
            balance = talk_by_spk.min()/talk_by_spk.max()*100 if talk_by_spk.max()>0 else 0

            sc_kpis = session.sql(f"SELECT RESOLUTION_STATUS,ESCALATION_FLAG,CSAT_INDICATOR,CALL_OUTCOME,ISSUE_TYPE,ROOT_CAUSE FROM {DB}.CALL_INSIGHTS WHERE CALL_ID='{selected_call}'").to_pandas()
            has_kpis = len(sc_kpis)>0 and sc_kpis.iloc[0].get('RESOLUTION_STATUS')
            if has_kpis:
                kr = sc_kpis.iloc[0]
                resolved = kr.get('RESOLUTION_STATUS')=='Resolved'
                escalated = bool(kr.get('ESCALATION_FLAG'))
                positive = kr.get('CSAT_INDICATOR')=='Positive'
                if resolved and not escalated and positive: grade = "🌟 Excellent"
                elif resolved: grade = "✅ Good"
                elif escalated: grade = "⚠️ Escalated"
                elif kr.get('RESOLUTION_STATUS')=='Unresolved': grade = "🔴 Needs Improvement"
                else: grade = "⚠️ Average"
            else:
                if sc_lead>=70 and sc_avg_sent>0.1 and balance>30: grade = "🌟 Excellent"
                elif sc_lead>=50 and sc_avg_sent>0: grade = "✅ Good"
                elif sc_lead>=30: grade = "⚠️ Average"
                else: grade = "🔴 Needs Improvement"

            st.markdown(f"### Overall grade: {grade}")
            col1,col2,col3 = st.columns(3)
            with col1:
                with st.container(border=True):
                    st.metric("Duration", f"{int(sc_dur//60)}m {int(sc_dur%60)}s")
                    st.metric("Speakers", sc_seg[role_col].nunique())
            with col2:
                with st.container(border=True):
                    st.metric("Lead score", f"{sc_lead}/100")
                    st.metric("Avg sentiment", f"{sc_avg_sent:.2f}")
            with col3:
                with st.container(border=True):
                    st.metric("Talk balance", f"{balance:.0f}%")
                    st.metric("Negative segments", f"{(sc_seg['SENTIMENT']<-0.2).sum()/len(sc_seg)*100:.1f}%")

            if has_kpis:
                st.markdown("### Structured KPIs")
                k1,k2,k3,k4 = st.columns(4)
                with k1:
                    with st.container(border=True): st.metric("Resolution", kr.get('RESOLUTION_STATUS','N/A'))
                with k2:
                    with st.container(border=True): st.metric("Escalation", "Yes" if kr.get('ESCALATION_FLAG') else "No")
                with k3:
                    with st.container(border=True): st.metric("CSAT", kr.get('CSAT_INDICATOR','N/A'))
                with k4:
                    with st.container(border=True): st.metric("Issue Type", kr.get('ISSUE_TYPE','N/A'))
                if kr.get('CALL_OUTCOME'): st.info(f"**Outcome:** {kr['CALL_OUTCOME']}")
                if kr.get('ROOT_CAUSE') and str(kr['ROOT_CAUSE']).lower() not in ['none','null','']: st.warning(f"**Root Cause:** {kr['ROOT_CAUSE']}")

            if len(sc_ins)>0:
                st.markdown("### Key insights")
                ins_row = sc_ins.iloc[0]
                icons = {'BUYING_SIGNALS':'💰','OBJECTIONS':'🚧','COMPETITOR_MENTIONS':'🏁','PRICING_DISCUSSIONS':'💲','ACTION_ITEMS':'✅','NEXT_STEPS':'➡️'}
                for c in ['BUYING_SIGNALS','OBJECTIONS','COMPETITOR_MENTIONS','PRICING_DISCUSSIONS','ACTION_ITEMS','NEXT_STEPS']:
                    val = str(ins_row.get(c,''))
                    if val and val.strip() and val.lower() not in ['none','null','','[]']:
                        with st.expander(f"{icons.get(c,'📌')} {c.replace('_',' ').title()}"):
                            st.write(val)

            scorecard_text = f"{'='*60}\n        ECHOMIND CALL SCORECARD\n{'='*60}\nCALL ID: {selected_call}\nGRADE: {grade}\nDuration: {int(sc_dur//60)}m {int(sc_dur%60)}s | Segments: {len(sc_seg)} | Lead: {sc_lead}/100 | Sentiment: {sc_avg_sent:.2f}\n"
            if has_kpis:
                scorecard_text += f"Resolution: {kr.get('RESOLUTION_STATUS','N/A')} | Escalation: {'Yes' if kr.get('ESCALATION_FLAG') else 'No'} | CSAT: {kr.get('CSAT_INDICATOR','N/A')}\n"
            st.download_button("Download scorecard (.txt)", data=scorecard_text, file_name=f"echomind_scorecard_{selected_call}.txt", mime="text/plain", key="dl_scorecard")

# ── Tab 16 · Re-Analyze ──────────────────────────────────────────────────────
with tab16:
    st.markdown("## Re-analyze existing calls")
    st.caption("Run enhanced analysis (speaker roles, standard topics, key moments, KPIs) on previously processed calls.")
    ra_calls = session.sql(f"SELECT DISTINCT CALL_ID FROM {DB}.CALL_SEGMENTS ORDER BY CALL_ID").to_pandas()
    if len(ra_calls) == 0:
        st.info("No calls to re-analyze.")
    else:
        sel_ra = st.selectbox("Select call to re-analyze", ra_calls['CALL_ID'].tolist(), key="ra_call")
        if st.button("Re-analyze selected call", key="ra_btn"):
            enhance_call(sel_ra)
            st.success(f"Call `{sel_ra}` enhanced!")
        st.divider()
        if st.button("Re-analyze ALL calls", key="ra_all_btn"):
            progress = st.progress(0)
            for i, (_, row) in enumerate(ra_calls.iterrows()):
                st.write(f"Processing {row['CALL_ID']}...")
                enhance_call(row['CALL_ID'])
                progress.progress((i+1)/len(ra_calls))
            st.success(f"Done! Enhanced {len(ra_calls)} calls.")

# ════════════════════════════════════════════════════════════════════════════
# NEW TABS
# ════════════════════════════════════════════════════════════════════════════

# ── Ask EchoMind ─────────────────────────────────────────────────────────────
with tab_ask:
    st.markdown("## 💬 Ask EchoMind")
    st.caption("Chat with AI about any processed call. Ask questions, get summaries, probe insights.")

    ask_calls = session.sql(f"SELECT DISTINCT CALL_ID FROM {DB}.CALL_SEGMENTS ORDER BY CALL_ID").to_pandas()
    if len(ask_calls) == 0:
        st.info("No calls processed yet. Upload a call first.")
    else:
        _ids = ask_calls['CALL_ID'].tolist()
        ask_sel = st.selectbox("Select call to query", _ids, index=_default_index(_ids), key="ask_call_select")

        chat_key = f"ask_chat_{ask_sel}"
        if chat_key not in st.session_state:
            st.session_state[chat_key] = []

        st.markdown("**Quick questions:**")
        qcol1, qcol2, qcol3, qcol4 = st.columns(4)
        quick_prompts = {
            "📋 Executive summary": "Give me a concise executive summary of this call in 3-5 bullet points covering purpose, key points, and outcome.",
            "😤 Frustration moments": "What were the moments of customer frustration in this call? What triggered them?",
            "✅ Was it resolved?": "Was the customer's issue resolved? What was the resolution status and outcome?",
            "💡 Key action items": "What are the key action items and next steps identified in this call?"
        }
        for col, (label, prompt) in zip([qcol1, qcol2, qcol3, qcol4], quick_prompts.items()):
            with col:
                if st.button(label, key=f"quick_{label}_{ask_sel}"):
                    st.session_state[chat_key].append({"role": "user", "content": prompt})

        for msg in st.session_state[chat_key]:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        user_q = st.chat_input("Ask anything about this call…", key=f"ask_input_{ask_sel}")
        if user_q:
            st.session_state[chat_key].append({"role": "user", "content": user_q})

        if st.session_state[chat_key] and st.session_state[chat_key][-1]["role"] == "user":
            last_q = st.session_state[chat_key][-1]["content"]

            ask_segs = session.sql(
                f"SELECT COALESCE(SPEAKER_ROLE,SPEAKER) AS SPK, SEGMENT_TEXT, SENTIMENT, "
                f"STANDARD_TOPIC, IS_KEY_MOMENT, MOMENT_TYPE "
                f"FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{ask_sel}' ORDER BY START_TIME"
            ).to_pandas()
            ask_ins = session.sql(f"SELECT * FROM {DB}.CALL_INSIGHTS WHERE CALL_ID='{ask_sel}'").to_pandas()

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
                f"Be concise, specific, and cite timestamps or speakers where relevant.{ins_context}{km_context}"
            )
            full_prompt = (
                f"{system_ctx}\n\nCall transcript (call ID: {ask_sel}):\n{tx_context}"
                f"\n\nUser question: {last_q}\n\nAnswer:"
            )

            with st.chat_message("assistant"):
                with st.spinner("EchoMind is thinking…"):
                    answer = _cortex(full_prompt)
                st.markdown(answer)
            st.session_state[chat_key].append({"role": "assistant", "content": answer})

        if st.session_state[chat_key]:
            if st.button("Clear conversation", key=f"clear_chat_{ask_sel}"):
                st.session_state[chat_key] = []
                st.rerun()

# ── Follow-Up Email ───────────────────────────────────────────────────────────
with tab_email:
    st.markdown("## 📧 Follow-Up Email")
    st.caption("Auto-generate a professional follow-up email based on call outcomes, action items, and next steps.")

    fe_calls = session.sql(f"SELECT DISTINCT CALL_ID FROM {DB}.CALL_SEGMENTS ORDER BY CALL_ID").to_pandas()
    if len(fe_calls) == 0:
        st.info("No calls processed yet. Upload a call first.")
    else:
        _ids = fe_calls['CALL_ID'].tolist()
        fe_sel = st.selectbox("Select call", _ids, index=_default_index(_ids), key="fe_call_select")

        fe_col1, fe_col2 = st.columns(2)
        with fe_col1:
            fe_sender = st.text_input("From (Agent name)", placeholder="e.g. Priya Sharma", key="fe_sender")
            fe_company = st.text_input("Company name", placeholder="e.g. Acme Corp", key="fe_company")
        with fe_col2:
            fe_recipient = st.text_input("Customer name", placeholder="e.g. Rahul Verma", key="fe_recipient")
            fe_tone = st.selectbox("Email tone", ["Professional", "Friendly", "Apologetic", "Follow-up focused"], key="fe_tone")

        if st.button("Generate follow-up email", key="fe_generate_btn"):
            fe_segs = session.sql(
                f"SELECT COALESCE(SPEAKER_ROLE,SPEAKER) AS SPK, SEGMENT_TEXT "
                f"FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{fe_sel}' ORDER BY START_TIME"
            ).to_pandas()
            fe_ins = session.sql(f"SELECT * FROM {DB}.CALL_INSIGHTS WHERE CALL_ID='{fe_sel}'").to_pandas()

            tx_lines = [f"{r['SPK']}: {r['SEGMENT_TEXT']}" for _, r in fe_segs.iterrows()]
            tx_snippet = "\n".join(tx_lines[:40])

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

            sender_str = fe_sender or "the agent"
            recipient_str = fe_recipient or "the customer"
            company_str = fe_company or "our company"

            fe_prompt = (
                f"Write a {fe_tone.lower()} follow-up email from {sender_str} at {company_str} "
                f"to {recipient_str} after a customer support call.\n"
                f"Use the call context below to make the email specific and relevant.\n"
                f"Include: subject line, greeting, brief call recap, any action items or commitments made, "
                f"next steps, and a professional sign-off.\n"
                f"Format as a ready-to-send email.\n"
                f"{ins_ctx}\n\nCall transcript (excerpt):\n{tx_snippet}"
            )

            with st.spinner("Drafting your follow-up email…"):
                fe_result = _cortex(fe_prompt)
            st.session_state[f'fe_email_{fe_sel}'] = fe_result

        if st.session_state.get(f'fe_email_{fe_sel}'):
            st.markdown("### Generated email")
            email_text = st.session_state[f'fe_email_{fe_sel}']
            st.text_area("Email draft (editable)", value=email_text, height=400, key=f"fe_edit_{fe_sel}")
            st.download_button(
                "⬇️ Download email (.txt)",
                data=email_text,
                file_name=f"followup_email_{fe_sel}.txt",
                mime="text/plain",
                key="fe_download"
            )

# ── Previous Runs ─────────────────────────────────────────────────────────────
with tab_prev:
    st.markdown("## 🗂️ Previous Runs")
    st.caption("Browse all processed calls with their key stats and analysis status at a glance.")

    pr_data = session.sql(f"""
        SELECT
            c.CALL_ID,
            COUNT(c.SEGMENT_ID)                                    AS SEGMENTS,
            ROUND(MAX(c.END_TIME), 0)                              AS DURATION_S,
            ROUND(AVG(c.SENTIMENT), 3)                             AS AVG_SENTIMENT,
            SUM(CASE WHEN c.IS_KEY_MOMENT THEN 1 ELSE 0 END)      AS KEY_MOMENTS,
            COUNT(DISTINCT c.STANDARD_TOPIC)                       AS UNIQUE_TOPICS,
            COALESCE(i.RESOLUTION_STATUS, '—')                     AS RESOLUTION,
            COALESCE(i.CSAT_INDICATOR, '—')                        AS CSAT,
            COALESCE(i.ESCALATION_FLAG, FALSE)                     AS ESCALATED,
            COALESCE(i.LEAD_INTENT_SCORE, 0)                       AS LEAD_SCORE,
            COALESCE(i.ISSUE_TYPE, '—')                            AS ISSUE_TYPE
        FROM {DB}.CALL_SEGMENTS c
        LEFT JOIN {DB}.CALL_INSIGHTS i ON c.CALL_ID = i.CALL_ID
        GROUP BY c.CALL_ID, i.RESOLUTION_STATUS, i.CSAT_INDICATOR,
                 i.ESCALATION_FLAG, i.LEAD_INTENT_SCORE, i.ISSUE_TYPE
        ORDER BY c.CALL_ID DESC
    """).to_pandas()

    if len(pr_data) == 0:
        st.info("No calls processed yet. Head to **Upload & Process** to get started.")
    else:
        pm1, pm2, pm3, pm4 = st.columns(4)
        with pm1:
            with st.container(border=True):
                st.metric("Total calls", len(pr_data))
        with pm2:
            resolved_count = len(pr_data[pr_data['RESOLUTION'] == 'Resolved'])
            with st.container(border=True):
                st.metric("✅ Resolved", resolved_count)
        with pm3:
            escalated_count = len(pr_data[pr_data['ESCALATED'] == True])
            with st.container(border=True):
                st.metric("🔺 Escalated", escalated_count)
        with pm4:
            avg_lead = int(pr_data['LEAD_SCORE'].mean()) if len(pr_data) > 0 else 0
            with st.container(border=True):
                st.metric("Avg lead score", f"{avg_lead}/100")

        st.divider()

        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            res_filter = st.multiselect(
                "Filter by resolution",
                options=pr_data['RESOLUTION'].unique().tolist(),
                default=[],
                key="pr_res_filter"
            )
        with fc2:
            csat_filter = st.multiselect(
                "Filter by CSAT",
                options=pr_data['CSAT'].unique().tolist(),
                default=[],
                key="pr_csat_filter"
            )
        with fc3:
            esc_filter = st.selectbox(
                "Escalated?",
                options=["All", "Yes", "No"],
                key="pr_esc_filter"
            )

        filtered = pr_data.copy()
        if res_filter:
            filtered = filtered[filtered['RESOLUTION'].isin(res_filter)]
        if csat_filter:
            filtered = filtered[filtered['CSAT'].isin(csat_filter)]
        if esc_filter == "Yes":
            filtered = filtered[filtered['ESCALATED'] == True]
        elif esc_filter == "No":
            filtered = filtered[filtered['ESCALATED'] == False]

        st.markdown(f"### Showing {len(filtered)} call(s)")

        for _, row in filtered.iterrows():
            res_icon = {"Resolved":"✅","Unresolved":"❌","Partial":"🟡","Escalated":"🔺","—":"❓"}.get(row['RESOLUTION'],"❓")
            csat_icon = {"Positive":"😊","Neutral":"😐","Negative":"😞","—":"❓"}.get(row['CSAT'],"❓")
            esc_badge = " 🔺 **Escalated**" if row['ESCALATED'] else ""
            dur_min = int(row['DURATION_S'] // 60)
            dur_sec = int(row['DURATION_S'] % 60)

            with st.expander(
                f"📞 {row['CALL_ID']}  |  {dur_min}m {dur_sec}s  |  "
                f"{res_icon} {row['RESOLUTION']}  |  {csat_icon} {row['CSAT']}{esc_badge}"
            ):
                rc1, rc2, rc3, rc4, rc5 = st.columns(5)
                with rc1:
                    st.metric("Segments", int(row['SEGMENTS']))
                with rc2:
                    st.metric("Avg sentiment", f"{row['AVG_SENTIMENT']:.2f}")
                with rc3:
                    st.metric("Key moments", int(row['KEY_MOMENTS']))
                with rc4:
                    st.metric("Unique topics", int(row['UNIQUE_TOPICS']))
                with rc5:
                    st.metric("Lead score", f"{int(row['LEAD_SCORE'])}/100")

                dc1, dc2 = st.columns(2)
                with dc1:
                    st.caption(f"**Issue type:** {row['ISSUE_TYPE']}")
                with dc2:
                    st.caption(f"**Resolution:** {row['RESOLUTION']}  ·  **CSAT:** {row['CSAT']}")

                qa1, qa2 = st.columns(2)
                with qa1:
                    if st.button("Set as active call", key=f"pr_set_{row['CALL_ID']}"):
                        st.session_state['last_call_id'] = row['CALL_ID']
                        st.success(f"Active call set to `{row['CALL_ID']}`")
                with qa2:
                    if st.button("Re-analyze", key=f"pr_reanalyze_{row['CALL_ID']}"):
                        enhance_call(row['CALL_ID'])
                        st.success(f"Re-analysis complete for `{row['CALL_ID']}`!")

        st.divider()
        if st.checkbox("Show raw table", key="pr_show_table"):
            display_cols = ['CALL_ID','SEGMENTS','DURATION_S','AVG_SENTIMENT',
                            'KEY_MOMENTS','UNIQUE_TOPICS','RESOLUTION','CSAT',
                            'ESCALATED','LEAD_SCORE','ISSUE_TYPE']
            st.dataframe(filtered[display_cols], use_container_width=True, hide_index=True)

# ── Footer ────────────────────────────────────────────────────────────────────
st.divider()
st.caption("🎧 EchoMind v2.0 · Powered by Snowflake Cortex AI + CoCo · Built with ❄️")