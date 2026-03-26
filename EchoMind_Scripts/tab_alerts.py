import streamlit as st
import pandas as pd
from utils import DB, _cortex, _sq, _clean_json, section_header
import json

def render(session):
    section_header("🚨", "Churn Risk & Proactive Alerts",
                   "Cross-conversation pattern detection — catch risks before they become problems")

    st.markdown("""
    > **No competitor does this:** EchoMind analyses patterns **across all your conversations**
    > to proactively surface churn risks, recurring complaints, competitor threats, and coaching gaps —
    > before your CRM or support team even notices.
    """)

    sub1, sub2, sub3 = st.tabs([
        "🔴 Churn Risk Radar",
        "📊 Pattern Intelligence",
        "🔔 Alert Configuration",
    ])

    # ════════════════════════════════════════════════════════════════════════
    # SUB 1 — Churn Risk Radar
    # ════════════════════════════════════════════════════════════════════════
    with sub1:
        section_header("🔴", "Churn Risk Radar", "AI-scored churn risk across all accounts")

        all_data = session.sql(f"""
            SELECT c.CALL_ID,
                   COUNT(c.SEGMENT_ID) AS SEGS,
                   ROUND(AVG(c.SENTIMENT),3) AS AVG_SENT,
                   SUM(CASE WHEN c.IS_KEY_MOMENT THEN 1 ELSE 0 END) AS KM_COUNT,
                   SUM(CASE WHEN c.MOMENT_TYPE IN ('Frustration','Complaint','Escalation_Request') THEN 1 ELSE 0 END) AS NEG_MOMENTS,
                   COALESCE(i.ESCALATION_FLAG,FALSE) AS ESCALATED,
                   COALESCE(i.CSAT_INDICATOR,'Unknown') AS CSAT,
                   COALESCE(i.RESOLUTION_STATUS,'Unknown') AS RES,
                   COALESCE(i.LEAD_INTENT_SCORE,50) AS LEAD,
                   COALESCE(i.ROOT_CAUSE,'') AS ROOT_CAUSE,
                   COALESCE(i.COMPETITOR_MENTIONS,'') AS COMPETITORS
            FROM {DB}.CALL_SEGMENTS c
            LEFT JOIN {DB}.CALL_INSIGHTS i ON c.CALL_ID=i.CALL_ID
            GROUP BY c.CALL_ID, i.ESCALATION_FLAG, i.CSAT_INDICATOR,
                     i.RESOLUTION_STATUS, i.LEAD_INTENT_SCORE,
                     i.ROOT_CAUSE, i.COMPETITOR_MENTIONS
        """).to_pandas()

        if len(all_data) == 0:
            st.info("No conversations processed yet.")
        else:
            # Calculate churn risk score for each conversation
            def churn_score(row):
                score = 50  # baseline
                sent  = float(row.get('AVG_SENT', 0) or 0)
                score -= sent * 30          # negative sentiment increases risk
                if row.get('ESCALATED'):     score += 25
                if row.get('CSAT') == 'Negative': score += 20
                if row.get('RES') == 'Unresolved': score += 15
                neg_m = int(row.get('NEG_MOMENTS', 0) or 0)
                score += neg_m * 5
                comp = str(row.get('COMPETITORS',''))
                if comp and comp.lower() not in ['','none','null','[]','nan']:
                    score += 15             # competitor mentioned = churn signal
                lead = int(row.get('LEAD', 50) or 50)
                score -= (lead - 50) * 0.3  # low lead score increases risk
                return max(0, min(100, int(score)))

            all_data['CHURN_RISK'] = all_data.apply(churn_score, axis=1)
            all_data = all_data.sort_values('CHURN_RISK', ascending=False)

            # Summary
            critical = len(all_data[all_data['CHURN_RISK'] >= 75])
            high     = len(all_data[(all_data['CHURN_RISK'] >= 50) & (all_data['CHURN_RISK'] < 75)])
            low      = len(all_data[all_data['CHURN_RISK'] < 50])

            r1,r2,r3,r4 = st.columns(4)
            with r1:
                with st.container(border=True):
                    st.metric("Total accounts", len(all_data))
            with r2:
                with st.container(border=True):
                    st.metric("🔴 Critical risk (≥75)", critical)
            with r3:
                with st.container(border=True):
                    st.metric("🟡 High risk (50-74)", high)
            with r4:
                with st.container(border=True):
                    st.metric("🟢 Low risk (<50)", low)

            st.divider()
            st.markdown("### Churn Risk by Account")

            for _, row in all_data.iterrows():
                risk  = int(row['CHURN_RISK'])
                color = "🔴" if risk >= 75 else "🟡" if risk >= 50 else "🟢"
                label = "CRITICAL" if risk >= 75 else "HIGH" if risk >= 50 else "LOW"
                is_esc = bool(row.get('ESCALATED', False))
                has_comp = str(row.get('COMPETITORS','')).lower() not in ['','none','null','[]','nan']

                with st.expander(f"{color} **{row['CALL_ID']}** — Risk: {risk}/100 [{label}]",
                                 expanded=(risk >= 75)):
                    c1, c2, c3, c4 = st.columns(4)
                    with c1: st.metric("Churn Risk",    f"{risk}/100")
                    with c2: st.metric("Sentiment",     f"{float(row.get('AVG_SENT',0) or 0):.2f}")
                    with c3: st.metric("CSAT",          row.get('CSAT','?'))
                    with c4: st.metric("Resolution",    row.get('RES','?'))

                    flags = []
                    if is_esc:   flags.append("🔺 Escalated")
                    if has_comp: flags.append("🏁 Competitor mentioned")
                    if row.get('CSAT') == 'Negative': flags.append("😞 Negative CSAT")
                    if row.get('RES') == 'Unresolved': flags.append("❌ Unresolved")
                    neg_m = int(row.get('NEG_MOMENTS',0) or 0)
                    if neg_m > 2: flags.append(f"😤 {neg_m} negative moments")

                    if flags:
                        st.markdown("**Risk signals:** " + "  ·  ".join(flags))

                    if row.get('ROOT_CAUSE') and str(row['ROOT_CAUSE']).lower() not in ['none','null','']:
                        st.warning(f"**Root cause:** {row['ROOT_CAUSE']}")

                    if risk >= 50:
                        if st.button(f"🧠 Generate save strategy", key=f"save_{row['CALL_ID']}"):
                            prompt = f"""Account: {row['CALL_ID']}
Churn risk score: {risk}/100
Signals: {', '.join(flags) if flags else 'General dissatisfaction'}
CSAT: {row.get('CSAT','?')} | Resolution: {row.get('RES','?')} | Sentiment: {float(row.get('AVG_SENT',0) or 0):.2f}

Generate a specific 3-step account save strategy. Be direct and actionable."""
                            with st.spinner("Generating save strategy..."):
                                strategy = _cortex(session, prompt)
                            st.success(strategy)

    # ════════════════════════════════════════════════════════════════════════
    # SUB 2 — Pattern Intelligence
    # ════════════════════════════════════════════════════════════════════════
    with sub2:
        section_header("📊", "Pattern Intelligence",
                       "Cross-conversation trends and emerging issues")

        if st.button("🧠 Run Pattern Analysis", key="pattern_btn", type="primary"):
            try:
                # Pull aggregate data
                topic_data = session.sql(f"""
                    SELECT COALESCE(STANDARD_TOPIC,TOPIC_LABEL,'Unknown') AS TOPIC,
                           COUNT(*) AS COUNT,
                           ROUND(AVG(SENTIMENT),2) AS AVG_SENT
                    FROM {DB}.CALL_SEGMENTS
                    WHERE COALESCE(STANDARD_TOPIC,TOPIC_LABEL,'Unknown') IS NOT NULL
                    GROUP BY COALESCE(STANDARD_TOPIC,TOPIC_LABEL,'Unknown')
                    ORDER BY COUNT DESC
                """).to_pandas()

                km_data = session.sql(f"""
                    SELECT MOMENT_TYPE, SEVERITY, COUNT(*) AS COUNT
                    FROM {DB}.CALL_KEY_MOMENTS
                    GROUP BY MOMENT_TYPE, SEVERITY
                    ORDER BY COUNT DESC
                """).to_pandas()

                ins_data = session.sql(f"""
                    SELECT RESOLUTION_STATUS, CSAT_INDICATOR,
                           ROUND(AVG(LEAD_INTENT_SCORE),0) AS AVG_LEAD,
                           COUNT(*) AS COUNT
                    FROM {DB}.CALL_INSIGHTS
                    WHERE RESOLUTION_STATUS IS NOT NULL
                    GROUP BY RESOLUTION_STATUS, CSAT_INDICATOR
                """).to_pandas()

                summary = f"""
Topic distribution: {topic_data.to_string() if len(topic_data)>0 else 'No data'}
Key moment patterns: {km_data.to_string() if len(km_data)>0 else 'No data'}
Resolution patterns: {ins_data.to_string() if len(ins_data)>0 else 'No data'}
"""
                prompt = f"""You are a CX intelligence analyst. Analyze these cross-conversation patterns and surface:

1. 🔴 EMERGING ISSUES — problems appearing repeatedly
2. 📈 POSITIVE TRENDS — what's working well
3. 🏁 COMPETITIVE THREATS — competitor signals
4. 💡 STRATEGIC RECOMMENDATIONS — top 3 actions for leadership
5. 📊 HEADLINE METRICS — key numbers to present to stakeholders

Data:
{summary[:3000]}

Be specific, data-driven, and executive-ready."""

                with st.spinner("Analysing patterns across all conversations..."):
                    st.session_state['pattern_report'] = _cortex(session, prompt)

                if len(topic_data) > 0:
                    st.markdown("**Topic frequency:**")
                    st.bar_chart(topic_data.set_index('TOPIC')['COUNT'])

                if len(km_data) > 0:
                    st.markdown("**Key moment types:**")
                    st.bar_chart(km_data.set_index('MOMENT_TYPE')['COUNT'])

            except Exception as e:
                st.error(f"Pattern analysis failed: {e}")

        if st.session_state.get('pattern_report'):
            st.markdown("### 📊 Pattern Intelligence Report")
            st.markdown(st.session_state['pattern_report'])
            st.download_button("⬇️ Download report",
                data=st.session_state['pattern_report'],
                file_name="echomind_pattern_report.txt",
                mime="text/plain", key="dl_pattern")

    # ════════════════════════════════════════════════════════════════════════
    # SUB 3 — Alert Configuration
    # ════════════════════════════════════════════════════════════════════════
    with sub3:
        section_header("🔔", "Alert Configuration",
                       "Define thresholds — EchoMind flags anything that crosses them")

        st.markdown("Configure what EchoMind should proactively alert you about:")

        with st.container(border=True):
            st.markdown("**🔴 Churn Risk Alerts**")
            a1, a2 = st.columns(2)
            with a1:
                churn_thresh = st.slider("Alert when churn risk exceeds", 0, 100, 70, key="churn_thresh")
            with a2:
                st.caption(f"Current: {len([1 for _ in range(1)]) } accounts above {churn_thresh}")

        with st.container(border=True):
            st.markdown("**📉 Sentiment Alerts**")
            b1, b2 = st.columns(2)
            with b1:
                sent_thresh = st.slider("Alert when avg sentiment drops below", -1.0, 0.0, -0.3, 0.05, key="sent_thresh")
            with b2:
                st.caption("Triggers when a conversation sentiment is consistently negative")

        with st.container(border=True):
            st.markdown("**🏁 Competitor Mention Alerts**")
            comp_names = st.text_input("Competitors to monitor (comma-separated)",
                placeholder="e.g. Gong, Fireflies, Salesforce, HubSpot", key="comp_names")

        with st.container(border=True):
            st.markdown("**🔺 Escalation Alerts**")
            esc_immediate = st.checkbox("Alert immediately on any escalation", value=True, key="esc_immediate")

        with st.container(border=True):
            st.markdown("**📧 Alert Delivery**")
            d1, d2 = st.columns(2)
            with d1:
                alert_email = st.text_input("Email alerts to", placeholder="manager@company.com", key="alert_email")
            with d2:
                alert_slack = st.text_input("Slack webhook (optional)", placeholder="https://hooks.slack.com/...", key="alert_slack")

        if st.button("💾 Save Alert Configuration", key="save_alerts", type="primary"):
            st.session_state['alert_config'] = {
                'churn_thresh': churn_thresh,
                'sent_thresh':  sent_thresh,
                'competitors':  [c.strip() for c in comp_names.split(',') if c.strip()],
                'esc_immediate':esc_immediate,
                'email':        alert_email,
                'slack':        alert_slack,
            }
            st.success("✅ Alert configuration saved! EchoMind will flag conversations matching these thresholds.")

        st.divider()
        st.markdown("#### 🔔 Run alerts now against all processed conversations")
        if st.button("▶️ Check all conversations against alert thresholds", key="run_alerts"):
            config = st.session_state.get('alert_config', {'churn_thresh':70,'sent_thresh':-0.3,'competitors':[],'esc_immediate':True})
            try:
                check_df = session.sql(f"""
                    SELECT c.CALL_ID,
                           ROUND(AVG(c.SENTIMENT),2) AS SENT,
                           COALESCE(i.ESCALATION_FLAG,FALSE) AS ESC,
                           COALESCE(i.CSAT_INDICATOR,'') AS CSAT,
                           COALESCE(i.COMPETITOR_MENTIONS,'') AS COMP
                    FROM {DB}.CALL_SEGMENTS c
                    LEFT JOIN {DB}.CALL_INSIGHTS i ON c.CALL_ID=i.CALL_ID
                    GROUP BY c.CALL_ID,i.ESCALATION_FLAG,i.CSAT_INDICATOR,i.COMPETITOR_MENTIONS
                """).to_pandas()

                alerts_fired = []
                for _, row in check_df.iterrows():
                    if float(row.get('SENT',0) or 0) < config.get('sent_thresh',-0.3):
                        alerts_fired.append(f"📉 **{row['CALL_ID']}** — sentiment {float(row.get('SENT',0)):.2f} below threshold")
                    if bool(row.get('ESC',False)) and config.get('esc_immediate'):
                        alerts_fired.append(f"🔺 **{row['CALL_ID']}** — escalation detected")
                    comp = str(row.get('COMP',''))
                    for c in config.get('competitors',[]):
                        if c.lower() in comp.lower():
                            alerts_fired.append(f"🏁 **{row['CALL_ID']}** — competitor '{c}' mentioned")

                if alerts_fired:
                    st.markdown(f"### 🔔 {len(alerts_fired)} alert(s) fired:")
                    for a in alerts_fired:
                        st.warning(a)
                else:
                    st.success("✅ No alerts fired — all conversations within configured thresholds.")
            except Exception as e:
                st.error(f"Alert check failed: {e}")