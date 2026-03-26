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

    # ── Summary stats ────────────────────────────────────────────────────────
    km_count = tx_seg['IS_KEY_MOMENT'].sum() if 'IS_KEY_MOMENT' in tx_seg.columns else 0
    dur      = tx_seg['END_TIME'].max()

    sc1, sc2, sc3, sc4 = st.columns(4)
    with sc1: st.metric("Total segments", len(tx_seg))
    with sc2: st.metric("⭐ Key moments",  int(km_count))
    with sc3: st.metric("Avg sentiment",  f"{tx_seg['SENTIMENT'].mean():.2f}")
    with sc4: st.metric("Duration",       f"{int(dur//60)}m {int(dur%60)}s")

    # ── Search ───────────────────────────────────────────────────────────────
    search = st.text_input("🔍 Search transcript", placeholder="Filter by keyword...", key="tx_search")
    st.divider()

    # ── Segment rows — pure Streamlit, no HTML ───────────────────────────────
    role_icons = {'Agent': '🔵', 'Customer': '🟢'}
    sev_icons  = {'high': '🔴', 'medium': '🟡', 'low': '🟢'}

    for _, seg in tx_seg.iterrows():
        role = seg.get('SPEAKER_ROLE') or seg.get('SPEAKER', 'Unknown')
        text = seg['SEGMENT_TEXT']

        if search and search.lower() not in text.lower():
            continue

        mm, ss  = int(seg['START_TIME'] // 60), int(seg['START_TIME'] % 60)
        is_km   = bool(seg.get('IS_KEY_MOMENT', False))
        sent    = float(seg.get('SENTIMENT', 0))
        topic   = seg.get('STANDARD_TOPIC') or seg.get('TOPIC_LABEL', '')
        mt      = seg.get('MOMENT_TYPE', '') or ''
        ms      = seg.get('MOMENT_SEVERITY', '') or ''
        dot     = role_icons.get(role, '⚪')
        sev_dot = sev_icons.get(ms, '')

        # Build header line
        header_parts = [f"{dot} **{role}**", f"`{mm:02d}:{ss:02d}`"]
        if topic:
            header_parts.append(f"🏷 {topic}")
        if is_km:
            header_parts.append(f"⚡ {sev_dot} {mt}")

        sent_label = "🟢" if sent > 0.1 else "🔴" if sent < -0.2 else "🟡"

        with st.container(border=is_km):
            col_main, col_sent = st.columns([8, 1])
            with col_main:
                st.markdown("  ·  ".join(header_parts))
                st.write(text)
            with col_sent:
                st.caption(f"{sent_label}")
                st.caption(f"{sent:.2f}")