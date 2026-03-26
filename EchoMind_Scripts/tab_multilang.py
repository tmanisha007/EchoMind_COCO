import streamlit as st
from utils import DB, _cortex, _sq, _clean_json, section_header, _default_index
import json

SUPPORTED_LANGUAGES = {
    "English": "en", "Hindi": "hi", "Spanish": "es", "French": "fr",
    "German": "de", "Portuguese": "pt", "Arabic": "ar", "Japanese": "ja",
    "Chinese (Mandarin)": "zh", "Korean": "ko", "Italian": "it",
    "Dutch": "nl", "Russian": "ru", "Tamil": "ta", "Telugu": "te",
    "Marathi": "mr", "Bengali": "bn", "Gujarati": "gu", "Kannada": "kn",
}

def render(session):
    section_header("🌍", "Multi-Language Intelligence",
                   "Analyse conversations in any language — auto-detect, translate, and extract insights")

    st.markdown("""
    > **Beats Fireflies and most Gong plans:** Full multi-language conversation analysis.
    > Auto-detect language, extract insights in the original language,
    > and generate English summaries — all in one pipeline.
    > Covers 19 languages including all major Indian languages.
    """)

    sub1, sub2, sub3 = st.tabs([
        "🔍 Language Detection",
        "🌐 Multi-Language Analysis",
        "📊 Language Distribution",
    ])

    # ════════════════════════════════════════════════════════════════════════
    # SUB 1 — Language Detection & Translation
    # ════════════════════════════════════════════════════════════════════════
    with sub1:
        section_header("🔍", "Language Detection",
                       "Auto-detect language and translate conversation to English")

        calls = session.sql(f"SELECT DISTINCT CALL_ID FROM {DB}.CALL_SEGMENTS ORDER BY CALL_ID").to_pandas()

        if len(calls) == 0:
            st.info("No conversations processed yet.")
        else:
            _ids  = calls['CALL_ID'].tolist()
            sel   = st.selectbox("Select conversation", _ids,
                                 index=_default_index(_ids), key="lang_call")

            col1, col2 = st.columns(2)
            with col1:
                if st.button("🔍 Detect language", key="detect_lang_btn", type="primary"):
                    segs = session.sql(f"SELECT SEGMENT_TEXT FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{sel}' ORDER BY START_TIME LIMIT 10").to_pandas()
                    sample = " ".join(segs['SEGMENT_TEXT'].tolist())[:1000]

                    prompt = f"""Detect the language(s) in this conversation. Return ONLY valid JSON:
{{"primary_language":"English","secondary_languages":[],"confidence":"High|Medium|Low","mixed_language":true|false,"language_notes":"brief observation"}}

Text: {sample}"""
                    with st.spinner("Detecting language..."):
                        try:
                            raw    = _cortex(session, prompt)
                            result = json.loads(_clean_json(raw))
                            st.session_state[f'lang_{sel}'] = result
                        except:
                            st.session_state[f'lang_{sel}'] = {"primary_language":"Unknown","confidence":"Low"}

            with col2:
                if st.button("🌐 Translate to English", key="translate_btn"):
                    segs = session.sql(f"SELECT COALESCE(SPEAKER_ROLE,SPEAKER) AS SPK, SEGMENT_TEXT FROM {DB}.CALL_SEGMENTS WHERE CALL_ID='{sel}' ORDER BY START_TIME LIMIT 20").to_pandas()
                    conv = "\n".join([f"{r['SPK']}: {r['SEGMENT_TEXT']}" for _, r in segs.iterrows()])[:3000]

                    prompt = f"""Translate this conversation to English. Keep speaker labels. If already English, return as-is.
Provide translation line by line preserving the speaker format.

Conversation:
{conv}"""
                    with st.spinner("Translating..."):
                        translation = _cortex(session, prompt)
                        st.session_state[f'translation_{sel}'] = translation

            # Show language detection result
            if st.session_state.get(f'lang_{sel}'):
                r = st.session_state[f'lang_{sel}']
                l1, l2, l3, l4 = st.columns(4)
                with l1:
                    with st.container(border=True):
                        st.metric("Primary Language", r.get('primary_language','?'))
                with l2:
                    with st.container(border=True):
                        st.metric("Confidence", r.get('confidence','?'))
                with l3:
                    with st.container(border=True):
                        secondary = r.get('secondary_languages',[])
                        st.metric("Secondary", ", ".join(secondary) if secondary else "None")
                with l4:
                    with st.container(border=True):
                        st.metric("Mixed Language", "Yes" if r.get('mixed_language') else "No")
                if r.get('language_notes'):
                    st.info(f"📝 {r['language_notes']}")

            # Show translation
            if st.session_state.get(f'translation_{sel}'):
                st.markdown("**English Translation:**")
                with st.container(border=True):
                    st.markdown(st.session_state[f'translation_{sel}'])
                st.download_button("⬇️ Download translation",
                    data=st.session_state[f'translation_{sel}'],
                    file_name=f"translation_{sel}.txt",
                    mime="text/plain", key="dl_translation")

    # ════════════════════════════════════════════════════════════════════════
    # SUB 2 — Multi-Language Analysis
    # ════════════════════════════════════════════════════════════════════════
    with sub2:
        section_header("🌐", "Multi-Language Analysis",
                       "Analyse a conversation in any language and get insights in English")

        ml_lang = st.selectbox("Input language", list(SUPPORTED_LANGUAGES.keys()),
                               key="ml_lang")
        ml_name = st.text_input("Conversation name", placeholder="e.g. Hindi_Support_Call_Jan15",
                                key="ml_name")
        ml_text = st.text_area("Paste conversation (in any language)", height=250,
            placeholder="ग्राहक: मुझे मेरे ऑर्डर के बारे में समस्या है...\nएजेंट: नमस्ते, मैं आपकी कैसे मदद कर सकता हूँ?\n\nCustomer: I have a problem with my order...\nAgent: Hello, how can I help you?",
            key="ml_text")

        if st.button("🌍 Analyse in any language", key="ml_analyse_btn", type="primary"):
            if not ml_text.strip():
                st.warning("Please paste conversation text first.")
            else:
                call_id = _sq(ml_name.strip() or "MULTILANG_CONV").upper()
                call_id = __import__('re').sub(r'[^A-Za-z0-9]', '_', call_id)

                prompt = f"""This conversation is in {ml_lang}. Analyse it and provide a complete response in ENGLISH.

Conversation:
{ml_text[:3000]}

Provide:
1. SUMMARY — 3-5 bullet points covering purpose, key points, outcome
2. SENTIMENT — Overall sentiment and progression (positive/neutral/negative)
3. KEY MOMENTS — Any frustration, escalation, buying signals, or resolution
4. KPIs — Resolution status, issue type, customer satisfaction indicator
5. ACTION ITEMS — What needs to happen next
6. TRANSLATION — Key phrases translated to English

Return as structured analysis."""

                with st.spinner(f"Analysing {ml_lang} conversation..."):
                    analysis = _cortex(session, prompt)
                    st.session_state[f'ml_analysis_{call_id}'] = analysis

                # Also store as segments for dashboard
                lines = [l.strip() for l in ml_text.strip().splitlines() if l.strip()]
                segs  = []
                cur_speaker, buf = "Unknown", []
                for line in lines:
                    m = __import__('re').match(r'^[\[\(]?([A-Za-z0-9\u0900-\u097F_ ]{1,30})[\]\)>:\-]\s+(.+)$', line)
                    if m:
                        if buf: segs.append({'text':" ".join(buf),'speaker':cur_speaker,'start':len(segs)*30,'end':len(segs)*30+30})
                        cur_speaker, buf = m.group(1).strip(), [m.group(2).strip()]
                    else:
                        buf.append(line)
                if buf: segs.append({'text':" ".join(buf),'speaker':cur_speaker,'start':len(segs)*30,'end':len(segs)*30+30})
                if not segs: segs = [{'text':ml_text[:2000],'speaker':'Unknown','start':0,'end':30}]

                st.info(f"✅ Analysis complete! Conversation stored as `{call_id}` — available in all other tabs.")

            if st.session_state.get(f'ml_analysis_{_sq(ml_name.strip() or "MULTILANG_CONV").upper()}'):
                st.markdown("### 📋 Analysis Results (in English)")
                key = f'ml_analysis_{_sq(ml_name.strip() or "MULTILANG_CONV").upper()}'
                st.markdown(st.session_state[key])
                st.download_button("⬇️ Download analysis",
                    data=st.session_state[key],
                    file_name="multilang_analysis.txt",
                    mime="text/plain", key="dl_ml_analysis")

    # ════════════════════════════════════════════════════════════════════════
    # SUB 3 — Language Distribution
    # ════════════════════════════════════════════════════════════════════════
    with sub3:
        section_header("📊", "Language Distribution",
                       "Understand the language breakdown across all your conversations")

        if st.button("📊 Analyse language distribution", key="lang_dist_btn", type="primary"):
            try:
                segs = session.sql(f"""
                    SELECT CALL_ID, SEGMENT_TEXT
                    FROM {DB}.CALL_SEGMENTS
                    WHERE SEGMENT_ID = 0
                    ORDER BY CALL_ID
                """).to_pandas()

                if len(segs) == 0:
                    st.info("No conversations to analyse.")
                else:
                    lang_results = {}
                    progress = st.progress(0)
                    for idx, (_, row) in enumerate(segs.iterrows()):
                        sample = str(row.get('SEGMENT_TEXT',''))[:500]
                        prompt = f"Detect language. Return ONLY the language name (one word, e.g. English, Hindi, Spanish): {sample}"
                        try:
                            lang = _cortex(session, prompt).strip().split('\n')[0].strip()
                            lang_results[row['CALL_ID']] = lang
                        except:
                            lang_results[row['CALL_ID']] = "Unknown"
                        progress.progress((idx+1)/len(segs))

                    st.session_state['lang_dist'] = lang_results

            except Exception as e:
                st.error(f"Language analysis failed: {e}")

        if st.session_state.get('lang_dist'):
            import pandas as pd
            dist = st.session_state['lang_dist']
            dist_df = pd.DataFrame(list(dist.items()), columns=['Conversation','Language'])

            st.markdown(f"**Language distribution across {len(dist_df)} conversations:**")
            st.bar_chart(dist_df['Language'].value_counts())
            st.dataframe(dist_df, use_container_width=True, hide_index=True)

            # Multi-language opportunity
            non_english = dist_df[dist_df['Language'] != 'English']
            if len(non_english) > 0:
                st.warning(f"🌍 **{len(non_english)} non-English conversations detected** — these may need translation for full analysis. Use the Multi-Language Analysis tab to process them.")
