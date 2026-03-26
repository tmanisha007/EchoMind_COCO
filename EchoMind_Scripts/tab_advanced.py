import streamlit as st
from utils import DB, require_call, section_header, _default_index, enhance_call

def render(session):

    sub1, sub2, sub3 = st.tabs([
        "🔍 Compare Calls",
        "🏆 Leaderboard",
        "🔄 Re-Analyze",
    ])

    # ════════════════════════════════════════════════════════════════════════
    # SUB 1 — Compare Calls
    # ════════════════════════════════════════════════════════════════════════
    with sub1:
        section_header("🔍", "Compare Calls", "Side-by-side comparison of two calls")

        cp_calls = session.sql(f"SELECT DISTINCT CALL_ID FROM {DB}.CALL_SEGMENTS ORDER BY CALL_ID").to_pandas()
        if len(cp_calls) < 2:
            st.info("Need at least 2 processed calls to compare.")
        else:
            _ids = cp_calls['CALL_ID'].tolist()
            cl1, cl2 = st.columns(2)
            with cl1:
                cp1 = st.selectbox("Call A", _ids, index=_default_index(_ids), key="cp1")
            with cl2:
                default_b = 1 if len(_ids) > 1 else 0
                cp2 = st.selectbox("Call B", _ids, index=default_b, key="cp2")

            if cp1 != cp2:
                data = {}
                for cid in [cp1, cp2]:
                    s   = session.sql(f"SELECT * FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{cid}'").to_pandas()
                    ins = session.sql(f"SELECT * FROM {DB}.CALL_INSIGHTS WHERE CALL_ID='{cid}'").to_pandas()
                    km  = session.sql(f"SELECT * FROM {DB}.CALL_KEY_MOMENTS WHERE CALL_ID='{cid}'").to_pandas()
                    data[cid] = {'seg':s,'ins':ins,'km':km}

                compare_metrics = [
                    ("⏱️ Duration",        lambda d: f"{int(d['seg']['END_TIME'].max()//60)}m {int(d['seg']['END_TIME'].max()%60)}s"),
                    ("💬 Segments",        lambda d: str(len(d['seg']))),
                    ("⭐ Key Moments",     lambda d: str(len(d['km']))),
                    ("😐 Avg Sentiment",   lambda d: f"{d['seg']['SENTIMENT'].mean():.2f}"),
                    ("📉 Neg Segments %",  lambda d: f"{(d['seg']['SENTIMENT']<-0.2).sum()/len(d['seg'])*100:.1f}%"),
                    ("🎯 Lead Score",      lambda d: f"{int(d['ins']['LEAD_INTENT_SCORE'].iloc[0])}/100" if len(d['ins'])>0 else "N/A"),
                    ("✅ Resolution",      lambda d: d['ins']['RESOLUTION_STATUS'].iloc[0] if len(d['ins'])>0 and d['ins']['RESOLUTION_STATUS'].iloc[0] else "N/A"),
                    ("😊 CSAT",            lambda d: d['ins']['CSAT_INDICATOR'].iloc[0] if len(d['ins'])>0 and d['ins']['CSAT_INDICATOR'].iloc[0] else "N/A"),
                ]

                hc1, hc2, hc3 = st.columns([2,2,2])
                with hc1: st.markdown("**Metric**")
                with hc2: st.markdown(f"**{cp1}**")
                with hc3: st.markdown(f"**{cp2}**")
                st.divider()

                for label, fn in compare_metrics:
                    vc1, vc2, vc3 = st.columns([2,2,2])
                    v1 = fn(data[cp1])
                    v2 = fn(data[cp2])
                    with vc1: st.caption(label)
                    with vc2: st.markdown(f"**{v1}**")
                    with vc3: st.markdown(f"**{v2}**")

    # ════════════════════════════════════════════════════════════════════════
    # SUB 2 — Leaderboard
    # ════════════════════════════════════════════════════════════════════════
    with sub2:
        section_header("🏆", "Leaderboard", "All calls ranked by lead score and performance")

        lb = session.sql(f"""SELECT c.CALL_ID, COUNT(*) AS SEGMENTS,
            ROUND(MAX(c.END_TIME),0) AS DURATION_S, ROUND(AVG(c.SENTIMENT),3) AS AVG_SENTIMENT,
            COALESCE(i.LEAD_INTENT_SCORE,0) AS LEAD_SCORE,
            COALESCE(i.RESOLUTION_STATUS,'—') AS RESOLUTION,
            COALESCE(i.CSAT_INDICATOR,'—') AS CSAT,
            COALESCE(i.ESCALATION_FLAG,FALSE) AS ESCALATED
            FROM {DB}.CALL_SEGMENTS c LEFT JOIN {DB}.CALL_INSIGHTS i ON c.CALL_ID=i.CALL_ID
            GROUP BY c.CALL_ID,i.LEAD_INTENT_SCORE,i.RESOLUTION_STATUS,
                     i.CSAT_INDICATOR,i.ESCALATION_FLAG
            ORDER BY LEAD_SCORE DESC""").to_pandas()

        if len(lb) == 0:
            st.info("No calls processed yet.")
        else:
            lm1,lm2,lm3,lm4 = st.columns(4)
            with lm1:
                with st.container(border=True): st.metric("Total calls", len(lb))
            with lm2:
                with st.container(border=True): st.metric("✅ Resolved", len(lb[lb['RESOLUTION']=='Resolved']))
            with lm3:
                with st.container(border=True): st.metric("🔺 Escalated", len(lb[lb['ESCALATED']==True]))
            with lm4:
                with st.container(border=True): st.metric("Avg Lead Score", f"{lb['LEAD_SCORE'].mean():.0f}/100")

            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

            for rank, (_, row) in enumerate(lb.iterrows(), 1):
                res_icon  = {"Resolved":"✅","Unresolved":"❌","Partial":"🟡","Escalated":"🔺","—":"⬜"}.get(row['RESOLUTION'],"⬜")
                csat_icon = {"Positive":"😊","Neutral":"😐","Negative":"😞","—":"⬜"}.get(row['CSAT'],"⬜")
                medal     = {1:"🥇",2:"🥈",3:"🥉"}.get(rank, f"#{rank}")
                score     = int(row['LEAD_SCORE'])
                bar_w     = score
                bar_col   = "#22c55e" if score >= 70 else "#f59e0b" if score >= 40 else "#ef4444"
                is_active = row['CALL_ID'] == st.session_state.get('last_call_id','')
                bg        = "#eff6ff" if is_active else "#fafafa"
                border    = "2px solid #3b82f6" if is_active else "1px solid #e2e8f0"
                dur_m, dur_s = int(row['DURATION_S']//60), int(row['DURATION_S']%60)

                st.markdown(f"""
                <div style='background:{bg};border:{border};border-radius:12px;
                            padding:14px 18px;margin-bottom:8px;'>
                    <div style='display:flex;justify-content:space-between;align-items:center;'>
                        <div>
                            <span style='font-size:18px;'>{medal}</span>
                            <span style='font-weight:700;color:#1e40af;margin-left:8px;'>{row['CALL_ID']}</span>
                            {'<span style="background:#3b82f6;color:#fff;border-radius:4px;padding:1px 7px;font-size:11px;margin-left:6px;">ACTIVE</span>' if is_active else ''}
                        </div>
                        <div style='color:#64748b;font-size:13px;'>
                            ⏱ {dur_m}m {dur_s}s &nbsp;·&nbsp; {res_icon} {row['RESOLUTION']}
                            &nbsp;·&nbsp; {csat_icon} {row['CSAT']}
                        </div>
                    </div>
                    <div style='margin-top:10px;'>
                        <div style='display:flex;justify-content:space-between;font-size:12px;color:#64748b;margin-bottom:4px;'>
                            <span>Lead Score</span><span><strong style='color:{bar_col};'>{score}/100</strong></span>
                        </div>
                        <div style='background:#e2e8f0;border-radius:99px;height:8px;'>
                            <div style='background:{bar_col};width:{bar_w}%;height:8px;border-radius:99px;'></div>
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

    # ════════════════════════════════════════════════════════════════════════
    # SUB 3 — Re-Analyze
    # ════════════════════════════════════════════════════════════════════════
    with sub3:
        section_header("🔄", "Re-Analyze", "Re-run enhanced analysis on existing calls")

        ra_calls = session.sql(f"SELECT DISTINCT CALL_ID FROM {DB}.CALL_SEGMENTS ORDER BY CALL_ID").to_pandas()
        if len(ra_calls) == 0:
            st.info("No calls to re-analyze.")
        else:
            sel_ra = st.selectbox("Select call to re-analyze", ra_calls['CALL_ID'].tolist(), key="ra_call")

            rc1, rc2 = st.columns(2)
            with rc1:
                if st.button("🔄 Re-analyze selected call", key="ra_btn", use_container_width=True, type="primary"):
                    enhance_call(session, sel_ra)
                    st.success(f"✅ Call `{sel_ra}` re-analyzed!")
            with rc2:
                if st.button("🔄 Re-analyze ALL calls", key="ra_all_btn", use_container_width=True):
                    progress = st.progress(0)
                    for i, (_, row) in enumerate(ra_calls.iterrows()):
                        st.write(f"Processing {row['CALL_ID']}...")
                        enhance_call(session, row['CALL_ID'])
                        progress.progress((i+1)/len(ra_calls))
                    st.success(f"✅ Done! Enhanced {len(ra_calls)} calls.")
