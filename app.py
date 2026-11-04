import streamlit as st
from src.config import settings
from src.file_handler import read_upload, validate_upload, SUPPORTED
from src.analyzer import analyze
from src.fix_engine import build_correction, unified_diff
from src.ai_service import explain_with_ai
from src.report_generator import report_payload, json_report, text_report

st.set_page_config(page_title="BugTrace AI", page_icon="⌁", layout="wide", initial_sidebar_state="expanded")
st.markdown("""<style>
.stApp {background: radial-gradient(circle at 80% 0%, #162a4a 0, #08111f 42%, #050b14 100%); color:#e8f0fb}
.block-container{max-width:1240px;padding-top:2rem}.brand{font-size:2.4rem;font-weight:800;letter-spacing:-.04em}.brand span{color:#43d9ff}.sub{color:#91a9c6;font-size:1.05rem}.pill{display:inline-block;border:1px solid #2b6c89;border-radius:999px;padding:.28rem .7rem;color:#79e4ff;background:#0d2535;font-size:.8rem}.card{background:linear-gradient(145deg,rgba(18,39,66,.95),rgba(9,22,39,.95));border:1px solid #234665;border-radius:18px;padding:1.1rem 1.25rem;box-shadow:0 10px 30px #0003}.finding{border-left:4px solid #ff5f6d;padding:.7rem 1rem;margin:.55rem 0;background:#111f31;border-radius:0 12px 12px 0}.ok{border-left-color:#46e0a0}.warn{border-left-color:#ffc857}.muted{color:#91a9c6}.stButton>button{border-radius:10px;border:1px solid #2e7fa2}.stDownloadButton>button{border-radius:10px}
</style>""", unsafe_allow_html=True)

if "analysis" not in st.session_state: st.session_state.analysis=None
if "history" not in st.session_state: st.session_state.history=[]

with st.sidebar:
    st.markdown("### BugTrace <span style='color:#43d9ff'>AI</span>", unsafe_allow_html=True)
    page=st.radio("Navigation", ["Dashboard", "Analyze Code", "Analysis Results", "Project Information", "Settings"], label_visibility="collapsed")
    st.divider(); st.markdown("**Runtime mode**")
    st.success("AI enabled" if settings.ai_enabled else "Local fallback")
    st.caption("Static analysis only. Uploaded code is never executed.")

st.markdown("<div class='brand'>BugTrace <span>AI</span></div><div class='sub'>AI-Powered Code Analysis & Debugging Assistant &nbsp; <span class='pill'>SDG 9 · Innovation & Infrastructure</span></div>", unsafe_allow_html=True)
st.write("")

def run_analysis(source, filename, language):
    findings=analyze(source, language, filename); mode=("AI + local" if settings.ai_enabled else "Local fallback")
    if language in {"C", "C++"}:
        mode = f"{language} compiler diagnostics"
    correction=build_correction(source, findings, language, filename) if language in {"Python", "C", "C++"} else None
    corrected=correction.corrected if correction else None
    corrected_findings=correction.remaining if correction else []
    ai_note=None
    if settings.ai_enabled and findings:
        ok, result=explain_with_ai(source, [f.to_dict() for f in findings]); ai_note=result if ok else str(result)
        if ok and isinstance(result, dict) and result.get("corrected_code"):
            corrected=result["corrected_code"]
            corrected_findings=analyze(corrected, language, filename)
    st.session_state.analysis={"source":source,"filename":filename,"language":language,"findings":findings,"corrected":corrected,"mode":mode,"ai_note":ai_note,"correction":correction,"corrected_findings":corrected_findings}
    st.session_state.history.append({"filename":filename,"errors":sum(f.severity=="error" for f in findings),"warnings":sum(f.severity=="warning" for f in findings)})

if page in ("Dashboard", "Analyze Code"):
    if page=="Dashboard":
        st.markdown("## Ship cleaner code with confidence")
        st.markdown("<div class='card'>Paste code or upload a source file. BugTrace AI combines safe Python syntax checks, optional Ruff diagnostics, and transparent AI suggestions when configured.</div>", unsafe_allow_html=True)
        st.write("")
    col1,col2=st.columns([1.35,1])
    with col1:
        st.markdown("### Code workspace")
        uploaded=st.file_uploader("Upload source file", type=[x.lstrip('.') for x in SUPPORTED], help=f"Maximum size: {settings.max_upload_mb} MB")
        default='def greet(name)\n    return f"Hello, {name}"\n'
        source=default; filename="untitled.py"
        if uploaded:
            data=uploaded.getvalue(); ok,msg=validate_upload(uploaded.name,data,settings.max_upload_mb)
            if ok: source,language=read_upload(uploaded.name,data,settings.max_upload_mb); filename=uploaded.name
            else: st.error(msg); language="Python"
        else: language=st.selectbox("Language", ["Python","JavaScript","Java","C","C++"])
        source=st.text_area("Source code", value=source, height=310, label_visibility="collapsed")
        b1,b2=st.columns([1,1])
        with b1:
            if st.button("Analyze code", type="primary", use_container_width=True):
                run_analysis(source, filename, language); st.success("Analysis complete.")
        with b2:
            if st.button("Load clean example", use_container_width=True): st.rerun()
    with col2:
        st.markdown("### At a glance")
        a=st.session_state.analysis
        errors=sum(f.severity=="error" for f in a["findings"]) if a else 0; warnings=sum(f.severity=="warning" for f in a["findings"]) if a else 0
        c1,c2=st.columns(2); c1.metric("Errors",errors); c2.metric("Warnings",warnings)
        st.markdown("<div class='card'><b>How it works</b><br><span class='muted'>1 · Parse safely<br>2 · Inspect with local rules / Ruff<br>3 · Explain in plain language<br>4 · Review, compare, and download suggestions</span></div>", unsafe_allow_html=True)
        st.write("")
        st.info("Never upload passwords, API keys, personal data, or confidential source code.")

