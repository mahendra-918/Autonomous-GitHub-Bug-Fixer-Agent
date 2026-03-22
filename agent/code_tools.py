import difflib
import os
import re
import subprocess
from collections import Counter
from pathlib import Path
from langchain.tools import tool

CLONE_DIR = os.environ.get("REPO_CLONE_DIR", "/tmp/repos")


def _repo_path(repo_full_name: str) -> Path:
    return Path(CLONE_DIR) / repo_full_name.replace("/", "_")


@tool
def clone_repo(repo_url: str, repo_full_name: str) -> str:
    """Clone a GitHub repository locally."""
    path = _repo_path(repo_full_name)
    if path.exists():
        return f"Already cloned at {path}"
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", repo_url, str(path)], check=True)
    return f"Cloned to {path}"


@tool
def read_local_file(repo_full_name: str, file_path: str) -> str:
    """Read a file from the locally cloned repository."""
    full_path = _repo_path(repo_full_name) / file_path
    return full_path.read_text()


@tool
def write_local_file(repo_full_name: str, file_path: str, content: str) -> str:
    """Write content to a file in the locally cloned repository."""
    full_path = _repo_path(repo_full_name) / file_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content)
    return f"Written to {full_path}"


@tool
def create_branch_and_commit(
    repo_full_name: str, branch_name: str, commit_message: str
) -> str:
    """Create a new git branch and commit all changes in the local repo."""
    repo_path = str(_repo_path(repo_full_name))
    subprocess.run(["git", "-C", repo_path, "checkout", "-b", branch_name], check=True)
    subprocess.run(["git", "-C", repo_path, "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", repo_path, "commit", "-m", commit_message], check=True
    )
    return f"Branch '{branch_name}' created and changes committed."


@tool
def push_branch(repo_full_name: str, branch_name: str) -> str:
    """Push a local branch to the remote GitHub repository."""
    repo_path = str(_repo_path(repo_full_name))
    subprocess.run(
        ["git", "-C", repo_path, "push", "origin", branch_name], check=True
    )
    return f"Branch '{branch_name}' pushed to origin."


# ── the two requested functions ──────────────────────────────────────────────

# Common English words that carry no signal for file relevance.
_STOPWORDS = {
    "the", "a", "an", "is", "it", "in", "on", "at", "to", "of", "and",
    "or", "not", "with", "for", "this", "that", "was", "are", "be",
    "when", "where", "how", "what", "which", "from", "by", "as", "has",
    "have", "had", "but", "so", "if", "then", "than", "i", "we", "my",
    "our", "can", "does", "do", "its",
}


def find_relevant_files(issue_body: str, file_tree: list[str], top_n: int = 5) -> list[str]:
    
    if not file_tree:
        raise ValueError("file_tree is empty — nothing to rank.")

    # Build keyword set from the issue text
    tokens = re.findall(r"[a-z_][a-z0-9_]*", issue_body.lower())
    # Also split camelCase / snake_case tokens that appear in issue text
    expanded: list[str] = []
    for t in tokens:
        expanded.extend(re.split(r"[_\-]", t))
    keywords = {w for w in expanded if len(w) > 2 and w not in _STOPWORDS}

    def score(path: str) -> int:
        # Decompose path into searchable parts: dir names + filename (without .py)
        parts = Path(path).parts
        stem = Path(path).stem
        # Also split snake_case names so "auth_handler" → ["auth", "handler"]
        name_tokens = set(re.split(r"[_\-]", stem))
        searchable = {p.lower() for p in parts} | name_tokens
        return sum(1 for kw in keywords if kw in searchable)

    scored = sorted(file_tree, key=lambda p: (-score(p), p))
    return scored[:top_n]


def apply_fix(file_path: str, original_content: str, fixed_content: str) -> str:
   
    path = Path(file_path)
    if not path.parent.exists():
        raise FileNotFoundError(f"Parent directory does not exist: {path.parent}")

    path.write_text(fixed_content, encoding="utf-8")

    diff_lines = list(
        difflib.unified_diff(
            original_content.splitlines(keepends=True),
            fixed_content.splitlines(keepends=True),
            fromfile=f"a/{path.name}",
            tofile=f"b/{path.name}",
        )
    )
    return "".join(diff_lines)


code_tools = [
    clone_repo,
    read_local_file,
    write_local_file,
    create_branch_and_commit,
    push_branch,
]
