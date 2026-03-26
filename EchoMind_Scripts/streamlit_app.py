import streamlit as st
from snowflake.snowpark.context import get_active_session
from utils import init_session_state

import tab_upload
import tab_dashboard
import tab_transcript
import tab_analytics
import tab_intelligence
import tab_scorecard
import tab_actions
import tab_advanced
import tab_pitchdeck
import tab_deals
import tab_alerts
import tab_pii
import tab_multilang

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(page_title="EchoMind", page_icon="🎧", layout="wide")

# ── Custom CSS — executive UI ─────────────────────────────────────────────────
st.markdown("""
<style>
    /* Global font */
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

    /* Hide default streamlit menu & footer */
    #MainMenu { visibility: hidden; }
    footer    { visibility: hidden; }

    /* Cleaner tab styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 4px;
        background: #f1f5f9;
        border-radius: 10px;
        padding: 4px;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px;
        padding: 8px 16px;
        font-weight: 600;
        font-size: 13px;
        color: #64748b;
    }
    .stTabs [aria-selected="true"] {
        background: #fff !important;
        color: #1e40af !important;
        box-shadow: 0 1px 4px rgba(0,0,0,0.1);
    }

    /* Metric cards */
    [data-testid="metric-container"] {
        background: #fafafa;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 12px !important;
    }

    /* Buttons */
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #1d4ed8, #2563eb);
        color: #fff;
        border: none;
        border-radius: 8px;
        font-weight: 600;
        padding: 8px 20px;
    }
    .stButton > button[kind="primary"]:hover {
        background: linear-gradient(135deg, #1e40af, #1d4ed8);
    }

    /* Expander */
    .streamlit-expanderHeader {
        font-weight: 600;
        font-size: 14px;
    }

    /* Divider */
    hr { border-color: #f1f5f9; }

    /* Scrollbar */
    ::-webkit-scrollbar { width: 6px; }
    ::-webkit-scrollbar-track { background: #f1f5f9; }
    ::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 3px; }
</style>
""", unsafe_allow_html=True)

# ── Session ──────────────────────────────────────────────────────────────────
session = get_active_session()
init_session_state()

# ── Top header bar ───────────────────────────────────────────────────────────
header_left, header_right = st.columns([3, 2])
with header_left:
    st.markdown("""
    <div style='display:flex;align-items:center;gap:12px;padding:4px 0;'>
        <span style='font-size:28px;'>🎧</span>
        <div>
            <div style='font-size:22px;font-weight:800;color:#0f172a;letter-spacing:-0.5px;'>EchoMind</div>
            <div style='font-size:12px;color:#64748b;'>AI-Powered Call Analytics · Snowflake Cortex AI</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

with header_right:
    right_logo, right_info = st.columns([1, 3])
    with right_logo:
        try:
            with open("/opt/streamlit-runtime/kipi_logo.png", "rb") as f:
                st.image(f.read(), width=80)
        except Exception:
            st.markdown("**kipi**")
    with right_info:
        if st.session_state.get('last_call_id'):
            st.markdown(f"""
            <div style='background:#eff6ff;border:1px solid #bfdbfe;border-radius:10px;
                        padding:10px 16px;text-align:right;'>
                <div style='font-size:11px;color:#3b82f6;font-weight:700;text-transform:uppercase;
                            letter-spacing:0.5px;'>Active Call</div>
                <div style='font-size:14px;font-weight:700;color:#1e40af;'>
                    📞 {st.session_state['last_call_id']}
                </div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown("""
            <div style='background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;
                        padding:10px 16px;text-align:right;'>
                <div style='color:#94a3b8;font-size:13px;'>No call loaded · Upload to begin</div>
            </div>
            """, unsafe_allow_html=True)

st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

# ── Main tabs ────────────────────────────────────────────────────────────────
(t_upload, t_dashboard, t_transcript,
 t_analytics, t_intelligence,
 t_scorecard, t_actions, t_advanced,
 t_deals, t_alerts, t_pii, t_multilang,
 t_pitch) = st.tabs([
    "📤 Upload & Process",
    "📊 Call Dashboard",
    "📜 Transcript",
    "📈 Analytics",
    "🧠 Intelligence",
    "📋 Scorecard & Coaching",
    "⚡ Actions",
    "⚙️ Advanced",
    "🏆 Deal Intelligence",
    "🚨 Churn & Alerts",
    "🔒 PII & Compliance",
    "🌍 Multi-Language",
    "🎬 Pitch Deck",
])

with t_upload:      tab_upload.render(session)
with t_dashboard:   tab_dashboard.render(session)
with t_transcript:  tab_transcript.render(session)
with t_analytics:   tab_analytics.render(session)
with t_intelligence:tab_intelligence.render(session)
with t_scorecard:   tab_scorecard.render(session)
with t_actions:     tab_actions.render(session)
with t_advanced:    tab_advanced.render(session)
with t_deals:       tab_deals.render(session)
with t_alerts:      tab_alerts.render(session)
with t_pii:         tab_pii.render(session)
with t_multilang:   tab_multilang.render(session)
with t_pitch:       tab_pitchdeck.render(session)

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("""
<div style='text-align:center;color:#94a3b8;font-size:12px;margin-top:40px;padding:16px;
            border-top:1px solid #f1f5f9;'>
    🎧 EchoMind · Built for Cocothon · Powered by Snowflake Cortex AI ❄️
</div>
""", unsafe_allow_html=True)