if page in ("Analysis Results", "Dashboard", "Analyze Code") and st.session_state.analysis:
    a=st.session_state.analysis
    if page=="Analysis Results": st.markdown("## Analysis results")
    st.markdown(f"### {a['filename']} · {a['language']} <span class='pill'>{a['mode']}</span>", unsafe_allow_html=True)
    for f in a["findings"]:
        cls="ok" if f.severity=="info" else ("warn" if f.severity=="warning" else "")
        verified = " · verified local fix" if getattr(f, "verified", False) else ""
        st.markdown(f"<div class='finding {cls}'><b>{f.severity.upper()} · {f.code}</b> · line {f.line or 'n/a'}{verified}<br>{f.message}<br><span class='muted'>{f.explanation}<br><b>Suggested fix:</b> {f.suggestion}</span></div>", unsafe_allow_html=True)
    if not a["findings"]: st.success("No findings detected by the configured analyzers.")
    correction=a.get("correction")
    if correction and correction.corrected:
        if correction.verified:
            st.success(f"Local correction applied {len(correction.applied)} change(s) and re-analysis found no remaining errors.")
        else:
            st.warning(f"Local correction applied {len(correction.applied)} change(s), but re-analysis found {len(correction.remaining)} remaining finding(s). Review before downloading.")
        if correction.remaining:
            st.markdown("**Remaining findings after correction**")
            for f in correction.remaining:
                st.markdown(f"- **{f.severity.upper()} · {f.code}** · line {f.line or 'n/a'} — {f.message}")
    elif a.get("corrected") and a.get("ai_note"):
        remaining=a.get("corrected_findings", [])
        st.warning(f"AI suggestion re-analysis found {len(remaining)} remaining finding(s). The suggestion is not verified.")
        for f in remaining:
            st.markdown(f"- **{f.severity.upper()} · {f.code}** · line {f.line or 'n/a'} — {f.message}")
    if a.get("ai_note"):
        st.info("AI-generated suggestions are unverified hypotheses. Review them before applying.")
    left,right=st.columns(2)
    with left: st.code(a["source"], language=a["language"].lower())
    with right:
        st.markdown("**Suggested corrected code**")
        st.code(a["corrected"] or a["source"], language=a["language"].lower())
        if a["corrected"]: st.markdown("**Unified diff**"); st.code(unified_diff(a["source"],a["corrected"]), language="diff")
    report_findings = a["findings"]
    report_correction = a.get("correction")
    report_corrected = a.get("corrected")
    report_remaining = a.get("corrected_findings", [])
    payload=report_payload(
        a["filename"], a["language"], report_findings, a["mode"],
        original_code=a["source"], corrected_code=report_corrected,
        reanalysis_findings=report_remaining,
        fixes_proposed=report_corrected is not None,
        fix_verified=bool(report_correction and report_correction.verified),
    )
    d1,d2,d3=st.columns(3)
    d1.download_button("Download corrected code", a["corrected"] or a["source"], file_name="suggested_"+a["filename"], use_container_width=True)
    d2.download_button("Download JSON report", json_report(payload), file_name="bugtrace_report.json", use_container_width=True)
    d3.download_button("Download TXT report", text_report(payload), file_name="bugtrace_report.txt", use_container_width=True)

if page=="Project Information":
    st.markdown("## Project information")
    st.markdown("<div class='card'><h3>Problem statement</h3>Beginners often struggle to interpret compiler and linter output. BugTrace AI turns safe static diagnostics into understandable guidance without executing untrusted code.</div>", unsafe_allow_html=True)
    st.markdown("### SDG 9 alignment")
    st.write("BugTrace AI supports the spirit of UN Sustainable Development Goal 9 (Industry, Innovation and Infrastructure) by demonstrating technology-driven innovation, software reliability, efficient debugging workflows, and accessible programming assistance. It does not claim measured SDG impact.")
    st.markdown("[Official SDG 9 reference](https://sdgs.un.org/goals/goal9)")
    st.markdown("### Implemented vs future scope")
    st.write("Implemented: Python AST validation, optional Ruff integration, local explanations, optional Anthropic integration, reports, downloads, and tests. Future scope: richer JavaScript/Java tooling, repository integrations, authenticated multi-user history, and safe sandboxed runtime diagnostics.")

if page=="Settings":
    st.markdown("## Settings & AI configuration")
    st.markdown(f"<div class='card'><b>Current mode:</b> {'AI + local fallback' if settings.ai_enabled else 'Local fallback only'}<br><span class='muted'>Model: {settings.anthropic_model if settings.ai_enabled else 'not active'}<br>API keys are never displayed.</span></div>", unsafe_allow_html=True)
    st.write("To enable AI locally, copy `.env.example` to `.env`, set `ANTHROPIC_API_KEY`, optionally set `ANTHROPIC_MODEL`, then restart Streamlit. Without a valid key, the application remains useful and clearly labels local results.")
