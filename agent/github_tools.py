import os
from pathlib import Path
from github import Github
from git import Repo, GitCommandError
from langchain.tools import tool

_gh = None
CLONE_DIR = os.environ.get("REPO_CLONE_DIR", "/tmp/repos")


# ── helpers ──────────────────────────────────────────────────────────────────

def get_github_client() -> Github:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PAT")
    if not token:
        raise ValueError("No GitHub token found in GITHUB_TOKEN or GITHUB_PAT env vars")
    global _gh
    if _gh is None:
        _gh = Github(token)
    return _gh


def _repo_full_name(repo_url: str) -> str:
    parts = repo_url.rstrip("/").split("/")
    return f"{parts[-2]}/{parts[-1]}"


def _clone_path(repo_url: str) -> Path:
    name = _repo_full_name(repo_url).replace("/", "_")
    return Path(CLONE_DIR) / name



def get_issue(repo_url: str, issue_number: int) -> dict:
    try:
        gh = get_github_client()
        repo = gh.get_repo(_repo_full_name(repo_url))
        issue = repo.get_issue(issue_number)
    except Exception as exc:
        raise ValueError(
            f"Could not fetch issue #{issue_number} from '{repo_url}': {exc}"
        ) from exc

    comments = [
        {"author": c.user.login, "body": c.body}
        for c in issue.get_comments()
    ]

    return {
        "title": issue.title,
        "body": issue.body or "",
        "comments": comments,
    }


def get_repo_file_tree(repo_url: str) -> list[str]:
    
    clone_path = _clone_path(repo_url)

    token = os.environ.get("GITHUB_TOKEN", "")
    auth_url = repo_url.replace("https://", f"https://{token}@") if token else repo_url

    try:
        if clone_path.exists():
            # Update the existing clone — checkout default branch first to avoid
            # "did not specify a branch" error when on a detached/feature branch
            r = Repo(clone_path)
            r.remotes.origin.set_url(auth_url)
            r.remotes.origin.fetch()
            default = r.git.symbolic_ref("refs/remotes/origin/HEAD", "--short").split("/")[-1]
            r.git.checkout(default)
            r.git.reset("--hard", f"origin/{default}")
        else:
            clone_path.parent.mkdir(parents=True, exist_ok=True)
            Repo.clone_from(auth_url, clone_path)
    except GitCommandError as exc:
        raise ValueError(f"Failed to clone/pull '{repo_url}': {exc}") from exc

    py_files = sorted(
        str(p.relative_to(clone_path))
        for p in clone_path.rglob("*.py")
        if ".git" not in p.parts
    )
    return py_files


def read_file(file_path: str) -> str:
    """
    Read and return the content of a file from the local clone directory.

    Args:
        file_path: Absolute path OR a path relative to REPO_CLONE_DIR.

    Returns:
        File content as a string.

    Raises:
        FileNotFoundError: if the file does not exist.
        ValueError:        if the file cannot be decoded as UTF-8.
    """
    path = Path(file_path)
    if not path.is_absolute():
        path = Path(CLONE_DIR) / file_path

    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"Could not decode '{path}' as UTF-8: {exc}") from exc


def create_fix_pr(
    repo_url: str,
    branch_name: str,
    file_path: str,
    fixed_content: str,
    issue_number: int,
    diff_summary: str,
) -> str:
    
    fix_branch = f"fix/issue-{issue_number}"
    clone_path = _clone_path(repo_url)

    token = os.environ.get("GITHUB_TOKEN", "")
    auth_url = repo_url.replace("https://", f"https://{token}@") if token else repo_url

    repo = Repo(clone_path)
    origin = repo.remotes.origin
    origin.set_url(auth_url)

    # Start from a clean main/master (detect from remote HEAD, not active branch)
    origin.fetch()
    default_branch = repo.git.symbolic_ref("refs/remotes/origin/HEAD", "--short").split("/")[-1]
    repo.git.checkout(default_branch)
    repo.git.reset("--hard", f"origin/{default_branch}")

    # Create and checkout the fix branch (reset if it already exists)
    if fix_branch in [b.name for b in repo.branches]:
        repo.git.branch("-D", fix_branch)
    repo.git.checkout("-b", fix_branch)

    # Write the fixed file
    target = clone_path / file_path
    target.write_text(fixed_content, encoding="utf-8")

    repo.index.add([str(target)])
    repo.index.commit(f"fix: resolve issue #{issue_number}")

    # Push using an authenticated URL so Git doesn't prompt for credentials
    token = os.environ.get("GITHUB_TOKEN", "")
    auth_url = repo_url.replace("https://", f"https://{token}@")
    repo.git.push("--force", auth_url, f"{fix_branch}:{fix_branch}")

    # ── GitHub API operations ────────────────────────────────────────────────
    gh = get_github_client()
    gh_repo = gh.get_repo(_repo_full_name(repo_url))
    issue = gh_repo.get_issue(issue_number)

    pr_body = (
        f"## Auto-fix for issue #{issue_number}\n\n"
        f"**Changes made:**\n{diff_summary}\n\n"
        f"> This pull request was generated automatically by an AI agent."
    )

    # Check if a PR already exists for this branch and reuse it
    existing = list(gh_repo.get_pulls(state="open", head=f"{gh_repo.owner.login}:{fix_branch}"))
    if existing:
        existing[0].edit(body=pr_body)
        return existing[0].html_url

    pr = gh_repo.create_pull(
        title=f"Auto-fix: {issue.title}",
        body=pr_body,
        head=fix_branch,
        base=default_branch,
    )

    diff_summary = diff_summary[:500] if len(diff_summary) > 500 else diff_summary
    issue.create_comment(
        f"🤖 I found the bug and opened a fix in {pr.html_url}. "
        f"Root cause: {diff_summary}"
    )

    return pr.html_url


# ── LangChain @tool wrappers (kept from original) ────────────────────────────

@tool
def tool_get_issue(repo_url: str, issue_number: int) -> str:
    """Fetch a GitHub issue's title, body, and comments. Returns a formatted string."""
    data = get_issue(repo_url, issue_number)
    comments_text = "\n".join(
        f"  [{c['author']}]: {c['body']}" for c in data["comments"]
    ) or "  (no comments)"
    return f"Title: {data['title']}\n\nBody:\n{data['body']}\n\nComments:\n{comments_text}"


@tool
def tool_get_repo_file_tree(repo_url: str) -> str:
    """Clone a GitHub repo and list all .py files. Returns newline-separated paths."""
    files = get_repo_file_tree(repo_url)
    return "\n".join(files) if files else "(no .py files found)"


@tool
def tool_read_file(file_path: str) -> str:
    """Read and return the content of a file from the locally cloned repo."""
    return read_file(file_path)


@tool
def create_pull_request(
    repo_full_name: str,
    branch_name: str,
    title: str,
    body: str,
    base: str = "main",
) -> str:
    """Create a pull request on GitHub."""
    gh = get_github_client()
    repo = gh.get_repo(repo_full_name)
    pr = repo.create_pull(title=title, body=body, head=branch_name, base=base)
    return f"PR created: {pr.html_url}"


github_tools = [tool_get_issue, tool_get_repo_file_tree, tool_read_file, create_pull_request]
