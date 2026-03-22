#!/usr/bin/env python3
"""
demo.py — run the bug-fixer agent against a real GitHub issue.

Usage:
    python demo.py <repo_url> <issue_number>

Example:
    python demo.py https://github.com/owner/repo 42
"""

import argparse
import json
import sys
import urllib.request
import urllib.error

BASE_URL = "http://localhost:8000"


def fix_issue(repo_url: str, issue_number: int) -> dict:
    payload = json.dumps({"repo_url": repo_url, "issue_number": issue_number}).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/fix-issue",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        try:
            detail = json.loads(body).get("detail", body)
        except Exception:
            detail = body
        print(f"Error {exc.code}: {detail}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(f"Could not reach {BASE_URL} — is the server running?\n{exc.reason}", file=sys.stderr)
        sys.exit(1)


def pretty_print(result: dict) -> None:
    sep = "─" * 60

    print(f"\n{sep}")
    print("  ROOT CAUSE")
    print(sep)
    print(result.get("root_cause", "(none)"))

    print(f"\n{sep}")
    print("  DIFF")
    print(sep)
    diff = result.get("diff", "").strip()
    if diff:
        for line in diff.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                print(f"\033[32m{line}\033[0m")   # green
            elif line.startswith("-") and not line.startswith("---"):
                print(f"\033[31m{line}\033[0m")   # red
            else:
                print(line)
    else:
        print("(no diff returned)")

    print(f"\n{sep}")
    print("  PULL REQUEST")
    print(sep)
    print(result.get("pr_url", "(no PR URL)"))
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the bug-fixer agent on a GitHub issue.")
    parser.add_argument("repo_url", help="Full GitHub repository URL")
    parser.add_argument("issue_number", type=int, help="Issue number to fix")
    args = parser.parse_args()

    print(f"Fixing issue #{args.issue_number} in {args.repo_url} ...")
    result = fix_issue(args.repo_url, args.issue_number)
    pretty_print(result)


if __name__ == "__main__":
    main()
