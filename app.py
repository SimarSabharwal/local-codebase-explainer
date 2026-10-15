"""Streamlit entry point for the Local Codebase Explainer."""

from __future__ import annotations

import os

os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"

import streamlit as st

from src.config import AppConfig
from src.discovery import scan_project
from src.errors import OllamaConnectionError, OllamaModelError
from src.answering import AnsweringError, answer_question
from src.index_store import IndexStoreError, ProjectIndexStore, project_key
from src.indexing import IndexingError, build_index
from src.models import ScanReport
from src.ollama_client import check_connection
from src.retrieval import RetrievalError, retrieve


st.set_page_config(
    page_title="Local Codebase Explainer",
    page_icon="⌕",
    layout="wide",
)


def _config_from_sidebar() -> AppConfig:
    with st.sidebar:
        st.header("Local models")
        endpoint = st.text_input("Ollama URL", value="http://localhost:11434")
        chat_model = st.text_input("Chat model", value="llama3.2")
        embedding_model = st.text_input("Embedding model", value="nomic-embed-text")
        st.divider()
        st.header("Indexing limits")
        max_file_mb = st.number_input(
            "Maximum file size (MB)", min_value=1, max_value=100, value=2, step=1
        )
        chunk_lines = st.number_input(
            "Lines per snippet", min_value=20, max_value=300, value=100, step=10
        )
        overlap_lines = st.number_input(
            "Overlapping lines", min_value=0, max_value=100, value=15, step=5
        )
        min_similarity = st.number_input(
            "Minimum evidence similarity",
            min_value=0.0,
            max_value=0.95,
            value=0.2,
            step=0.05,
            help="Raise this to ignore weaker matches; lower it to include more results.",
        )

    return AppConfig(
        ollama_url=endpoint.strip().rstrip("/"),
        chat_model=chat_model.strip(),
        embedding_model=embedding_model.strip(),
        max_file_bytes=int(max_file_mb * 1024 * 1024),
        chunk_lines=int(chunk_lines),
        overlap_lines=int(overlap_lines),
        min_similarity=float(min_similarity),
    )


def _show_model_status(config: AppConfig) -> bool:
    try:
        status = check_connection(config)
    except OllamaConnectionError as exc:
        st.warning(f"Ollama is unavailable: {exc}")
        st.caption("Start Ollama, then check that its local service URL is correct.")
        return False
    except OllamaModelError as exc:
        st.warning(str(exc))
        return False

    st.success(
        f"Ollama connected · chat: {status.chat_model} · embeddings: {status.embedding_model}"
    )
    return True


