# Implementation Plan: Local Codebase Explainer

## Objective

Build a local-first desktop-friendly application that indexes one selected software project at a time and answers questions from retrieved source and documentation snippets. Answers must cite file paths and line ranges, and all source, prompts, embeddings, and model calls must remain on the user's device.

## Product decisions and assumptions

- Use Python and Streamlit for the MVP UI, Ollama for local model inference, and Chroma in persistent local mode for vector retrieval, as suggested by the PRD.
- Keep file discovery, parsing, indexing, retrieval, and answer generation in separate modules so the UI does not own application logic.
- Store index data in an application data directory, partitioned by a stable identifier derived from the canonical project path. Do not write application data into the indexed repository by default.
- Use a local embedding model through Ollama; make both the embedding and chat model configurable and display actionable setup/connection errors.
- Use line-preserving chunks with configurable size and overlap as the reliable baseline. Add language-aware chunking only where it is practical without weakening line references.
- Treat unsupported encodings, oversized files, ignored paths, and unreadable files as explicit scan outcomes rather than fatal indexing errors.
- Interpret “incremental refresh” as re-indexing changed, new, and removed files by comparing path, size, and modification time, with content hashing where needed to avoid stale results.
- Never execute files from the selected project. File parsing and indexing are read-only.

## Proposed project structure

```text
app.py                         # Streamlit entry point and page composition
src/
  config.py                    # Settings, paths, model names, file-size/chunk limits
  discovery.py                 # Traversal, ignore rules, exclusion reasons
  parsing.py                   # Text decoding and line-preserving chunks
  index_store.py               # Per-project Chroma persistence and metadata
  indexing.py                  # Full build and incremental refresh orchestration
  retrieval.py                 # Embedding search and context assembly
  answering.py                 # Ollama prompt, grounded answer, citation validation
  models.py                    # Shared records and result types
  errors.py                    # User-safe actionable errors
tests/
  ...                          # Unit and integration coverage as implementation proceeds
```

The exact layout can adapt to the repository once implementation starts; the boundaries above are the intended responsibilities.

## Implementation phases

### Phase 1 — Application skeleton and local configuration

**Work**

- Create the Python application structure, dependency manifest, and startup instructions.
- Add configuration for Ollama endpoint, chat and embedding model names, supported extensions, file-size limit, chunk size/overlap, and local data directory.
- Add a connection check that distinguishes an unavailable Ollama service from a missing model and gives clear next steps.
- Establish shared records for discovered files, chunks, citations, scan outcomes, and indexing progress.

**Completion criteria**

- The app starts locally and shows a clear Ollama status.
- Configuration is local and does not require a hosted API key.
- Errors shown to users are actionable and do not expose unnecessary stack traces.

### Phase 2 — Project selection and safe file discovery

**Work**

- Add project-folder selection and keep the canonical selected root visible in the UI.
- Discover supported text source and documentation files recursively.
- Apply `.gitignore` rules where practical and always exclude `.git`, dependency folders, build output, virtual environments, and secret-like files such as `.env` by default.
- Record skip reasons for ignored, unsupported, secret-like, oversized, unreadable, and binary files.
- Normalize paths relative to the selected root for stable display and citations.

**Completion criteria**

- A selected project can be scanned without executing any project content.
- Excluded paths are summarized with understandable reasons.
- The UI can switch the selected project and clearly identifies the active project.

### Phase 3 — Parsing, chunking, and persistent index

**Work**

- Decode supported text safely and retain exact source line numbers.
- Split files into bounded, overlapping chunks; store relative path, start/end lines, content hash, and project identity with every chunk.
- Create isolated persistent Chroma collections per project.
- Implement an interrupt-tolerant full build that reports progress and does not mark a partial index as complete.
- Provide clear recovery behavior for indexing failures and interrupted runs.

**Completion criteria**

- A full index can be built using only local components.
- Every stored chunk can be mapped back to its source path and line range.
- Index state is isolated by project and remains available after restarting the app.
- Progress and recoverable errors are visible to the user.

### Phase 4 — Retrieval and grounded answers

**Work**

