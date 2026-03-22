import os
from typing import Optional
from typing_extensions import TypedDict

from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, END
from pydantic import BaseModel

from agent.github_tools import get_issue, get_repo_file_tree, read_file, create_fix_pr
from agent.code_tools import find_relevant_files, apply_fix, CLONE_DIR

load_dotenv()

llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    temperature=0,
    api_key=os.getenv("GROQ_API_KEY"),
)


# ── State schema ──────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    repo_url: str
    issue_number: int
    issue_data: Optional[dict]
    file_tree: Optional[list[str]]
    relevant_files: Optional[list[str]]
    file_contents: Optional[dict]
    analysis: Optional["BugAnalysis"]
    fixed_content: Optional[str]
    diff: Optional[str]
    pr_url: Optional[str]
    error: Optional[str]


# ── Helpers ───────────────────────────────────────────────────────────────────

def clean_llm_output(content: str) -> str:
    # Strip markdown code fences if present
    if content.startswith("```"):
        lines = content.split("\n")
        lines = [l for l in lines if not l.startswith("```")]
        content = "\n".join(lines)
    return content.strip()


class BugAnalysis(BaseModel):
    buggy_file: str
    buggy_function: str
    root_cause: str


def analyze_bug(issue_title: str, issue_body: str, file_contents: dict) -> BugAnalysis:
    structured_llm = llm.with_structured_output(BugAnalysis)

    files_text = "\n\n".join(
        f"### {path}\n```\n{content}\n```" for path, content in file_contents.items()
    )
    prompt = (
        f"Issue: {issue_title}\n\n{issue_body}\n\n"
        f"Relevant files:\n{files_text}\n\n"
        "Identify the buggy file, the buggy function, and the root cause of the bug."
    )
    return structured_llm.invoke(prompt)


def generate_fix(analysis: BugAnalysis, file_contents: dict) -> str:
    file_content = file_contents.get(analysis.buggy_file, "")
    prompt = (
        f"The following file contains a bug in the function `{analysis.buggy_function}`.\n"
        f"Root cause: {analysis.root_cause}\n\n"
        f"File: {analysis.buggy_file}\n```\n{file_content}\n```\n\n"
        "Return the complete corrected file content with the bug fixed. "
        "Do not include any explanation, only the fixed code."
    )
    response = llm.invoke(prompt)
    return clean_llm_output(response.content)


# ── Graph nodes ───────────────────────────────────────────────────────────────

def fetch_issue(state: AgentState) -> AgentState:
    try:
        data = get_issue(state["repo_url"], state["issue_number"])
        return {**state, "issue_data": data}
    except Exception as exc:
        return {**state, "error": f"fetch_issue failed: {exc}"}


def clone_and_explore(state: AgentState) -> AgentState:
    try:
        file_tree = get_repo_file_tree(state["repo_url"])
        issue_text = (state["issue_data"] or {}).get("body", "")
        relevant = find_relevant_files(issue_text, file_tree)
        return {**state, "file_tree": file_tree, "relevant_files": relevant}
    except Exception as exc:
        return {**state, "error": f"clone_and_explore failed: {exc}"}


def read_files(state: AgentState) -> AgentState:
    try:
        contents = {}
        for rel_path in (state["relevant_files"] or []):
            repo_name = "/".join(state["repo_url"].rstrip("/").split("/")[-2:])
            abs_path = f"{CLONE_DIR}/{repo_name.replace('/', '_')}/{rel_path}"
            contents[rel_path] = read_file(abs_path)
        return {**state, "file_contents": contents}
    except Exception as exc:
        return {**state, "error": f"read_files failed: {exc}"}


def analyze(state: AgentState) -> AgentState:
    try:
        issue = state["issue_data"] or {}
        result = analyze_bug(issue.get("title", ""), issue.get("body", ""), state["file_contents"] or {})
        return {**state, "analysis": result}
    except Exception as exc:
        return {**state, "error": f"analyze failed: {exc}"}


def fix(state: AgentState) -> AgentState:
    try:
        fixed = generate_fix(state["analysis"], state["file_contents"] or {})
        return {**state, "fixed_content": fixed}
    except Exception as exc:
        return {**state, "error": f"fix failed: {exc}", "fixed_content": None}


def apply_and_pr(state: AgentState) -> AgentState:
    try:
        analysis: BugAnalysis = state["analysis"]
        repo_name = "/".join(state["repo_url"].rstrip("/").split("/")[-2:])
        abs_path = f"{CLONE_DIR}/{repo_name.replace('/', '_')}/{analysis.buggy_file}"

        original = read_file(abs_path)
        diff = apply_fix(abs_path, original, state["fixed_content"])

        pr_url = create_fix_pr(
            repo_url=state["repo_url"],
            branch_name=f"fix/issue-{state['issue_number']}",
            file_path=analysis.buggy_file,
            fixed_content=state["fixed_content"],
            issue_number=state["issue_number"],
            diff_summary=diff,
        )
        return {**state, "diff": diff, "pr_url": pr_url}
    except Exception as exc:
        return {**state, "error": f"apply_and_pr failed: {exc}"}


def _route_after_fix(state: AgentState) -> str:
    if not state.get("fixed_content"):
        return END
    return "apply_and_pr"


# ── Build the graph ───────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("fetch_issue", fetch_issue)
    graph.add_node("clone_and_explore", clone_and_explore)
    graph.add_node("read_files", read_files)
    graph.add_node("analyze", analyze)
    graph.add_node("fix", fix)
    graph.add_node("apply_and_pr", apply_and_pr)

    graph.set_entry_point("fetch_issue")
    graph.add_edge("fetch_issue", "clone_and_explore")
    graph.add_edge("clone_and_explore", "read_files")
    graph.add_edge("read_files", "analyze")
    graph.add_edge("analyze", "fix")
    graph.add_conditional_edges("fix", _route_after_fix, {"apply_and_pr": "apply_and_pr", END: END})
    graph.add_edge("apply_and_pr", END)

    return graph.compile()


# ── Public entry point ────────────────────────────────────────────────────────

async def run_agent(repo_url: str, issue_number: int) -> AgentState:
    graph = build_graph()
    initial: AgentState = {
        "repo_url": repo_url,
        "issue_number": issue_number,
        "issue_data": None,
        "file_tree": None,
        "relevant_files": None,
        "file_contents": None,
        "analysis": None,
        "fixed_content": None,
        "diff": None,
        "pr_url": None,
        "error": None,
    }
    return await graph.ainvoke(initial)


if __name__ == "__main__":
    import sys

    repo_name = os.environ.get("REPO_NAME")
    issue_number = os.environ.get("ISSUE_NUMBER")

    if not repo_name or not issue_number:
        print("ERROR: REPO_NAME and ISSUE_NUMBER env vars are required")
        sys.exit(1)

    repo_url = f"https://github.com/{repo_name}"

    print(f"Starting agent for {repo_url} issue #{issue_number}")

    app = build_graph()
    result = app.invoke({
        "repo_url": repo_url,
        "issue_number": int(issue_number),
        "issue_data": None,
        "file_tree": [],
        "relevant_files": [],
        "file_contents": {},
        "analysis": None,
        "fixed_content": None,
        "diff": None,
        "pr_url": None,
        "error": None,
    })

    if result.get("pr_url"):
        print(f"SUCCESS: PR opened at {result['pr_url']}")
        sys.exit(0)
    else:
        print(f"FAILED: {result.get('error', 'Unknown error')}")
        sys.exit(1)
