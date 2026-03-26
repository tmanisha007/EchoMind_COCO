import streamlit as st
import json
from snowflake.snowpark.context import get_active_session

CORTEX_MODEL = 'claude-4-sonnet'
DB = 'ECHOMIND_DB.APP'

def get_session():
    return get_active_session()

def _cortex(session, prompt):
    safe = prompt.replace('$$', '$ $')
    return session.sql(f"SELECT SNOWFLAKE.CORTEX.COMPLETE('{CORTEX_MODEL}', $${safe}$$) AS R").collect()[0]['R']

def _clean_json(raw):
    return raw.strip().replace('```json', '').replace('```', '').strip()

def _sq(v):
    return str(v or '').replace("'", "''")

def _default_index(call_list, default_id=None):
    cid = default_id or st.session_state.get('last_call_id')
    if cid and cid in call_list:
        return call_list.index(cid)
    return 0

def map_speaker_roles(session, call_id):
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
        result = _cortex(session, prompt)
        mapping = json.loads(_clean_json(result))
        for label, role in mapping.items():
            session.sql(f"UPDATE {DB}.CALL_SEGMENTS SET SPEAKER_ROLE='{_sq(role)}' WHERE CALL_ID='{call_id}' AND SPEAKER='{_sq(label)}'").collect()
    except Exception as e:
        st.warning(f"Speaker role mapping partial: {e}")

def standardize_topics_and_moments(session, call_id):
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
        items = json.loads(_clean_json(_cortex(session, prompt)))
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

def extract_call_kpis(session, call_id):
    segs = session.sql(f"SELECT COALESCE(SPEAKER_ROLE,SPEAKER) AS SPK, SEGMENT_TEXT FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{call_id}' ORDER BY START_TIME").to_pandas()
    if len(segs) == 0:
        return
    lines = [f"{r['SPK']}: {r['SEGMENT_TEXT']}" for _, r in segs.iterrows()]
    prompt = f"""Analyze this call and extract KPIs. Return ONLY valid JSON:
{{"resolution_status":"Resolved|Unresolved|Partial|Escalated","escalation_flag":true|false,"csat_indicator":"Positive|Neutral|Negative","call_outcome":"one sentence","issue_type":"category","root_cause":"brief or null"}}

Transcript:
{chr(10).join(lines)}"""
    try:
        kpis = json.loads(_clean_json(_cortex(session, prompt)))
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

def enhance_call(session, call_id):
    with st.status("🔍 Enhancing call analysis...", expanded=True) as status:
        st.write("🎙️ Mapping speaker roles (Agent vs Customer)...")
        map_speaker_roles(session, call_id)
        st.write("🧩 Standardizing topics & detecting key moments...")
        standardize_topics_and_moments(session, call_id)
        st.write("📊 Extracting structured KPIs...")
        extract_call_kpis(session, call_id)
        status.update(label="✅ Enhancement complete!", state="complete")

def init_session_state():
    defaults = {
        'last_call_id': None,
        'call_tags': {},
        'call_notes': {},
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

def require_call(label="this tab"):
    if not st.session_state.get('last_call_id'):
        st.markdown("""
        <div style='text-align:center; padding: 60px 20px;'>
            <div style='font-size:48px;'>📭</div>
            <h3 style='color:#666; margin-top:12px;'>No call loaded yet</h3>
            <p style='color:#999;'>Head to <strong>Upload & Process</strong> to analyse your first call.</p>
        </div>
        """, unsafe_allow_html=True)
        return False
    return True

def section_header(icon, title, subtitle=""):
    st.markdown(f"""
    <div style='margin-bottom:8px;'>
        <span style='font-size:22px; font-weight:700;'>{icon} {title}</span>
        {'<br><span style="color:#888; font-size:13px;">'+subtitle+'</span>' if subtitle else ''}
    </div>
    """, unsafe_allow_html=True)

def badge(text, color="#1a73e8"):
    return f"<span style='background:{color};color:#fff;border-radius:4px;padding:2px 8px;font-size:12px;font-weight:600;'>{text}</span>"