- Embed and retrieve relevant chunks from the active project's index only.
- Assemble bounded context for the configured local chat model.
- Instruct the model to answer only from supplied evidence, cite paths and line ranges, and explicitly say when evidence is insufficient.
- Parse/validate citations against retrieved chunks; present citations as clickable or easily locatable references with excerpts visually distinct from generated prose.
- Handle empty results, model failures, and malformed or unsupported citations without presenting invented references as verified.

**Completion criteria**

- A user can ask a question and receive a locally generated answer with citations tied to retrieved source ranges.
- Insufficient evidence produces a clear uncertainty response.
- No results from another project can enter the answer context.

### Phase 5 — Refresh, rebuild, project switching, and deletion

**Work**

- Compare the current scan with the stored manifest to find changed, new, and deleted files.
- Replace chunks for changed files, add new files, and remove stale chunks for deleted or newly excluded files.
- Expose incremental refresh and full rebuild controls.
- Show last successful refresh time and current indexing status.
- Expose clear-index and switch-project controls; ensure deletion removes only the selected project's local index.

**Completion criteria**

- Refresh updates changed files and removes deleted content without cross-project mixing.
- Full rebuild produces a clean index for the selected project.
- The user can clear the active index and select another project.
- Last refresh and indexing state are visible.

### Phase 6 — Quality, privacy, and usability pass

**Work**

- Exercise the complete flow with a representative small/medium repository, including ignored directories, `.env`, large files, unreadable/binary files, and add/change/delete refresh cases.
- Confirm paths and line ranges remain correct through chunking, storage, retrieval, and display.
- Confirm all model and embedding calls target the configured local Ollama service and no hosted AI API is used.
- Improve progress, empty states, unsupported-file reporting, and model/setup guidance based on the end-to-end flow.
- Document installation, Ollama setup, local data location, supported file types, refresh behavior, and known limitations.

**Completion criteria**

- The PRD's primary user flow works end to end on a local machine.
- Secret-like and generated content is excluded by default and exclusions are explained.
- Citations can be verified against the original files.
- Setup and recovery steps are documented.

## Cross-cutting requirements

- **Local privacy:** no hosted inference, embedding, or source upload; make the configured Ollama endpoint visible or discoverable in settings.
- **Project isolation:** include project identity in storage boundaries and retrieval filters; do not reuse a previous project's context after switching.
- **Citation integrity:** line numbers refer to original files, not chunk-relative positions; validate references before display.
- **Read-only behavior:** never execute indexed code and do not modify repository files.
- **Recoverability:** persist enough scan/index state to resume or safely rebuild after interruption.
- **User feedback:** show scan/index progress, last successful refresh, and concise reasons for skipped content.

## Key risks and mitigations

| Risk | Mitigation |
|---|---|
| Weak local model or embedding quality | Make models configurable, keep retrieval settings tunable, and disclose when evidence is weak or absent. |
| Large repositories take too long or exceed local resources | Enforce configurable size limits, skip known generated/dependency folders, show progress, and support incremental refresh. |
| Chunking breaks citation accuracy | Preserve source line metadata at parse time and test citations against known files. |
| Ignore behavior differs across platforms | Keep mandatory exclusions independent of `.gitignore`; make ignore parsing a replaceable component and report applied exclusions. |
| Index becomes stale after edits or interrupted runs | Track file manifests and hashes; update changed/deleted files transactionally where possible and distinguish incomplete from successful builds. |
| “Local only” is undermined by configuration | Use Ollama as the only model provider in the MVP and avoid hosted-provider fallbacks. |

## Suggested delivery order

1. Build phases 1–3 to establish a safe, persistent local index.
2. Build phase 4 and verify grounded answers and citations.
3. Build phase 5 to complete the lifecycle controls.
4. Complete phase 6 before calling the MVP ready.

## Open implementation choices

- Which source and documentation extensions should be enabled by default?
- What default maximum file size and chunk size/overlap best fit the target machines?
- Which Ollama chat and embedding models should be recommended in setup guidance?
- Should project-folder selection use a native picker or Streamlit's available directory input mechanism on the supported platforms?
- What operating systems are in the first release target?

Use conservative defaults and keep these settings configurable unless product feedback resolves them before implementation.