def _show_scan(report: ScanReport) -> None:
    st.subheader("Project scan")
    left, right = st.columns(2)
    left.metric("Supported files found", len(report.files))
    right.metric("Paths skipped", report.skipped_count)

    if report.files:
        st.caption("These supported text files are ready for indexing.")
        st.dataframe(
            [
                {"File": item.relative_path, "Size": _format_size(item.size_bytes)}
                for item in report.files
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No supported files were found. Check the selected folder and file types.")

    if report.skipped:
        with st.expander(f"Why {report.skipped_count} paths were skipped", expanded=False):
            st.dataframe(
                [
                    {"Path": item.path, "Reason": item.reason}
                    for item in report.skipped
                ],
                use_container_width=True,
                hide_index=True,
            )


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def main() -> None:
    st.title("Local Codebase Explainer")
    st.write(
        "Choose a project folder to see which source and documentation files can be indexed. "
        "Your project stays on this device."
    )

    config = _config_from_sidebar()
    ollama_ready = _show_model_status(config)
    notice = st.session_state.pop("notice", None)
    if notice:
        st.success(notice)

    with st.form("project-selection"):
        project_path = st.text_input(
            "Project folder",
            value=st.session_state.get("project_path", ""),
            placeholder=r"C:\path\to\your\project",
            help="Enter the full path to a local folder. The app scans files but never runs them.",
        )
        submitted = st.form_submit_button("Select project", type="primary")

    if submitted:
        with st.spinner("Scanning the selected folder…"):
            report = scan_project(project_path, max_file_bytes=config.max_file_bytes)
        if report.error:
            st.error(report.error)
            st.session_state.pop("scan_report", None)
            st.session_state.pop("project_path", None)
        else:
            if st.session_state.get("project_path") != report.root:
                st.session_state.pop("messages", None)
            st.session_state.project_path = report.root
            st.session_state.scan_report = report

    selected_path = st.session_state.get("project_path")
    if selected_path:
        st.info(f"Selected project: `{selected_path}`")
        report = st.session_state.get("scan_report")
        if report:
            _show_scan(report)

        store = ProjectIndexStore(project_key(selected_path))
        try:
            manifest = store.load_manifest()
        except IndexStoreError as exc:
            manifest = None
            st.error(str(exc))

        if manifest:
            refreshed = manifest.get("last_refresh")
            st.caption(
                f"Index: {manifest.get('file_count', 0)} files · "
                f"{manifest.get('chunk_count', 0)} snippets · "
                f"last refresh {refreshed or 'unknown'}"
            )

        index_col, rebuild_col, clear_col = st.columns(3)
        index_label = "Refresh index" if manifest else "Build index"
        if index_col.button(index_label, type="primary", disabled=not ollama_ready):
            progress_bar = st.progress(0.0)
            progress_text = st.empty()

            def update_progress(fraction: float, label: str) -> None:
                progress_bar.progress(max(0.0, min(1.0, fraction)))
                progress_text.caption(label)

            try:
                new_report, result = build_index(
                    selected_path, config, incremental=True, progress=update_progress
                )
                st.session_state.scan_report = new_report
                st.success(
                    f"Index ready: {result['files_indexed']} files and "
                    f"{result['chunks_indexed']} snippets."
                )
                if result["skipped"]:
                    with st.expander("Files skipped while reading"):
                        st.dataframe(result["skipped"], use_container_width=True, hide_index=True)
                st.session_state.notice = (
                    f"Index ready: {result['files_indexed']} files and "
                    f"{result['chunks_indexed']} snippets."
                )
                st.rerun()
            except IndexingError as exc:
                st.error(str(exc))

        if rebuild_col.button("Full rebuild", disabled=not ollama_ready):
            progress_bar = st.progress(0.0)
            progress_text = st.empty()

            def update_rebuild_progress(fraction: float, label: str) -> None:
                progress_bar.progress(max(0.0, min(1.0, fraction)))
                progress_text.caption(label)

            try:
                new_report, result = build_index(
                    selected_path,
                    config,
                    incremental=False,
                    progress=update_rebuild_progress,
                )
                st.session_state.scan_report = new_report
                st.success(
                    f"Full rebuild ready: {result['files_indexed']} files and "
                    f"{result['chunks_indexed']} snippets."
                )
                st.session_state.notice = (
                    f"Full rebuild ready: {result['files_indexed']} files and "
                    f"{result['chunks_indexed']} snippets."
                )
                st.rerun()
            except IndexingError as exc:
                st.error(str(exc))

        if clear_col.button("Clear index", disabled=not manifest):
            try:
                store.clear()
                st.session_state.pop("messages", None)
                st.session_state.notice = "The local index for this project was cleared."
                st.rerun()
            except IndexStoreError as exc:
                st.error(str(exc))

        if manifest and int(manifest.get("chunk_count", 0)) > 0:
            st.divider()
            st.subheader("Ask about this codebase")
            with st.form("question-form"):
                question = st.text_input(
                    "Question", placeholder="Where is authentication handled?"
                )
                asked = st.form_submit_button(
                    "Ask", type="primary", disabled=not ollama_ready
                )

            if asked and question.strip():
                try:
                    with st.spinner("Searching the local index and asking Ollama…"):
                        sources = retrieve(selected_path, question.strip(), config)
                        answer, invalid_citations = answer_question(
                            question.strip(), sources, config
                        )
                    st.session_state.setdefault("messages", []).append(
                        {
                            "question": question.strip(),
                            "answer": answer,
                            "sources": sources,
                            "invalid_citations": invalid_citations,
                        }
                    )
                except (RetrievalError, AnsweringError) as exc:
                    st.error(str(exc))

            for message in st.session_state.get("messages", []):
                st.markdown(f"**You asked:** {message['question']}")
                st.markdown(message["answer"])
                if message["invalid_citations"]:
                    st.warning(
                        "The model returned a citation that did not match the retrieved snippets. "
                        "That citation was removed; verify the sources below."
                    )
                with st.expander("Retrieved source excerpts"):
                    for source in message["sources"]:
                        st.markdown(f"**{source.citation}**")
                        st.code(source.text, language=None)


main()
