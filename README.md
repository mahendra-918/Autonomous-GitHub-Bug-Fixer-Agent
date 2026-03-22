# Autonomous GitHub Bug Fixer Agent

> Give it a repo URL and an issue number. It reads the code, finds the bug, writes the fix, and opens a PR — no human in the loop.

---

## Demo

```
$ python demo.py https://github.com/owner/demo-repo 7
Fixing issue #7 in https://github.com/owner/demo-repo ...

────────────────────────────────────────────────────────────
  ROOT CAUSE
────────────────────────────────────────────────────────────
In calculate_discount(), the percentage is divided by 100 twice —
once by the caller and once inside the function — resulting in a
discount 100× smaller than intended.

────────────────────────────────────────────────────────────
  DIFF
────────────────────────────────────────────────────────────
--- a/pricing.py
+++ b/pricing.py
@@ -12,7 +12,7 @@ def calculate_discount(price: float, pct: float) -> float:
-    return price * (1 - pct / 100)
+    return price * (1 - pct)

────────────────────────────────────────────────────────────
  PULL REQUEST
────────────────────────────────────────────────────────────
https://github.com/owner/demo-repo/pull/8
```

---

## What it does

This project is a fully autonomous bug-fixing agent built with **LangGraph**, **LangChain + Groq (Llama 3.3 70B)**, and the **GitHub API**. Given a GitHub issue, it clones the repository, identifies the most relevant files using keyword scoring, uses a structured LLM call to pinpoint the root cause, generates a corrected file, writes a real unified diff, commits the fix to a new branch, and opens a pull request — all through a six-node LangGraph pipeline exposed as a FastAPI service.

---

## Architecture

```
POST /fix-issue
      │
      ▼
┌─────────────────┐
│  fetch_issue    │  PyGithub → issue title, body, comments
└────────┬────────┘
         │
         ▼
┌─────────────────────┐
│  clone_and_explore  │  GitPython clone + keyword-ranked file selection
└────────┬────────────┘
         │
         ▼
┌─────────────────┐
│   read_files    │  reads top-N relevant .py files from disk
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│    analyze      │  LLM → BugAnalysis(buggy_file, buggy_function, root_cause)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│      fix        │  LLM → complete corrected file content
└────────┬────────┘
         │
    fixed? ──No──► END (error returned)
         │ Yes
         ▼
┌─────────────────┐
│  apply_and_pr   │  write file, unified diff, git commit + push, open PR
└────────┬────────┘
         │
         ▼
   { pr_url, diff, root_cause }
```

---

## Setup

**Prerequisites:** Docker, a GitHub token with repo write access, a [Groq API key](https://console.groq.com).

```bash
git clone https://github.com/your-username/Autonomous-GitHub-Bug-Fixer-Agent
cd Autonomous-GitHub-Bug-Fixer-Agent

cp .env.example .env
# Edit .env and fill in GITHUB_TOKEN and GROQ_API_KEY

docker compose up --build
```

The API is now live at `http://localhost:8000`.

**Run the demo:**

```bash
python demo.py https://github.com/owner/repo 42
```

**Or call the API directly:**

```bash
curl -s -X POST http://localhost:8000/fix-issue \
  -H "Content-Type: application/json" \
  -d '{"repo_url": "https://github.com/owner/repo", "issue_number": 42}' \
  | python -m json.tool
```

---

## .env reference

```
GITHUB_TOKEN=ghp_...        # Personal access token (repo scope)
GROQ_API_KEY=gsk_...        # Groq API key
REPO_CLONE_DIR=/tmp/repos   # Where repos are cloned inside the container
```

---

## Stack

| Layer | Technology |
|---|---|
| LLM | Groq — Llama 3.3 70B Versatile |
| Agent orchestration | LangGraph `StateGraph` |
| GitHub API | PyGithub |
| Git operations | GitPython |
| API server | FastAPI + Uvicorn |
| Container | Docker / docker compose |
# Autonomous-GitHub-Bug-Fixer-Agent
