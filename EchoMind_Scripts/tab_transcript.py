import streamlit as st
from utils import DB, require_call, section_header, _default_index

def render(session):
    if not require_call("Full Transcript"):
        return

    section_header("📜", "Full Transcript", "Speaker-separated conversation with key moment annotations")

    tx_calls = session.sql(f"SELECT DISTINCT CALL_ID FROM {DB}.CALL_SEGMENTS ORDER BY CALL_ID").to_pandas()
    _ids = tx_calls['CALL_ID'].tolist()
    sel = st.selectbox("Select call", _ids, index=_default_index(_ids), key="tx_call")

    tx_seg = session.sql(f"SELECT * FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{sel}' ORDER BY START_TIME").to_pandas()

    if len(tx_seg) == 0:
        st.info("No transcript data found.")
        return

    # Summary stats bar
    agent_segs    = tx_seg[tx_seg.get('SPEAKER_ROLE', tx_seg.get('SPEAKER','')) == 'Agent'] if 'SPEAKER_ROLE' in tx_seg.columns else tx_seg
    customer_segs = tx_seg[tx_seg.get('SPEAKER_ROLE', tx_seg.get('SPEAKER','')) == 'Customer'] if 'SPEAKER_ROLE' in tx_seg.columns else tx_seg
    km_count      = tx_seg['IS_KEY_MOMENT'].sum() if 'IS_KEY_MOMENT' in tx_seg.columns else 0

    sc1,sc2,sc3,sc4 = st.columns(4)
    with sc1: st.metric("Total segments",   len(tx_seg))
    with sc2: st.metric("⭐ Key moments",    int(km_count))
    with sc3: st.metric("Avg sentiment",    f"{tx_seg['SENTIMENT'].mean():.2f}")
    with sc4:
        dur = tx_seg['END_TIME'].max()
        st.metric("Duration", f"{int(dur//60)}m {int(dur%60)}s")

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # Search / filter
    search = st.text_input("🔍 Search transcript", placeholder="Filter by keyword...", key="tx_search")

    st.divider()

    role_colors = {'Agent': ('#dbeafe','#1e40af','🔵'), 'Customer': ('#dcfce7','#166534','🟢')}

    for _, seg in tx_seg.iterrows():
        role = seg.get('SPEAKER_ROLE') or seg.get('SPEAKER','Unknown')
        text = seg['SEGMENT_TEXT']

        if search and search.lower() not in text.lower():
            continue

        bg, tc, dot = role_colors.get(role, ('#f8fafc','#334155','⚪'))
        mm, ss     = int(seg['START_TIME']//60), int(seg['START_TIME']%60)
        is_km      = bool(seg.get('IS_KEY_MOMENT', False))
        km_html    = ""
        if is_km:
            mt = seg.get('MOMENT_TYPE','')
            ms = seg.get('MOMENT_SEVERITY','')
            sev_col = {'high':'#ef4444','medium':'#f59e0b','low':'#22c55e'}.get(ms,'#94a3b8')
            km_html = f"<span style='background:{sev_col};color:#fff;border-radius:4px;padding:1px 7px;font-size:11px;margin-left:8px;'>⚡ {mt}</span>"

        sent     = float(seg.get('SENTIMENT', 0))
        sent_col = '#22c55e' if sent > 0.1 else '#ef4444' if sent < -0.2 else '#94a3b8'
        topic    = seg.get('STANDARD_TOPIC') or seg.get('TOPIC_LABEL','')
        topic_html = f"<span style='background:#f1f5f9;color:#475569;border-radius:4px;padding:1px 7px;font-size:11px;margin-left:6px;'>{topic}</span>" if topic else ""

        border = f"border-left:4px solid {'#ef4444' if is_km else bg};"

        st.markdown(f"""
        <div style='background:{bg};{border}border-radius:10px;padding:12px 16px;margin-bottom:8px;'>
            <div style='display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:4px;'>
                <div>
                    <span style='font-weight:700;color:{tc};font-size:13px;'>{dot} {role}</span>
                    {km_html}
                    {topic_html}
                </div>
                <div style='display:flex;align-items:center;gap:10px;'>
                    <span style='color:{sent_col};font-size:12px;font-weight:600;'>sent: {sent:.2f}</span>
                    <span style='color:#94a3b8;font-size:12px;'>`{mm:02d}:{ss:02d}`</span>
                </div>
            </div>
            <div style='color:#1e293b;margin-top:8px;font-size:14px;line-height:1.6;'>{text}</div>
        </div>
        """, unsafe_allow_html=True)
