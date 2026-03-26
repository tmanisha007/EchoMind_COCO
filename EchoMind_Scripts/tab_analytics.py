import streamlit as st
import pandas as pd
from utils import DB, require_call, section_header, _default_index

def render(session):
    if not require_call("Analytics"):
        return

    call_id = st.session_state['last_call_id']

    # ── Sub-tabs ─────────────────────────────────────────────────────────────
    sub1, sub2, sub3, sub4 = st.tabs([
        "📈 Sentiment Deep Dive",
        "🧩 Topic Clusters",
        "🗺️ Call Journey",
        "🔄 Topic Trends",
    ])

    # ════════════════════════════════════════════════════════════════════════
    # SUB 1 — Sentiment Deep Dive
    # ════════════════════════════════════════════════════════════════════════
    with sub1:
        section_header("📈", "Sentiment Deep Dive", "Full sentiment analysis with negative segment highlights")

        se_calls = session.sql(f"SELECT DISTINCT CALL_ID FROM {DB}.CALL_SEGMENTS ORDER BY CALL_ID").to_pandas()
        _ids = se_calls['CALL_ID'].tolist()
        sel_se = st.selectbox("Select call", _ids, index=_default_index(_ids), key="se_call")
        se_seg = session.sql(f"SELECT * FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{sel_se}' ORDER BY START_TIME").to_pandas()

        if len(se_seg) > 0:
            avg_s = se_seg['SENTIMENT'].mean()
            pos_c = (se_seg['SENTIMENT'] > 0.1).sum()
            neg_c = (se_seg['SENTIMENT'] < -0.2).sum()
            neu_c = len(se_seg) - pos_c - neg_c

            s1,s2,s3,s4 = st.columns(4)
            with s1: st.metric("Avg Sentiment", f"{avg_s:.2f}")
            with s2: st.metric("😊 Positive",   str(pos_c))
            with s3: st.metric("😐 Neutral",    str(neu_c))
            with s4: st.metric("😞 Negative",   str(neg_c))

            st.markdown("**Sentiment over time:**")
            st.line_chart(se_seg.set_index('START_TIME')['SENTIMENT'], color=["#3b82f6"])

            st.markdown("**Distribution:**")
            se_seg['Bucket'] = pd.cut(se_seg['SENTIMENT'], bins=[-1,-0.3,0.3,1], labels=['Negative','Neutral','Positive'])
            st.bar_chart(se_seg['Bucket'].value_counts())

            neg = se_seg[se_seg['SENTIMENT'] < -0.2].sort_values('SENTIMENT')
            if len(neg) > 0:
                st.markdown("**🔴 Most negative segments:**")
                for _, n in neg.head(5).iterrows():
                    mm, ss = int(n['START_TIME']//60), int(n['START_TIME']%60)
                    role   = n.get('SPEAKER_ROLE') or n.get('SPEAKER','')
                    st.markdown(f"""
                    <div style='background:#fef2f2;border-left:4px solid #ef4444;border-radius:8px;
                                padding:12px 16px;margin-bottom:8px;'>
                        <div style='color:#991b1b;font-weight:700;font-size:13px;'>
                            {role} &nbsp;·&nbsp; `{mm:02d}:{ss:02d}` &nbsp;·&nbsp; sent: {n['SENTIMENT']:.2f}
                        </div>
                        <div style='color:#7f1d1d;margin-top:4px;font-size:13px;'>{n['SEGMENT_TEXT'][:150]}</div>
                    </div>
                    """, unsafe_allow_html=True)

    # ════════════════════════════════════════════════════════════════════════
    # SUB 2 — Topic Clusters
    # ════════════════════════════════════════════════════════════════════════
    with sub2:
        section_header("🧩", "Topic Clusters", "Standardized topic classification with conversation flow")

        tc_calls = session.sql(f"SELECT DISTINCT CALL_ID FROM {DB}.CALL_SEGMENTS WHERE STANDARD_TOPIC IS NOT NULL OR TOPIC_LABEL IS NOT NULL ORDER BY CALL_ID").to_pandas()
        if len(tc_calls) == 0:
            st.info("No topic data. Run Re-Analyze on the call first.")
        else:
            _ids = tc_calls['CALL_ID'].tolist()
            sel_tc = st.selectbox("Select call", _ids, index=_default_index(_ids), key="tc_call")
            tc_seg = session.sql(f"SELECT * FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{sel_tc}' ORDER BY START_TIME").to_pandas()
            has_std = 'STANDARD_TOPIC' in tc_seg.columns and tc_seg['STANDARD_TOPIC'].notna().any()
            tcol    = 'STANDARD_TOPIC' if has_std else 'TOPIC_LABEL'
            tcolors = {
                'Greeting':'🟦','Identity_Verification':'🟦','Intent_Discovery':'🟩',
                'Troubleshooting':'🟧','Frustration':'🟥','Escalation':'🟥',
                'Resolution':'✅','Pricing':'💰','Objection':'🟥',
                'Closing':'🟦','Follow_Up':'🟩','Product_Info':'🟧','Small_Talk':'⬜'
            }

            # Phase flow
            if has_std:
                seen = []
                for _, seg in tc_seg.iterrows():
                    t = seg.get(tcol)
                    if t and (not seen or seen[-1] != t):
                        seen.append(t)
                st.markdown("**Call phases:** " + " → ".join([f"{tcolors.get(t,'📌')} {t}" for t in seen]))
                st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

            # Critical
            crit = tc_seg[tc_seg[tcol].isin(['Frustration','Escalation'])]
            if len(crit) > 0:
                st.markdown("**🚨 Critical segments:**")
                for _, cs in crit.iterrows():
                    mm, ss = int(cs['START_TIME']//60), int(cs['START_TIME']%60)
                    st.error(f"**{cs[tcol]}** @ {mm:02d}:{ss:02d} — {cs['SEGMENT_TEXT'][:150]}")

            with st.expander("📋 Full conversation flow"):
                for _, seg in tc_seg.iterrows():
                    topic  = seg.get(tcol) or 'Unknown'
                    role   = seg.get('SPEAKER_ROLE') or 'Unknown'
                    is_km  = seg.get('IS_KEY_MOMENT', False)
                    mm, ss = int(seg['START_TIME']//60), int(seg['START_TIME']%60)
                    ti     = tcolors.get(topic,'⬜')
                    ri     = "🔵" if role=='Agent' else "🟢" if role=='Customer' else "⚪"
                    km     = " ⚡" if is_km else ""
                    st.markdown(f"`{mm:02d}:{ss:02d}` {ti} **{topic}** {ri} {role}{km} — _{seg['SEGMENT_TEXT'][:80]}_")

            st.markdown("**Topic distribution:**")
            st.bar_chart(tc_seg[tcol].value_counts())

            if has_std:
                st.markdown("**Topic vs Sentiment:**")
                ts = tc_seg.groupby('STANDARD_TOPIC')['SENTIMENT'].agg(['mean','count']).reset_index()
                ts.columns = ['Topic','Avg Sentiment','Segments']
                st.dataframe(ts.sort_values('Avg Sentiment'), use_container_width=True, hide_index=True)

    # ════════════════════════════════════════════════════════════════════════
    # SUB 3 — Call Journey
    # ════════════════════════════════════════════════════════════════════════
    with sub3:
        section_header("🗺️", "Call Journey", "End-to-end visual flow of the conversation")

        tj_calls = session.sql(f"SELECT DISTINCT CALL_ID FROM {DB}.CALL_SEGMENTS ORDER BY CALL_ID").to_pandas()
        _ids = tj_calls['CALL_ID'].tolist()
        sel_tj = st.selectbox("Select call", _ids, index=_default_index(_ids), key="tj_call")
        tj_seg = session.sql(f"SELECT * FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{sel_tj}' ORDER BY START_TIME").to_pandas()

        has_roles  = 'SPEAKER_ROLE' in tj_seg.columns and tj_seg['SPEAKER_ROLE'].notna().any()
        has_topics = 'STANDARD_TOPIC' in tj_seg.columns and tj_seg['STANDARD_TOPIC'].notna().any()
        rc = 'SPEAKER_ROLE' if has_roles else 'SPEAKER'
        tc = 'STANDARD_TOPIC' if has_topics else 'TOPIC_LABEL'
        pi = {'Greeting':'👋','Identity_Verification':'🪪','Intent_Discovery':'🔍',
              'Troubleshooting':'🔧','Product_Info':'📦','Pricing':'💲','Objection':'🚧',
              'Frustration':'😤','Escalation':'🔺','Resolution':'✅',
              'Follow_Up':'📋','Closing':'👋','Small_Talk':'💬'}

        if has_topics:
            seen = []
            for _, seg in tj_seg.iterrows():
                t = seg.get(tc)
                if t and (not seen or seen[-1] != t):
                    seen.append(t)
            st.markdown("**Call phases:** " + " → ".join([f"{pi.get(t,'📌')} {t}" for t in seen]))
            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

        for _, seg in tj_seg.iterrows():
            topic  = seg.get(tc) or 'Unknown'
            role   = seg.get(rc) or 'Unknown'
            is_km  = seg.get('IS_KEY_MOMENT', False)
            mm, ss = int(seg['START_TIME']//60), int(seg['START_TIME']%60)
            dur    = seg['END_TIME'] - seg['START_TIME']
            rm     = "🔵" if role=='Agent' else "🟢" if role=='Customer' else "⚪"
            ti     = pi.get(topic,'📌')
            km     = " **⚡**" if is_km else ""
            sent   = float(seg.get('SENTIMENT',0))
            sb     = "🟢" if sent>0.1 else "🔴" if sent<-0.2 else "🟡"
            bg     = "#fff8f8" if is_km else "#fafafa"
            border = "border:1px solid #fca5a5;" if is_km else "border:1px solid #f1f5f9;"

            col_t, col_c = st.columns([1,5])
            with col_t:
                st.caption(f"`{mm:02d}:{ss:02d}`")
                st.caption(f"{dur:.1f}s")
            with col_c:
                st.markdown(f"""
                <div style='background:{bg};{border}border-radius:8px;padding:10px 14px;margin-bottom:6px;'>
                    <div style='font-weight:600;font-size:13px;'>
                        {rm} {ti} {topic} — {role}{' ⚡' if is_km else ''}
                    </div>
                    <div style='color:#64748b;font-size:12px;margin-top:4px;'>
                        {seg['SEGMENT_TEXT'][:120]} &nbsp; {sb} {sent:.2f}
                    </div>
                </div>
                """, unsafe_allow_html=True)

        if has_topics:
            st.markdown("**Time spent per phase:**")
            tj_seg['dur'] = tj_seg['END_TIME'] - tj_seg['START_TIME']
            st.bar_chart(tj_seg.groupby(tc)['dur'].sum().sort_values(ascending=False))

    # ════════════════════════════════════════════════════════════════════════
    # SUB 4 — Topic Trends (cross-call)
    # ════════════════════════════════════════════════════════════════════════
    with sub4:
        section_header("🔄", "Topic Trends", "Cross-call topic and sentiment patterns")

        trend_seg = session.sql(f"""SELECT CALL_ID, COALESCE(STANDARD_TOPIC,TOPIC_LABEL) AS TOPIC,
            COUNT(*) AS SEG_COUNT, ROUND(AVG(SENTIMENT),3) AS AVG_SENTIMENT
            FROM {DB}.CALL_SEGMENTS WHERE COALESCE(STANDARD_TOPIC,TOPIC_LABEL) IS NOT NULL
            GROUP BY CALL_ID, COALESCE(STANDARD_TOPIC,TOPIC_LABEL) ORDER BY CALL_ID""").to_pandas()

        if len(trend_seg) == 0:
            st.info("No cross-call topic data yet. Process more calls to see trends.")
        else:
            st.markdown("**Topic frequency across calls:**")
            tp = trend_seg.pivot_table(index='CALL_ID', columns='TOPIC', values='SEG_COUNT', fill_value=0)
            st.bar_chart(tp)

            st.markdown("**Topic sentiment across calls:**")
            sp = trend_seg.pivot_table(index='CALL_ID', columns='TOPIC', values='AVG_SENTIMENT', fill_value=0)
            st.line_chart(sp)

            st.markdown("**Most discussed topics overall:**")
            st.bar_chart(trend_seg.groupby('TOPIC')['SEG_COUNT'].sum().sort_values(ascending=False).head(10))
