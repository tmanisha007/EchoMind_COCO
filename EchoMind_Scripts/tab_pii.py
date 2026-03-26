import streamlit as st
import re
from utils import DB, _cortex, _sq, _clean_json, section_header
import json

# ── PII patterns ──────────────────────────────────────────────────────────────
PII_PATTERNS = {
    "Credit Card":     (r'\b(?:\d[ -]?){13,16}\b', "****-****-****-****"),
    "SSN":             (r'\b\d{3}-\d{2}-\d{4}\b', "***-**-****"),
    "Email":           (r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', "[EMAIL REDACTED]"),
    "Phone (US)":      (r'\b(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b', "[PHONE REDACTED]"),
    "Phone (IN)":      (r'\b(?:\+91[-.\s]?)?[6-9]\d{9}\b', "[PHONE REDACTED]"),
    "Date of Birth":   (r'\b(?:0?[1-9]|[12]\d|3[01])[\/\-](?:0?[1-9]|1[0-2])[\/\-]\d{2,4}\b', "[DOB REDACTED]"),
    "IP Address":      (r'\b(?:\d{1,3}\.){3}\d{1,3}\b', "[IP REDACTED]"),
    "Passport":        (r'\b[A-Z]{1,2}\d{6,9}\b', "[PASSPORT REDACTED]"),
    "Bank Account":    (r'\b\d{9,18}\b', "[ACCOUNT REDACTED]"),
}

def redact_text(text, selected_types):
    redacted = text
    findings = []
    for pii_type, (pattern, replacement) in PII_PATTERNS.items():
        if pii_type in selected_types:
            matches = re.findall(pattern, redacted)
            if matches:
                findings.append(f"{pii_type}: {len(matches)} instance(s) found")
                redacted = re.sub(pattern, replacement, redacted)
    return redacted, findings


def render(session):
    section_header("🔒", "PII Redaction & Compliance",
                   "Auto-redact sensitive data before storage — enterprise-grade privacy built in")

    st.markdown("""
    > **Enterprise differentiator:** Unlike Gong and Fireflies which process your data on their servers,
    > EchoMind gives you full control. Redact PII **before** it ever enters your Snowflake tables.
    > GDPR · HIPAA · PCI-DSS · SOC2 ready.
    """)

    sub1, sub2, sub3 = st.tabs([
        "🔍 Scan & Redact",
        "🗄️ Audit Existing Data",
        "📋 Compliance Report",
    ])

    # ════════════════════════════════════════════════════════════════════════
    # SUB 1 — Scan & Redact
    # ════════════════════════════════════════════════════════════════════════
    with sub1:
        section_header("🔍", "Scan & Redact", "Test PII redaction on any text before processing")

        st.markdown("**Select PII types to detect and redact:**")
        cols = st.columns(3)
        selected = []
        for i, pii_type in enumerate(PII_PATTERNS.keys()):
            with cols[i % 3]:
                if st.checkbox(pii_type, value=True, key=f"pii_{pii_type}"):
                    selected.append(pii_type)

        test_text = st.text_area("Paste text to scan", height=200,
            placeholder="Customer: Hi, my name is John Smith. My card number is 4532 1234 5678 9012 and my email is john@example.com. My phone is +1 (555) 123-4567. DOB: 15/03/1985",
            key="pii_test_text")

        if st.button("🔍 Scan & Redact", key="scan_btn", type="primary"):
            if not test_text.strip():
                st.warning("Please paste some text to scan.")
            elif not selected:
                st.warning("Please select at least one PII type to detect.")
            else:
                redacted, findings = redact_text(test_text, selected)

                if findings:
                    st.error(f"🚨 **{len(findings)} PII type(s) detected and redacted:**")
                    for f in findings:
                        st.markdown(f"- 🔴 {f}")
                else:
                    st.success("✅ No PII detected in the provided text.")

                col_orig, col_red = st.columns(2)
                with col_orig:
                    st.markdown("**Original (with PII):**")
                    st.text_area("", value=test_text, height=200, key="orig_text", disabled=True)
                with col_red:
                    st.markdown("**Redacted (safe to store):**")
                    st.text_area("", value=redacted, height=200, key="red_text", disabled=True)

                st.download_button("⬇️ Download redacted text",
                    data=redacted, file_name="redacted_text.txt",
                    mime="text/plain", key="dl_redacted")

    # ════════════════════════════════════════════════════════════════════════
    # SUB 2 — Audit Existing Data
    # ════════════════════════════════════════════════════════════════════════
    with sub2:
        section_header("🗄️", "Audit Existing Data",
                       "Scan already-stored conversations for PII")

        st.warning("⚠️ This will scan all stored conversation segments for PII patterns. Results are shown here but NOT automatically modified in the database.")

        audit_types = st.multiselect("PII types to scan for",
            list(PII_PATTERNS.keys()),
            default=["Credit Card","SSN","Email","Phone (US)","Phone (IN)"],
            key="audit_types")

        if st.button("🔍 Audit stored conversations", key="audit_btn", type="primary"):
            try:
                segs = session.sql(f"SELECT CALL_ID, SEGMENT_ID, SEGMENT_TEXT FROM {DB}.CALL_SEGMENTS LIMIT 500").to_pandas()

                if len(segs) == 0:
                    st.info("No segments stored yet.")
                else:
                    pii_found  = []
                    total_segs = len(segs)

                    progress = st.progress(0)
                    for idx, (_, seg) in enumerate(segs.iterrows()):
                        text = str(seg.get('SEGMENT_TEXT',''))
                        _, findings = redact_text(text, audit_types)
                        if findings:
                            pii_found.append({
                                'call_id':    seg['CALL_ID'],
                                'segment_id': seg['SEGMENT_ID'],
                                'findings':   findings
                            })
                        progress.progress((idx+1)/total_segs)

                    st.session_state['audit_results'] = pii_found
                    st.session_state['audit_total']   = total_segs

            except Exception as e:
                st.error(f"Audit failed: {e}")

        if 'audit_results' in st.session_state:
            results = st.session_state['audit_results']
            total   = st.session_state.get('audit_total', 0)

            if results:
                st.error(f"🚨 **PII found in {len(results)} of {total} segments** ({len(results)/total*100:.1f}%)")
                for r in results[:20]:
                    with st.expander(f"⚠️ {r['call_id']} — Segment {r['segment_id']}"):
                        for f in r['findings']:
                            st.markdown(f"- 🔴 {f}")
                        if len(results) > 20:
                            st.caption(f"... and {len(results)-20} more. Download full report below.")

                # Download full audit
                audit_text = f"EchoMind PII Audit Report\n{'='*50}\nTotal segments scanned: {total}\nSegments with PII: {len(results)}\n\n"
                for r in results:
                    audit_text += f"\nCall: {r['call_id']} | Segment: {r['segment_id']}\n"
                    for f in r['findings']:
                        audit_text += f"  - {f}\n"
                st.download_button("⬇️ Download full audit report",
                    data=audit_text, file_name="echomind_pii_audit.txt",
                    mime="text/plain", key="dl_audit")
            else:
                st.success(f"✅ No PII detected across {total} segments.")

    # ════════════════════════════════════════════════════════════════════════
    # SUB 3 — Compliance Report
    # ════════════════════════════════════════════════════════════════════════
    with sub3:
        section_header("📋", "Compliance Report",
                       "Generate a compliance posture report for stakeholders")

        compliance_frameworks = st.multiselect("Applicable frameworks",
            ["GDPR","HIPAA","PCI-DSS","SOC2","CCPA","ISO 27001","India DPDP Act"],
            default=["GDPR","PCI-DSS"], key="comp_frameworks")

        org_name    = st.text_input("Organisation name", placeholder="e.g. Acme Corp", key="org_name")
        data_types  = st.multiselect("Data types processed",
            ["Call recordings","Chat transcripts","Email content","Support tickets",
             "Customer PII","Payment information","Health information"],
            default=["Call recordings","Chat transcripts"], key="data_types")

        if st.button("📋 Generate Compliance Report", key="comp_report_btn", type="primary"):
            prompt = f"""Generate a data privacy and compliance posture report for:

Organisation: {org_name or 'The organisation'}
Applicable frameworks: {', '.join(compliance_frameworks)}
Data types processed: {', '.join(data_types)}
Platform: EchoMind — Snowflake-native conversation intelligence

The platform:
- Processes conversation data (calls, chats, emails, tickets)
- Stores data in Snowflake (customer's own warehouse)
- Uses Snowflake Cortex AI for processing (no external API calls)
- Supports PII redaction before storage
- Provides audit trails via Snowflake query history

Generate a compliance report covering:
1. DATA PROCESSING OVERVIEW — what data is processed and how
2. COMPLIANCE POSTURE — status against each framework
3. DATA RESIDENCY — where data lives and who controls it
4. PII HANDLING — how sensitive data is managed
5. RISKS & MITIGATIONS — key risks and how they're addressed
6. RECOMMENDATIONS — steps to strengthen compliance posture

Format as an executive-ready compliance document."""

            with st.spinner("Generating compliance report..."):
                st.session_state['comp_report'] = _cortex(session, prompt)

        if st.session_state.get('comp_report'):
            st.markdown(st.session_state['comp_report'])
            st.download_button("⬇️ Download compliance report",
                data=st.session_state['comp_report'],
                file_name="echomind_compliance_report.txt",
                mime="text/plain", key="dl_comp")
