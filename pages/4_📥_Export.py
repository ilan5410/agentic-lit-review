"""Page 4: Export — download papers in BibTeX, RIS, CSV, DOCX, and audit trail formats."""
from __future__ import annotations

import json

import streamlit as st

st.set_page_config(page_title="Export", page_icon="📥", layout="wide")

if "pipeline_stage" not in st.session_state:
    st.switch_page("app.py")

from data.database import get_papers, get_log, get_synthesis, count_papers
from data.exporters import (
    papers_to_bibtex,
    papers_to_ris,
    papers_to_dataframe,
    papers_to_docx_bytes,
    build_audit_trail,
)

conn = st.session_state.get("db_conn")
if not conn:
    st.error("No database connection.")
    st.stop()

counts = count_papers(conn)
if counts["total"] == 0:
    st.warning("No papers yet. Run the pipeline first.")
    st.stop()

included = [p for p in get_papers(conn) if p.get("final_status") == "INCLUDED"]
synthesis = get_synthesis(conn)

st.title("📥 Export Results")
st.caption(f"**{len(included)}** papers included · ready to export")

if not included:
    st.info("No included papers to export. Complete the screening stage first.")
    st.stop()

# ── Export options ─────────────────────────────────────────────────────────────

col1, col2 = st.columns(2)

with col1:
    st.subheader("Reference Formats")

    # BibTeX
    bibtex_str = papers_to_bibtex(included)
    st.download_button(
        label="📄 Download BibTeX (.bib)",
        data=bibtex_str,
        file_name="literature_review.bib",
        mime="text/plain",
        use_container_width=True,
    )

    # RIS
    ris_str = papers_to_ris(included)
    st.download_button(
        label="📄 Download RIS (.ris)",
        data=ris_str,
        file_name="literature_review.ris",
        mime="text/plain",
        use_container_width=True,
    )

    st.divider()
    st.subheader("Spreadsheets")

    # CSV
    df = papers_to_dataframe(included)
    csv_bytes = df.to_csv(index=False).encode()
    st.download_button(
        label="📊 Download CSV",
        data=csv_bytes,
        file_name="literature_review.csv",
        mime="text/csv",
        use_container_width=True,
    )

    # Excel
    import io
    excel_buf = io.BytesIO()
    df.to_excel(excel_buf, index=False, engine="openpyxl")
    st.download_button(
        label="📊 Download Excel (.xlsx)",
        data=excel_buf.getvalue(),
        file_name="literature_review.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

with col2:
    st.subheader("Reports")

    # DOCX narrative report
    try:
        docx_bytes = papers_to_docx_bytes(included, synthesis)
        st.download_button(
            label="📝 Download Narrative Report (.docx)",
            data=docx_bytes,
            file_name="literature_review_report.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True,
        )
    except Exception as e:
        st.warning(f"DOCX export unavailable: {e}")

    # Synthesis JSON
    if synthesis:
        synthesis_json = json.dumps(synthesis, indent=2, default=str)
        st.download_button(
            label="🧠 Download Synthesis (JSON)",
            data=synthesis_json,
            file_name="synthesis.json",
            mime="application/json",
            use_container_width=True,
        )

    st.divider()
    st.subheader("Audit Trail")
    st.caption("Full log of every agent decision — for methods section documentation.")

    log = get_log(conn, limit=10000)
    all_papers = get_papers(conn)
    audit_json = build_audit_trail(log, all_papers)
    st.download_button(
        label="🔍 Download Audit Trail (JSON)",
        data=audit_json,
        file_name="audit_trail.json",
        mime="application/json",
        use_container_width=True,
    )

# ── Preview ────────────────────────────────────────────────────────────────────
st.divider()
st.subheader("Paper List Preview")

for i, p in enumerate(included[:10], 1):
    try:
        authors = [a["name"] for a in (json.loads(p.get("authors") or "[]") or [])[:3]]
        author_str = ", ".join(authors)
    except Exception:
        author_str = ""

    doi_link = f" | [DOI](https://doi.org/{p['doi']})" if p.get("doi") else ""
    oa_link = f" | [PDF]({p['open_access_url']})" if p.get("open_access_url") else ""
    st.markdown(
        f"{i}. **{p.get('title', 'Untitled')}** "
        f"({p.get('year', '?')}) — {author_str}{doi_link}{oa_link}"
    )

if len(included) > 10:
    st.caption(f"… and {len(included) - 10} more papers in the downloaded files.")
