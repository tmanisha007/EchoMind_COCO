import streamlit as st
from utils import DB, _cortex, require_call, section_header, _default_index
from collections import Counter

def render(session):
    if not require_call("Intelligence"):
        return

    # ── Sub-tabs ─────────────────────────────────────────────────────────────
    sub1, sub2, sub3 = st.tabs([
        "🗣️ Speaker Dynamics",
        "💡 Coaching Tips",
        "🤖 AI Summary",
    ])

    # ════════════════════════════════════════════════════════════════════════
    # SUB 1 — Speaker Dynamics
    # ════════════════════════════════════════════════════════════════════════
    with sub1:
        section_header("🗣️", "Speaker Dynamics", "Agent vs Customer talk ratio, interruptions, listening score")

        sd_calls = session.sql(f"SELECT DISTINCT CALL_ID FROM {DB}.CALL_SEGMENTS ORDER BY CALL_ID").to_pandas()
        _ids = sd_calls['CALL_ID'].tolist()
        sel_sd = st.selectbox("Select call", _ids, index=_default_index(_ids), key="sd_call")
        sd_seg = session.sql(f"SELECT * FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{sel_sd}' ORDER BY START_TIME").to_pandas()

        has_roles = 'SPEAKER_ROLE' in sd_seg.columns and sd_seg['SPEAKER_ROLE'].notna().any()
        role_col  = 'SPEAKER_ROLE' if has_roles else 'SPEAKER'

        if not has_roles:
            st.warning("⚠️ Speaker roles not mapped yet. Re-analyze this call to enable full Agent/Customer analytics.")

        sd_seg['dur'] = sd_seg['END_TIME'] - sd_seg['START_TIME']
        speakers      = sd_seg[role_col].dropna().unique().tolist()

        if len(speakers) > 0:
            talk_time  = sd_seg.groupby(role_col)['dur'].sum()
            total_time = talk_time.sum()

            # Talk time cards
            st.markdown("**Talk time breakdown:**")
            cols = st.columns(len(speakers))
            for i, spk in enumerate(speakers):
                with cols[i]:
                    pct  = (talk_time.get(spk,0)/total_time*100) if total_time > 0 else 0
                    icon = "🔵" if spk=='Agent' else "🟢" if spk=='Customer' else "⚪"
                    bg   = "#dbeafe" if spk=='Agent' else "#dcfce7" if spk=='Customer' else "#f1f5f9"
                    tc   = "#1e40af" if spk=='Agent' else "#166534" if spk=='Customer' else "#334155"
                    st.markdown(f"""
                    <div style='background:{bg};border-radius:12px;padding:16px;text-align:center;'>
                        <div style='font-size:28px;'>{icon}</div>
                        <div style='font-weight:700;color:{tc};margin-top:4px;'>{spk}</div>
                        <div style='font-size:26px;font-weight:800;color:{tc};'>{pct:.1f}%</div>
                        <div style='color:#64748b;font-size:12px;'>{talk_time.get(spk,0):.0f}s</div>
                    </div>
                    """, unsafe_allow_html=True)

            # Listening score
            if has_roles and 'Agent' in speakers:
                agent_pct = talk_time.get('Agent',0)/total_time*100 if total_time > 0 else 50
                ls        = max(0, min(100, int(100-abs(agent_pct-40)*2)))
                ls_color  = "#22c55e" if ls >= 70 else "#f59e0b" if ls >= 40 else "#ef4444"
                st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
                st.markdown(f"""
                <div style='background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:16px 20px;'>
                    <div style='font-weight:700;font-size:14px;margin-bottom:8px;'>🎧 Agent Listening Score</div>
                    <div style='background:#e2e8f0;border-radius:99px;height:12px;'>
                        <div style='background:{ls_color};width:{ls}%;height:12px;border-radius:99px;'></div>
                    </div>
                    <div style='margin-top:6px;color:#64748b;font-size:13px;'>
                        Score: <strong style='color:{ls_color};'>{ls}/100</strong>
                        &nbsp;·&nbsp; Agent talk: {agent_pct:.0f}%
                        &nbsp;·&nbsp; Ideal: ~40%
                    </div>
                </div>
                """, unsafe_allow_html=True)

            # Longest monologue
            st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
            st.markdown("**Longest monologue per speaker:**")
            for spk in speakers:
                spk_segs = sd_seg[sd_seg[role_col]==spk].copy()
                if len(spk_segs) > 0:
                    longest = spk_segs.loc[spk_segs['dur'].idxmax()]
                    mm = int(longest['START_TIME']//60)
                    ss = int(longest['START_TIME']%60)
                    icon = "🔵" if spk=='Agent' else "🟢" if spk=='Customer' else "⚪"
                    with st.expander(f"{icon} {spk} — longest: {longest['dur']:.1f}s at {mm:02d}:{ss:02d}"):
                        st.write(longest['SEGMENT_TEXT'])

            # Turn taking
            st.markdown("**Turn-taking patterns:**")
            transitions = []
            for i in range(1, len(sd_seg)):
                if sd_seg.iloc[i][role_col] != sd_seg.iloc[i-1][role_col]:
                    gap = sd_seg.iloc[i]['START_TIME'] - sd_seg.iloc[i-1]['END_TIME']
                    transitions.append({'from':sd_seg.iloc[i-1][role_col],'to':sd_seg.iloc[i][role_col],'gap':gap})

            t1,t2,t3 = st.columns(3)
            interruptions = [t for t in transitions if t['gap'] < 0]
            avg_gap       = sum(t['gap'] for t in transitions)/len(transitions) if transitions else 0
            with t1:
                with st.container(border=True): st.metric("Total turns",    len(transitions))
            with t2:
                with st.container(border=True): st.metric("Avg gap",        f"{avg_gap:.1f}s")
            with t3:
                with st.container(border=True): st.metric("Interruptions",  len(interruptions))

            if transitions:
                quick = [t for t in transitions if 0 <= t['gap'] < 1.0]
                if quick:        st.caption(f"⚡ {len(quick)} quick responses (<1s)")
                if interruptions: st.caption(f"🚫 {len(interruptions)} overlaps detected")

            # Repetition
            if has_roles:
                st.markdown("**Agent repetition detection:**")
                agent_segs = sd_seg[sd_seg[role_col]=='Agent']['SEGMENT_TEXT'].tolist()
                if len(agent_segs) > 2:
                    words    = ' '.join(agent_segs).lower().split()
                    trigrams = [' '.join(words[j:j+3]) for j in range(len(words)-2)]
                    repeated = [(p,c) for p,c in Counter(trigrams).most_common(5) if c > 2]
                    if repeated:
                        for p, c in repeated:
                            st.markdown(f"""
                            <div style='background:#fefce8;border:1px solid #fde68a;border-radius:8px;
                                        padding:8px 14px;margin-bottom:6px;font-size:13px;'>
                                🔁 <strong>"{p}"</strong> repeated <strong>{c}x</strong>
                            </div>
                            """, unsafe_allow_html=True)
                    else:
                        st.success("✅ No excessive repetition detected")

            st.markdown("**Segments per speaker:**")
            st.bar_chart(sd_seg[role_col].value_counts())

    # ════════════════════════════════════════════════════════════════════════
    # SUB 2 — Coaching Tips
    # ════════════════════════════════════════════════════════════════════════
    with sub2:
        section_header("💡", "Coaching Tips", "AI-powered agent coaching based on call behaviour")

        ct_calls = session.sql(f"SELECT DISTINCT CALL_ID FROM {DB}.CALL_SEGMENTS ORDER BY CALL_ID").to_pandas()
        _ids = ct_calls['CALL_ID'].tolist()
        sel_ct = st.selectbox("Select call", _ids, index=_default_index(_ids), key="ct_call")

        if st.button("🎯 Generate coaching tips", key="gen_coaching", type="primary"):
            ct_seg = session.sql(
                f"SELECT COALESCE(SPEAKER_ROLE,SPEAKER) AS SPK, SEGMENT_TEXT, SENTIMENT "
                f"FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{sel_ct}' ORDER BY START_TIME"
            ).to_pandas()
            lines = [f"{r['SPK']} (sent:{r['SENTIMENT']:.2f}): {r['SEGMENT_TEXT']}" for _, r in ct_seg.iterrows()]
            tips  = _cortex(session,
                f"You are a senior call center coach. Analyze this call and provide exactly 5 specific, "
                f"actionable coaching tips for the agent. For each tip: state the issue, the impact, "
                f"and the exact recommended action or script change.\n\nCall:\n" + "\n".join(lines[:40])
            )
            st.session_state[f'coaching_{sel_ct}'] = tips

        if st.session_state.get(f'coaching_{sel_ct}'):
            st.markdown(f"""
            <div style='background:#f0f9ff;border:1px solid #bae6fd;border-radius:12px;
                        padding:20px 24px;'>
                {st.session_state[f'coaching_{sel_ct}']}
            </div>
            """, unsafe_allow_html=True)

    # ════════════════════════════════════════════════════════════════════════
    # SUB 3 — AI Summary
    # ════════════════════════════════════════════════════════════════════════
    with sub3:
        section_header("🤖", "AI Summary", "Executive-level call summary in bullet points")

        sm_calls = session.sql(f"SELECT DISTINCT CALL_ID FROM {DB}.CALL_SEGMENTS ORDER BY CALL_ID").to_pandas()
        _ids = sm_calls['CALL_ID'].tolist()
        sel_sm = st.selectbox("Select call", _ids, index=_default_index(_ids), key="sm_call")

        if st.button("📋 Generate summary", key="gen_summary", type="primary"):
            sm_seg = session.sql(
                f"SELECT COALESCE(SPEAKER_ROLE,SPEAKER) AS SPK, SEGMENT_TEXT "
                f"FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{sel_sm}' ORDER BY START_TIME"
            ).to_pandas()
            tx_lines = [f"{r['SPK']}: {r['SEGMENT_TEXT']}" for _, r in sm_seg.iterrows()]
            summary  = _cortex(session,
                f"Provide a concise executive summary of this call in 3-5 bullet points. "
                f"Include: purpose, key discussion points, outcome, and any follow-up needed.\n\n"
                f"Transcript:\n" + "\n".join(tx_lines[:50])
            )
            st.session_state[f'ai_summary_{sel_sm}'] = summary

        if st.session_state.get(f'ai_summary_{sel_sm}'):
            st.markdown(f"""
            <div style='background:#fafafa;border:1px solid #e2e8f0;border-radius:12px;
                        padding:20px 24px;'>
                {st.session_state[f'ai_summary_{sel_sm}']}
            </div>
            """, unsafe_allow_html=True)
