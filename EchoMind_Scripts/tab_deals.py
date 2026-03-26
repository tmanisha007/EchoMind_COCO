import streamlit as st
import pandas as pd
from utils import DB, _cortex, _sq, _clean_json, section_header, _default_index
import json

def render(session):
    section_header("🏆", "Deal Intelligence",
                   "Join conversation data with sales pipeline — no competitor does this natively in Snowflake")

    st.markdown("""
    > **EchoMind's biggest differentiator:** Unlike Gong or Fireflies, EchoMind lives inside your
    > Snowflake warehouse — so it can join conversation intelligence with your actual sales pipeline,
    > CRM data, and revenue numbers. No API. No sync. No latency.
    """)

    # ── Sub-tabs ─────────────────────────────────────────────────────────────
    sub1, sub2, sub3, sub4 = st.tabs([
        "📊 Deal Health Scores",
        "🔗 Pipeline Intelligence",
        "📈 Win/Loss Analysis",
        "🎯 Rep Performance",
    ])

    # ════════════════════════════════════════════════════════════════════════
    # SUB 1 — Deal Health Scores
    # ════════════════════════════════════════════════════════════════════════
    with sub1:
        section_header("📊", "Deal Health Scores",
                       "AI-scored deal health based on conversation signals across all interactions")

        st.markdown("#### Enter deal / account data")
        st.caption("Paste your pipeline data below. EchoMind will cross-reference with conversation intelligence to score each deal.")

        # Manual deal entry
        with st.expander("➕ Add / update a deal", expanded=True):
            d1, d2, d3 = st.columns(3)
            with d1:
                deal_name    = st.text_input("Deal / Account name", placeholder="e.g. Acme Corp - Enterprise", key="deal_name")
                deal_owner   = st.text_input("Sales rep", placeholder="e.g. Priya Sharma", key="deal_owner")
            with d2:
                deal_stage   = st.selectbox("Stage", ["Prospecting","Discovery","Proposal","Negotiation","Closed Won","Closed Lost"], key="deal_stage")
                deal_value   = st.number_input("Deal value ($)", 0, 10000000, 50000, step=5000, key="deal_value")
            with d3:
                deal_close   = st.text_input("Expected close date", placeholder="e.g. 2024-03-31", key="deal_close")
                deal_call_id = st.text_input("Linked call / conversation ID", placeholder="e.g. SALES_CALL_MP3", key="deal_call_id")

            if st.button("🔍 Score this deal", key="score_deal_btn", type="primary"):
                if not deal_name.strip():
                    st.warning("Please enter a deal name.")
                else:
                    # Pull conversation data for linked call
                    conv_context = ""
                    km_context   = ""
                    ins_context  = ""

                    if deal_call_id.strip():
                        cid = _sq(deal_call_id.strip().upper())
                        try:
                            segs = session.sql(f"SELECT COALESCE(SPEAKER_ROLE,SPEAKER) AS SPK, SEGMENT_TEXT FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{cid}' ORDER BY START_TIME LIMIT 40").to_pandas()
                            if len(segs) > 0:
                                conv_context = "\n".join([f"{r['SPK']}: {r['SEGMENT_TEXT']}" for _, r in segs.iterrows()])[:4000]
                        except:
                            pass
                        try:
                            ins = session.sql(f"SELECT * FROM {DB}.CALL_INSIGHTS WHERE CALL_ID='{cid}'").to_pandas()
                            if len(ins) > 0:
                                row = ins.iloc[0]
                                ins_context = f"Resolution: {row.get('RESOLUTION_STATUS','?')}, CSAT: {row.get('CSAT_INDICATOR','?')}, Lead score: {row.get('LEAD_INTENT_SCORE','?')}, Objections: {row.get('OBJECTIONS','?')}, Buying signals: {row.get('BUYING_SIGNALS','?')}"
                        except:
                            pass
                        try:
                            km = session.sql(f"SELECT MOMENT_TYPE, SEVERITY FROM {DB}.CALL_KEY_MOMENTS WHERE CALL_ID='{cid}'").to_pandas()
                            if len(km) > 0:
                                km_context = "Key moments: " + ", ".join([f"{r['MOMENT_TYPE']}({r['SEVERITY']})" for _, r in km.iterrows()])
                        except:
                            pass

                    prompt = f"""You are a sales intelligence AI. Score this deal and provide analysis.

Deal: {deal_name}
Stage: {deal_stage}
Value: ${deal_value:,}
Rep: {deal_owner}
Close date: {deal_close}
{f'Conversation insights: {ins_context}' if ins_context else ''}
{f'Key moments detected: {km_context}' if km_context else ''}
{f'Conversation excerpt: {conv_context[:2000]}' if conv_context else 'No conversation data linked.'}

Return ONLY valid JSON:
{{"health_score":0-100,"risk_level":"Low|Medium|High|Critical","win_probability":0-100,
"positive_signals":["list"],"risk_signals":["list"],
"recommended_actions":["list of 3 specific next steps"],
"deal_summary":"2 sentence summary","forecast":"Likely to close|At risk|Needs attention|Strong"}}"""

                    with st.spinner("🧠 Scoring deal..."):
                        try:
                            raw    = _cortex(session, prompt)
                            result = json.loads(_clean_json(raw))
                            st.session_state[f'deal_{deal_name}'] = result
                        except Exception as e:
                            st.error(f"Scoring failed: {e}")

            # Show result
            key = f'deal_{deal_name}' if deal_name else None
            if key and st.session_state.get(key):
                r = st.session_state[key]
                health   = r.get('health_score', 50)
                win_prob = r.get('win_probability', 50)
                risk     = r.get('risk_level', 'Medium')
                forecast = r.get('forecast', 'Needs attention')

                h_color  = "#22c55e" if health >= 70 else "#f59e0b" if health >= 40 else "#ef4444"
                r_color  = {"Low":"#22c55e","Medium":"#f59e0b","High":"#f97316","Critical":"#ef4444"}.get(risk,"#94a3b8")

                st.markdown("---")
                st.markdown(f"### Deal Score: **{deal_name}**")

                sc1, sc2, sc3, sc4 = st.columns(4)
                with sc1:
                    with st.container(border=True):
                        st.metric("🏥 Health Score", f"{health}/100")
                        st.progress(health/100)
                with sc2:
                    with st.container(border=True):
                        st.metric("🎯 Win Probability", f"{win_prob}%")
                        st.progress(win_prob/100)
                with sc3:
                    with st.container(border=True):
                        st.metric("⚠️ Risk Level", risk)
                with sc4:
                    with st.container(border=True):
                        st.metric("📈 Forecast", forecast)

                if r.get('deal_summary'):
                    st.info(f"**📋 Summary:** {r['deal_summary']}")

                pos_col, risk_col = st.columns(2)
                with pos_col:
                    st.markdown("**✅ Positive signals:**")
                    for s in r.get('positive_signals', []):
                        st.markdown(f"- {s}")
                with risk_col:
                    st.markdown("**⚠️ Risk signals:**")
                    for s in r.get('risk_signals', []):
                        st.markdown(f"- {s}")

                st.markdown("**🎯 Recommended next actions:**")
                for i, action in enumerate(r.get('recommended_actions', []), 1):
                    st.markdown(f"{i}. {action}")

    # ════════════════════════════════════════════════════════════════════════
    # SUB 2 — Pipeline Intelligence
    # ════════════════════════════════════════════════════════════════════════
    with sub2:
        section_header("🔗", "Pipeline Intelligence",
                       "Cross-call patterns across your entire pipeline")

        calls_df = session.sql(f"""
            SELECT c.CALL_ID,
                   COUNT(c.SEGMENT_ID) AS SEGS,
                   ROUND(AVG(c.SENTIMENT),2) AS AVG_SENT,
                   COALESCE(i.LEAD_INTENT_SCORE,0) AS LEAD,
                   COALESCE(i.RESOLUTION_STATUS,'—') AS RES,
                   COALESCE(i.CSAT_INDICATOR,'—') AS CSAT,
                   COALESCE(i.ESCALATION_FLAG,FALSE) AS ESC,
                   COALESCE(i.ISSUE_TYPE,'—') AS ISSUE,
                   COALESCE(i.OBJECTIONS,'') AS OBJECTIONS,
                   COALESCE(i.BUYING_SIGNALS,'') AS BUYING_SIGNALS,
                   COALESCE(i.COMPETITOR_MENTIONS,'') AS COMPETITORS
            FROM {DB}.CALL_SEGMENTS c
            LEFT JOIN {DB}.CALL_INSIGHTS i ON c.CALL_ID=i.CALL_ID
            GROUP BY c.CALL_ID,i.LEAD_INTENT_SCORE,i.RESOLUTION_STATUS,
                     i.CSAT_INDICATOR,i.ESCALATION_FLAG,i.ISSUE_TYPE,
                     i.OBJECTIONS,i.BUYING_SIGNALS,i.COMPETITOR_MENTIONS
            ORDER BY LEAD DESC
        """).to_pandas()

        if len(calls_df) == 0:
            st.info("No conversations processed yet.")
        else:
            # Pipeline summary
            p1,p2,p3,p4,p5 = st.columns(5)
            with p1:
                with st.container(border=True):
                    st.metric("📞 Total Conversations", len(calls_df))
            with p2:
                hot = len(calls_df[calls_df['LEAD'] >= 70])
                with st.container(border=True):
                    st.metric("🔥 Hot (Lead ≥70)", hot)
            with p3:
                esc = len(calls_df[calls_df['ESC'] == True])
                with st.container(border=True):
                    st.metric("🔺 Escalated", esc)
            with p4:
                avg_lead = calls_df['LEAD'].mean()
                with st.container(border=True):
                    st.metric("🎯 Avg Lead Score", f"{avg_lead:.0f}/100")
            with p5:
                pos_sent = len(calls_df[calls_df['AVG_SENT'] > 0.1])
                with st.container(border=True):
                    st.metric("😊 Positive Sentiment", pos_sent)

            st.divider()

            # Competitor intelligence
            all_competitors = []
            for _, row in calls_df.iterrows():
                comp = str(row.get('COMPETITORS',''))
                if comp and comp.lower() not in ['','none','null','[]','nan']:
                    all_competitors.append(comp)

            if all_competitors:
                st.markdown("#### 🏁 Competitor Intelligence")
                comp_prompt = f"""Analyze these competitor mentions from customer conversations and identify:
1. Which competitors are mentioned most
2. What context they appear in (pricing, features, switching)
3. Key competitive risks

Mentions: {' | '.join(all_competitors[:20])}

Return a brief 3-4 point competitive intelligence summary."""
                comp_key = "comp_intel"
                if comp_key not in st.session_state:
                    with st.spinner("Analysing competitor mentions..."):
                        st.session_state[comp_key] = _cortex(session, comp_prompt)
                st.warning(st.session_state[comp_key])

            # Objection patterns
            all_objections = []
            for _, row in calls_df.iterrows():
                obj = str(row.get('OBJECTIONS',''))
                if obj and obj.lower() not in ['','none','null','[]','nan']:
                    all_objections.append(obj)

            if all_objections:
                st.markdown("#### 🚧 Top Objection Patterns")
                obj_prompt = f"""Analyze these objections from customer conversations.
Identify the top 3-4 recurring objection themes and suggest how to handle each.

Objections: {' | '.join(all_objections[:20])}

Format as: Theme → Handling strategy"""
                obj_key = "obj_patterns"
                if obj_key not in st.session_state:
                    with st.spinner("Analysing objection patterns..."):
                        st.session_state[obj_key] = _cortex(session, obj_prompt)
                st.info(st.session_state[obj_key])

            st.markdown("#### 📋 Full Pipeline View")
            display = calls_df[['CALL_ID','LEAD','AVG_SENT','RES','CSAT','ESC','ISSUE']].copy()
            display.columns = ['Conversation','Lead Score','Avg Sentiment','Resolution','CSAT','Escalated','Issue Type']
            st.dataframe(display, use_container_width=True, hide_index=True)

    # ════════════════════════════════════════════════════════════════════════
    # SUB 3 — Win/Loss Analysis
    # ════════════════════════════════════════════════════════════════════════
    with sub3:
        section_header("📈", "Win/Loss Analysis",
                       "Understand why deals are won or lost based on conversation patterns")

        calls_df2 = session.sql(f"""
            SELECT c.CALL_ID, COALESCE(i.RESOLUTION_STATUS,'Unknown') AS RES,
                   COALESCE(i.LEAD_INTENT_SCORE,0) AS LEAD,
                   ROUND(AVG(c.SENTIMENT),2) AS SENT,
                   SUM(CASE WHEN c.IS_KEY_MOMENT THEN 1 ELSE 0 END) AS KM_COUNT,
                   COALESCE(i.OBJECTIONS,'') AS OBJ,
                   COALESCE(i.BUYING_SIGNALS,'') AS BS
            FROM {DB}.CALL_SEGMENTS c
            LEFT JOIN {DB}.CALL_INSIGHTS i ON c.CALL_ID=i.CALL_ID
            GROUP BY c.CALL_ID,i.RESOLUTION_STATUS,i.LEAD_INTENT_SCORE,
                     i.OBJECTIONS,i.BUYING_SIGNALS
        """).to_pandas()

        if len(calls_df2) == 0:
            st.info("No data yet. Process some conversations first.")
        else:
            resolved   = calls_df2[calls_df2['RES'] == 'Resolved']
            unresolved = calls_df2[calls_df2['RES'] == 'Unresolved']
            escalated  = calls_df2[calls_df2['RES'] == 'Escalated']

            w1,w2,w3 = st.columns(3)
            with w1:
                with st.container(border=True):
                    st.metric("✅ Resolved", len(resolved))
                    if len(resolved) > 0:
                        st.caption(f"Avg lead: {resolved['LEAD'].mean():.0f} · Avg sentiment: {resolved['SENT'].mean():.2f}")
            with w2:
                with st.container(border=True):
                    st.metric("❌ Unresolved", len(unresolved))
                    if len(unresolved) > 0:
                        st.caption(f"Avg lead: {unresolved['LEAD'].mean():.0f} · Avg sentiment: {unresolved['SENT'].mean():.2f}")
            with w3:
                with st.container(border=True):
                    st.metric("🔺 Escalated", len(escalated))
                    if len(escalated) > 0:
                        st.caption(f"Avg lead: {escalated['LEAD'].mean():.0f} · Avg sentiment: {escalated['SENT'].mean():.2f}")

            if st.button("🧠 Generate Win/Loss AI Report", key="wl_report_btn", type="primary"):
                wl_data = f"""
Resolved conversations: {len(resolved)}, avg lead score: {resolved['LEAD'].mean():.0f if len(resolved)>0 else 0}, avg sentiment: {resolved['SENT'].mean():.2f if len(resolved)>0 else 0}
Unresolved: {len(unresolved)}, avg lead: {unresolved['LEAD'].mean():.0f if len(unresolved)>0 else 0}, avg sentiment: {unresolved['SENT'].mean():.2f if len(unresolved)>0 else 0}
Escalated: {len(escalated)}
Total key moments across all conversations: {calls_df2['KM_COUNT'].sum()}
"""
                prompt = f"""You are a sales and CX intelligence analyst. Based on this conversation data, provide a Win/Loss analysis report.

Data:
{wl_data}

Provide:
1. KEY PATTERNS IN RESOLVED conversations — what made them succeed
2. KEY PATTERNS IN UNRESOLVED conversations — what caused failure
3. TOP 3 RECOMMENDATIONS to improve resolution rate
4. EARLY WARNING SIGNALS to watch for

Be specific and actionable."""
                with st.spinner("Generating win/loss report..."):
                    st.session_state['wl_report'] = _cortex(session, prompt)

            if st.session_state.get('wl_report'):
                st.markdown(st.session_state['wl_report'])
                st.download_button("⬇️ Download Win/Loss Report",
                    data=st.session_state['wl_report'],
                    file_name="echomind_winloss_report.txt",
                    mime="text/plain", key="dl_wl")

    # ════════════════════════════════════════════════════════════════════════
    # SUB 4 — Rep Performance
    # ════════════════════════════════════════════════════════════════════════
    with sub4:
        section_header("🎯", "Rep Performance",
                       "Compare agent/rep performance across all conversations")

        rep_df = session.sql(f"""
            SELECT COALESCE(SPEAKER_ROLE,'Unknown') AS ROLE,
                   CALL_ID,
                   ROUND(AVG(SENTIMENT),2) AS AVG_SENT,
                   COUNT(*) AS SEGS,
                   SUM(CASE WHEN IS_KEY_MOMENT THEN 1 ELSE 0 END) AS KM
            FROM {DB}.CALL_SEGMENTS
            WHERE COALESCE(SPEAKER_ROLE,'') = 'Agent'
            GROUP BY SPEAKER_ROLE, CALL_ID
            ORDER BY AVG_SENT DESC
        """).to_pandas()

        if len(rep_df) == 0:
            st.info("No agent data yet. Re-analyze calls to map speaker roles first.")
        else:
            st.markdown("**Agent performance across conversations:**")
            rep_df.columns = ['Role','Conversation','Avg Sentiment','Segments','Key Moments']
            st.dataframe(rep_df, use_container_width=True, hide_index=True)

            st.markdown("**Sentiment distribution:**")
            st.bar_chart(rep_df.set_index('Conversation')['Avg Sentiment'])

            if st.button("🧠 Generate Rep Coaching Summary", key="rep_coach_btn", type="primary"):
                prompt = f"""Based on this agent performance data across {len(rep_df)} conversations:
Average sentiment range: {rep_df['Avg Sentiment'].min():.2f} to {rep_df['Avg Sentiment'].max():.2f}
Average key moments per call: {rep_df['Key Moments'].mean():.1f}

Generate a team performance coaching summary with:
1. Overall team performance assessment
2. Top 3 patterns to address
3. Specific training recommendations
4. Recognition opportunities"""
                with st.spinner("Generating coaching summary..."):
                    st.session_state['rep_coach'] = _cortex(session, prompt)

            if st.session_state.get('rep_coach'):
                st.markdown(st.session_state['rep_coach'])
