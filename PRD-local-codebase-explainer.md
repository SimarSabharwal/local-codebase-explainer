# PRD: Local Codebase Explainer

## Product summary

A local-first tool that indexes a software project and lets a developer ask questions about its files, structure, and behavior. It uses a local LLM and returns answers with file and line references.

## Problem

Understanding an unfamiliar codebase requires manually searching files and tracing how pieces connect. Hosted AI tools can be unsuitable when code is proprietary or private.

## Target users

- Developers onboarding to an unfamiliar repository
- Students learning from example projects
- Individual contributors who want quick answers about a local codebase

## Goals

- Help users locate relevant code and understand how it fits together.
- Keep source code and prompts on the user's machine.
- Ground explanations in source files and make verification easy.

## MVP scope

- Select a local project directory.
- Index common source and documentation files while ignoring common generated and dependency directories.
- Search indexed files with local embeddings and retrieve relevant snippets.
- Answer questions through an Ollama-hosted local model.
- Show source file paths and line ranges for cited snippets.
- Let users refresh or rebuild the index after code changes.
- Let users select a new project or clear the current index.

## Primary user flow

1. The user starts the app and chooses a local project folder.
2. The app scans supported files, applies ignore rules, and builds a local index.
3. The user asks a question such as “Where is authentication handled?”
4. The app retrieves relevant snippets and asks the local model to explain them.
5. The app shows an answer with file paths and line references.
6. The user opens the referenced files to verify details or refreshes the index after changes.

## Functional requirements

- Index text-based source and documentation files from a user-selected directory.
- Respect `.gitignore` where practical and always skip common large or generated folders such as `.git`, dependency directories, build output, and virtual environments.
- Do not index secret-like files such as `.env` by default; provide an understandable explanation of excluded paths.
- Support incremental refresh based on file changes, with a full rebuild option.
- Answers must cite file paths and line ranges when available.
- If the repository does not provide enough evidence, the app should say so rather than inventing architecture or behavior.
- Never execute indexed code.
- Provide controls to switch projects and delete the local index.
- Report unsupported files, oversized files, and model connection problems clearly.

## Non-functional requirements

- Source files, embeddings, and prompts stay on the user's device.
- The MVP should support a small to medium project, with a configurable file-size limit.
- Indexing should show progress and remain recoverable if interrupted.
- Search results should be fast enough for interactive use on a typical developer laptop.
- The index should be isolated per project to prevent results from leaking between projects.

## Out of scope for MVP

- Code editing or patch generation
- Running builds, tests, or shell commands on behalf of the user
- Git hosting integrations
- Multi-repository search
- IDE extensions
- Automated vulnerability scanning

## UX requirements

- Make the selected project root visible at all times.
- Show indexing status and the last refresh time.
- Make citations clickable or easy to locate in the referenced file.
- Explain why certain files and folders are skipped.
- Keep code excerpts visually distinct from model-generated explanations.

## Suggested implementation

- UI: Streamlit for a fast prototype
- Local model runtime: Ollama
- Retrieval store: Chroma in persistent local mode
- File discovery: Python filesystem traversal with ignore handling
- Parsing: language-aware chunking where practical, with a simple line-preserving fallback
- Language: Python

## Success criteria

- A user can select a local repository, index it, and ask questions without a hosted AI API.
- Answers include verifiable file and line references.
- Common generated folders and secret-like files are excluded by default.
- Refreshing the project updates the index without mixing content from another project.

## Risks and assumptions

- Retrieval quality depends on file selection, chunking, and the embedding model.
- Very large repositories may need tighter scope or longer indexing time.
- Local model context limits and capabilities vary by hardware and model choice.
- “Local only” depends on configuring every model and embedding component to run locally.
