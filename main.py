from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from agent.agent import run_agent

app = FastAPI(title="GitHub Bug Fixer Agent")


class FixIssueRequest(BaseModel):
    repo_url: str
    issue_number: int


class FixIssueResponse(BaseModel):
    pr_url: str
    diff: str
    root_cause: str


@app.post("/fix-issue", response_model=FixIssueResponse)
async def fix_issue(request: FixIssueRequest):
    state = await run_agent(request.repo_url, request.issue_number)

    if state.get("error"):
        raise HTTPException(status_code=422, detail=state["error"])

    analysis = state.get("analysis")
    return FixIssueResponse(
        pr_url=state.get("pr_url") or "",
        diff=state.get("diff") or "",
        root_cause=analysis.root_cause if analysis else "",
    )


@app.get("/health")
def health():
    return {"status": "ok"}
