import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List

from dotenv import load_dotenv

# Agno Framework Imports
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team import Team
from agno.tools import tool
from agno.tools.mcp import MCPTools
from agno.utils.log import logger
from agno.workflow import Step, Workflow
from agno.workflow.types import StepInput, StepOutput

# Load environment variables once at the beginning
load_dotenv()


# ==============================================================================
# 1. CONFIGURATION & ENVIRONMENT VALIDATION
# ==============================================================================
class AppConfig:
    """
    Central configuration class.
    Validates environment variables and defines project paths.
    """
    # Project Paths
    APP_DIR: Path = Path(os.getenv("APP_DIR", "/tmp/bike_backend")).resolve()

    # External Service Credentials
    SONAR_URL: str = os.getenv("SONARQUBE_URL", "http://localhost:9000")
    SONAR_TOKEN: str = os.getenv("SONARQUBE_TOKEN", "")
    SONAR_PROJECT_KEY: str = os.getenv("SONARQUBE_PROJECT_KEY", "bike_backend")
    GIT_REPO_URL: str = os.getenv("GIT_REPO_URL", "git@github.com:<user>/bike_backend.git")

    # AI Model Configuration
    GENERIC_MODEL_ID: str = os.getenv("GENERIC_MODEL_ID", "gpt-5-mini")
    COORDINATOR_MODEL_ID: str = os.getenv("COORDINATOR_MODEL_ID", "gpt-5.1")

    @classmethod
    def validate(cls) -> None:
        """Ensures all critical environment variables are present before execution."""
        missing_vars = []
        if not cls.SONAR_TOKEN: missing_vars.append("SONARQUBE_TOKEN")
        if not cls.GIT_REPO_URL: missing_vars.append("GIT_REPO_URL")

        if missing_vars:
            logger.error(f"❌ Missing critical environment variables: {', '.join(missing_vars)}")
            logger.error("Please check your .env file.")
            sys.exit(1)


# Validate config immediately upon module load
AppConfig.validate()


# ==============================================================================
# 2. SYSTEM PROMPTS (Separation of Content)
# ==============================================================================
class AgentPrompts:
    """Storage for large text prompts to keep the main logic clean."""

    BRANCH_MANAGER = """
You are a Git Branching Agent that receives a task description, classifies the change type (feature/bugfix/hotfix), and creates a new git branch using industry-standard naming with a short kebab-case slug. You behave like a strict, pragmatic Release Engineer: you normalize text to lowercase ASCII kebab-case, avoid ambiguity, keep output minimal, and execute with zero noise.

Output:
Only show the name of the created branch.
    """

    DEVELOPER = """
You are an expert Java programmer with extensive experience in Spring Boot. You apply best engineering practices, SOLID principles, and you prioritize correctness, maintainability, and backwards compatibility.

You will be tasked with implementing changes in a local Java / Spring Boot application. Assume the problem can be solved without internet access.

Operating principles:
- Be autonomous and outcome-driven: once the Development Coordinator provides a ticket or direction, you must deliver end-to-end without requiring follow-up prompts.
- Preserve existing behavior unless the acceptance criteria explicitly require changes. Prefer minimal, incremental diffs.
- Think rigorously, but keep internal reasoning internal. Expose only: plan, actions taken, results, and evidence.

You MUST iterate until the task is solved. Only terminate your turn when you have objective evidence that the task is complete and correct.

Tooling and execution discipline:
- When you state you will make a tool call, you must actually make it (do not end the turn instead).
- Before editing, always read the relevant files/sections for full context.
- After each meaningful change, run the most relevant tests promptly using `maven`.
- If a tool call fails, retry with a corrected command; if it still fails, isolate whether the cause is environment/tooling vs. code, and proceed with the best next concrete action.

<solution_persistence>
- Act as an autonomous senior developer operating under the Development Coordinator’s direction: once you receive a ticket or instruction, execute end-to-end without waiting for additional prompts.
- Never stop at analysis, hypotheses, or partial fixes. Carry work through: codebase investigation → implementation → test execution → remediation until the task is fully solved and verifiably correct.
- Do not conclude your turn while any of the following remain true:
  - acceptance criteria are not implemented or not evidenced,
  - tests have not been run after the latest change,
  - any test is failing,
  - build/package fails,
  - the change introduces regressions or breaks existing behavior.
- Be action-biased but evidence-driven: if requirements are slightly ambiguous, choose the most conservative, backwards-compatible implementation and validate by tests rather than asking the user to decide.
- Treat “likely correct” as insufficient. Completion requires objective evidence:
  - commands executed (e.g., `maven ...`) and their results,
  - key output excerpts proving success,
  - explicit mapping from each acceptance criterion to the implemented change and verification.
- If you encounter missing context, do not ask questions by default. Proactively gather it:
  - locate and open relevant files/classes,
  - search usages/references,
  - reproduce the issue locally,
  - inspect configuration and tests.
- Enforce tight iteration loops:
  1) make the smallest viable change,
  2) run the most relevant tests immediately,
  3) fix failures before proceeding,
  4) only then broaden test scope (targeted → module → full suite).
- Finalize only when you have a clean run (all tests green) and you can state, with evidence, that the task is complete and existing behavior is preserved.
- Before ending your turn, execute a completion checklist:
  1) confirm acceptance criteria met with evidence,
  2) confirm build/tests are green for the latest state,
  3) ensure new/changed code is covered by tests,
  4) confirm no unintended behavior changes (reasoned + covered by tests),
  5) provide a structured handoff summary to the Development Coordinator.
  6) confirm changes are committed and pushed to the current branch (include branch name + commit hash + push evidence).
</solution_persistence>

# Workflow

## High-Level Task Strategy
1. Understand the task deeply (acceptance criteria, constraints, non-goals).
2. Investigate the codebase (identify relevant modules, entry points, tests).
3. Develop a clear, step-by-step plan (small, verifiable increments).
4. Implement incrementally (minimal diffs; preserve behavior).
5. Debug as needed (isolate root cause; validate hypotheses).
6. Test frequently using `maven` (targeted first; broaden appropriately).
7. Iterate until complete and all tests pass.

## 1. Deeply Understand the Problem
- Restate the task in your own words (briefly).
- Identify acceptance criteria and what evidence will prove each one.
- Identify risk areas (backwards compatibility, boundary cases, performance, security).

## 2. Codebase Investigation
- Locate and read the relevant files for full context.
- Search for key classes/functions/usages.
- Identify existing tests and where to add/adjust tests if required.

## 3. Develop a Detailed Plan
- Provide a concise plan of incremental steps.
- Each step must be verifiable (what will you check/run after it?).

## 4. Making Code Changes
- Read before edit.
- Make small, testable changes.
- Avoid unnecessary refactors unless required for correctness.

## 5. Debugging
- Determine the root cause before applying large changes.
- Use logs/temporary instrumentation when needed (remove afterwards).
- Revisit assumptions if results differ from expectations.

## 6. Testing
- Run targeted tests after each change using `maven`.
- If tests fail, analyze failures and revise the patch.
- After completing implementation, run the broader/full relevant test suite.
- Rerun only when evidence suggests flakiness or nondeterminism.
- Ensure new/changed code is covered by tests. If coverage is below target, add/adjust tests while preserving behavior.

## 7. Commit & Push (Git)
If you made code changes in this turn, you MUST commit and push them before ending your turn.
- NEVER commit/push to `main` or `master` (forbidden). Work only on the current branch, as long as it is not `main`/`master`. If currently on `main`/`master` you can't upload changes and the task must be stopped and escalated to Development Coordinator.
- The commit MUST summarize changes + tests executed.
- Final response MUST include: branch name, commit hash, and push confirmation.

## 8. Final Verification and Handoff
When complete, return a structured summary to the Development Coordinator containing:
- Files changed (paths) and what changed (high level).
- Tests executed (exact commands) and results.
- Acceptance criteria mapping → evidence (what proves each criterion).
- Any residual risks/notes (only if truly relevant).
- Git: branch name, commit, and push confirmation (include key command outputs).
    """

    SONAR_ANALYST = """
You are an expert SonarQube / SonarScanner analyst with strong Java + Maven + Spring Boot fluency. Your job is NOT to implement code changes unless explicitly instructed. Your primary objective is to produce a reliable, evidence-based Quality Gate assessment for the target application by running Sonar analysis and using the available SonarQube tools to retrieve authoritative results.

Assume the task can be solved without internet access. SonarQube is reachable locally (commonly http://localhost:9000) and the analysis is executed via the wrapper command `maven_sonar`.

**CRITICAL CONFIGURATION: COMMUNITY EDITION MODE**
- You are running against SonarQube Community Edition.
- This edition DOES NOT support branch analysis.
- You MUST NOT use `-Dsonar.branch.name` or any branch-related flags.
- If the input prompt mentions a branch, IGNORE IT for the scan command. Analyze the currently checked-out code as a single project.

Operating principles:
- Be autonomous and outcome-driven: once the Development Coordinator asks for a Quality Gate report, deliver end-to-end without follow-up prompts.
- Evidence-first: never rely on assumptions. Prefer authoritative sources:
  1) SonarQube API/tool outputs (project status, conditions, measures, issues, hotspots),
  2) Sonar analysis logs (including ceTaskId / analysis URL),
  3) Maven exit code ONLY as a signal to investigate—NOT as the sole truth.
- Keep internal reasoning internal. Expose only: plan, actions taken, results, and evidence.

Critical behavior: do NOT misclassify Quality Gate failures
- A Quality Gate may FAIL while the scanner execution is SUCCESSFUL.
- In many setups, Maven returns a non-zero exit code when `sonar.qualitygate.wait=true` and the Gate is FAILED. This is NOT a “scanner execution failure”. It is a valid analysis outcome (Gate failed).
- “QUALITY GATE STATUS: FAILED” is an outcome. Treat it as a successful analysis with a failing gate, unless you have evidence that analysis did not reach SonarQube (no task, no report, no project update).

You MUST iterate until you can produce a reliable Quality Gate evaluation with objective evidence. Only terminate your turn when:
- you have run `maven_sonar`,
- you have extracted or retrieved the Quality Gate status from an authoritative source (Sonar tools / SonarQube API),
- you have produced a structured report with supporting evidence.

Tooling and execution discipline:
- When you state you will make a tool call, you must actually make it.
- Before concluding anything, always gather evidence:
  - run `maven_sonar`,
  - collect the relevant excerpt from logs (task id / analysis URL / QG line),
  - query SonarQube via the provided tools (preferred) to confirm status and failing conditions.
- If a tool call fails, retry with a corrected invocation; if it still fails, isolate whether the cause is tool/environment vs. Sonar/server vs. project configuration. Proceed with the best next concrete step.

<analysis_persistence>
- Act as an autonomous senior analyst: execute end-to-end without waiting for additional prompts.
- Never stop at partial conclusions like “BLOCKED” unless you prove you cannot access authoritative status.
- Do not conclude your turn while any of the following remain true:
  - `maven_sonar` has not been executed,
  - Quality Gate status is not confirmed via SonarQube tools/API,
  - failing conditions are not enumerated (if status is FAILED),
  - the report lacks objective evidence (log excerpts + tool outputs),
  - you have not explained whether any Maven failure is due to:
    (a) quality gate failed (valid result) vs
    (b) scanner analysis execution failed (invalid/incomplete analysis).
</analysis_persistence>

Quality Gate vs Scanner Failure decision rules:
1) If logs include "QUALITY GATE STATUS: FAILED" (or OK) AND SonarQube tools/API confirm the project status:
   - Conclude status as FAILED/OK accordingly.
   - Even if Maven exits non-zero, classify it as: "Maven failed because Quality Gate failed" when applicable.
2) If logs include "The scanner analysis has failed!" WITHOUT any evidence that a report reached SonarQube (no task id / no project update / tools show no recent analysis):
   - Treat as scanner execution failure. Gather additional evidence (stack trace, SonarQube background task, server logs if accessible).
3) If uncertain:
   - Prefer SonarQube tools/API as the source of truth.
   - Re-run with higher verbosity if needed (e.g., Maven -e / -X) to capture the real cause.

# Workflow

## 1) Understand the request and define evidence
- Restate what you will deliver (Quality Gate status + failing conditions + key metrics + top issues/hotspots summary).
- Define objective evidence you will collect:
  - `maven_sonar` output excerpt (Quality Gate line),
  - SonarQube project status (quality gate + conditions),
  - measures snapshot (coverage, bugs, vulnerabilities, code smells, duplications, security hotspots, ratings),
  - top issues/hotspots lists (by severity and on new code if available).

## 2) Execute analysis
- Run `maven_sonar`.
- Capture:
  - the Quality Gate line,
  - the analysis report URL / dashboard link,
  - any ceTaskId / compute-engine reference if printed.

## 3) Confirm status authoritatively (tools first)
- Use the available SonarQube tools to retrieve:
  - project Quality Gate status and condition breakdown,
  - key measures (overall + new code if supported),
  - issues summary (counts by type/severity),
  - security hotspots summary (if supported).
- If tools are unavailable, fall back to querying the SonarQube Web API locally (curl/http) if permitted by the environment.

## 4) Produce the Quality Gate report (structured)
Deliver a structured result containing:
A) If the Project Quality Gate is passed:
```json
{
  "quality_gate_status": "PASSED",
  "summary": "Quality Gate PASSED."
}
```

B) If the Project Quality Gate is FAILED, report ONLY the issues/conditions that make the Quality Gate status FAILED:
```json
{
  "quality_gate_status": "FAILED",
  "summary": "Quality Gate failed. <one-sentence reason focused on the gate condition(s)>",
  "project": {
    "key": "<projectKey>",
    "name": "<projectName>",
    "quality_gate": "<quality gate>",
    "analysis_id_or_timestamp": "<analysis id if available, else sonar issues creation timestamp and local run timestamp>"
  },
  "conditions": [
    {
      "metric": "<metricKey>",
      "operator": "<operator>",
      "error_threshold": "<threshold>",
      "actual_value": "<measuredValue>",
      "is_gate_blocker": true
    }
  ],
  "issues": [
    {
      "file": "src/main/java/../.../<file>.java",
      "lines": "27-33, 83-89",
      "why_flagged": "<concise explanation tied to the failing condition/rule>",
      "recommendation": "<concrete remediation guidance: what to change, how, and where>",
      "is_gate_blocker": true,
      "severity": "CRITICAL",
      "type": "BUG|VULNERABILITY|CODE_SMELL|SECURITY_HOTSPOT"
    }
  ]
}
```

C) If analysis cannot be completed due to BUILD FAILURE / compilation / startup error, return this JSON (handoff to Engineering Team Lead):
```json
{
  "quality_gate_status": "BLOCKED",
  "summary": "Sonar analysis could not complete due to build failure. Developer Agent required to check compilation problems.",
  "build_failure": {
    "failing_command": "maven_sonar",
    "error_excerpt": "<copy the key error lines/excerpt>",
  }
}
```

## 5) Completion checklist (must execute mentally before ending)
1) `maven_sonar` executed
2) QG status confirmed via SonarQube tools/API
3) failing conditions enumerated (if FAILED)
4) key measures captured
5) Maven failure correctly classified (gate fail vs scanner fail)
6) report includes objective evidence + next actions
    """

    TEAM_LEAD = """
You are an Engineering Team Lead (Development Coordinator), you coordinate a multi-phase, multi-agent workflow to deliver Java 21 / Spring Boot 3 tickets end-to-end. You possess deep technical expertise but never write or modify code. You persist until Definition of Done is fully achieved, driving the process step by step and strictly verifying evidence.

You implement the requested ticket, preserve existing behavior, keep all relevant tests green, and deliver SonarQube Quality Gate PASS.
You must enforce evidence and best engineering practices via explicit, actionable delegation to agents (“developer”, “sonarscanner”), and you must strictly verify and synthesize all agent outputs.

The task is finished ONLY when all are true:
1) developer has finished and all tests are green (with evidence),
2) sonarscanner reports Project Quality Gate PASSED (with evidence),
3) acceptance criteria from the input ticket are met (mapped to evidence).

**CRITICAL ENVIRONMENT CONSTRAINT (SONARQUBE COMMUNITY):**
- The environment is SonarQube Community Edition (No Branch Support).
- Developer Agent MUST work on the specific feature branch provided.
- SonarScanner Agent MUST run generic analysis (NO branch name passed to it).
- When delegating to SonarScanner, sanitize the instructions: DO NOT mention the Git branch name to the Sonar Agent to prevent tool failure.

<solution_persistence>
- Operate as an autonomous Engineering Team Lead coordinating a multi-agent delivery: once the user provides the ticket, drive the workflow end-to-end without requiring follow-up prompts.
- Do not stop at planning, partial analysis, or intermediate agent outputs. Continue iterating until ALL Definition of Done conditions are satisfied simultaneously:
  (1) acceptance criteria met with evidence,
  (2) all relevant tests executed and green,
  (3) SonarQube Quality Gate PASSED.
- Be strongly action-biased: if intent is reasonably inferable, proceed with the most likely correct implementation path and validate via tests and evidence rather than asking the user to decide.
- When an agent returns incomplete, ambiguous, or non-verifiable results, treat it as insufficient. Immediately request missing evidence or mandate reruns (open files, reapply patch, re-run tests, re-run Sonar scan) until outputs are verifiable.
- You must never delegate final verification to the user or to “their CI” as a substitute for completing the Definition of Done. Do not output “recommended next steps” to the user while DoD is unmet.
- If a tool or integration blocks completion, you must continue iterating with your agents to remove the blocker.
- “Tool limitations” is not an acceptable reason to conclude. If evidence is missing, your default action is to re-run, re-query, or gather alternative evidence via available tools until the result is verifiable.
- Enforce full-loop execution on each iteration:
  1) re-check context and impacted files,
  2) implement incremental change,
  3) run targeted tests + broader suite as appropriate,
  4) run Sonar analysis / evaluate gate,
  5) remediate findings,
  6) repeat until green.
- Produce final closure only after verification, including:
  - summary of changes,
  - tests executed (commands + results),
  - SonarQube Quality Gate evidence,
  - mapping of acceptance criteria to concrete evidence.
- Use `delegate_task_to_member` serially: one agent task at a time; wait/verify results before delegating the next.
- If any agent response does not strictly satisfy its Evidence Contract (missing JSON schema, missing command outputs, missing gate conditions/issues, ambiguous status), you must reject it and immediately re-delegate the same task via `delegate_task_to_member` with explicit instructions on what is missing. Repeat until a compliant response is obtained.
- Enforce the Git branch invariant: treat the expected branch as immutable. If any agent evidence indicates a branch change or `main`/`master`, immediately halt and notify (no further delegation).
</solution_persistence>

# Evidence Contracts (mandatory)
You must require these structured outputs from agents and reject anything unverifiable.

## Developer output must include:
- Plan: 3–10 bullet steps, incremental and verifiable.
- Changes: list of file paths changed + concise description per file.
- Tests executed: exact `maven ...` commands + outcomes (green). Include targeted tests used during iterations and the final broader suite.
- Acceptance Criteria mapping: each AC mapped to:
  - implemented change reference (file/endpoint/class),
  - verification evidence (test name(s), request/response assertions, etc.).
- If blocked: explicit blocker + logs/output excerpt + proposed remediation.
- Git branch evidence: expected branch name + current branch confirmation (must match and must not be `main`/`master`). If changes were made: commit + push confirmation.

## SonarScanner output must be strict JSON with one of:
- PASSED: { "quality_gate_status":"PASSED", ... }
- FAILED: includes gate conditions + gate-blocking issues (file/lines/rule/severity) + prioritized recommendations.
- BLOCKED: build failure evidence and developer remediation recommendation.

# Workflow

## 0) Intake and decomposition (Coordinator)
- Read the ticket fully and extract:
  - acceptance criteria (AC list),
  - constraints (compatibility, performance, non-goals),
  - required tests (unit/e2e),
  - risk areas (backwards compatibility, edge cases, validation).
- Define a verification plan: what evidence will prove each AC?
- Record the "expected branch" from the ticket input and treat it as an invariant for the entire run (must not be `main`/`master`).

## 1) Planning and implementation loop (Developer)
Delegate to developer with:
- the extracted AC list,
- explicit guardrails:
  - preserve existing endpoints/behavior,
  - minimal diffs,
  - no refactors unless required,
  - database-side filtering / performance constraints when applicable,
  - tests required by the ticket.
- Require the Developer Evidence Contract output.
- Git invariant: do not change branches; do not work on `main`/`master`; operate only on the ticket-provided expected branch. If mismatch is detected, stop and report immediately.

## 2) Verification gate to proceed to Sonar (Coordinator)
Before invoking sonarscanner, verify developer evidence:
- tests executed and green for latest state,
- AC mapping is complete and credible,
- no regressions indicated (existing endpoints preserved).

If any item is missing or weak, send developer back for remediation/evidence.

## 3) Static analysis and Quality Gate (SonarScanner)
Delegate to sonarscanner to:
- run `maven_sonar`,
- query Quality Gate,
- return strict JSON (PASSED/FAILED/BLOCKED).
- **IMPORTANT:** Do NOT include the branch name in this delegation message. Instruct the agent simply to "analyze the current code".

## 4) Remediation loop (Coordinator)
- If Sonar is PASSED: proceed to final closure checks.
- If Sonar is FAILED:
  - prioritize only gate blockers first,
  - delegate fixes to developer with explicit file/line/rule references,
  - require developer to rerun tests (targeted + final suite),
  - then rerun sonarscanner until PASSED.
- If Sonar is BLOCKED due to build failure:
  - delegate build fix to developer with the provided error excerpt,
  - require a green test run,
  - then re-run sonarscanner.

## 5) Final closure (Coordinator)
Only when all DoD conditions are met, produce a final report including:
- What was delivered (high-level summary),
- Acceptance Criteria → Evidence mapping,
- Tests executed (commands + results),
- SonarQube Quality Gate evidence (status + timestamp/id if available),
- Confirmation of compatibility (existing endpoints preserved).
    """


# ==============================================================================
# 3. SYSTEM UTILITIES
# ==============================================================================
def verify_dependencies() -> None:
    """Checks if required system CLI tools are installed."""
    required_tools = ["git", "mvn", "docker"]
    missing = [tool for tool in required_tools if shutil.which(tool) is None]

    if missing:
        logger.error(f"❌ Missing system tools: {', '.join(missing)}")
        logger.error("Please install them and ensure they are in your system PATH.")
        sys.exit(1)

    logger.info("✅ System dependencies verified (git, mvn, docker).")


def run_shell_command(cmd: List[str], cwd: Path = AppConfig.APP_DIR, tail_lines: int = 100) -> str:
    """
    Executes a shell command safely and returns the output.

    Args:
        cmd: List of command parts (e.g., ["mvn", "clean"]).
        cwd: Working directory for the command.
        tail_lines: Number of lines to return from the output (logs).
    """
    try:
        # Check if directory exists before running
        if not cwd.exists() and cmd[0] != "git":  # Git clone creates the dir, so skip check
            return f"Error: Directory {cwd} does not exist."

        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )

        output = result.stdout or ""
        lines = output.splitlines()

        # Get the last N lines for readability
        tail_text = "\n".join(lines[-tail_lines:]) if tail_lines > 0 else output

        if result.returncode != 0:
            return f"❌ Command Failed (Exit Code {result.returncode}):\n...{tail_text}"

        return tail_text

    except Exception as e:
        logger.warning(f"Exception while running command {cmd}: {e}")
        return f"System Exception: {e}"


# ==============================================================================
# 4. AGENT TOOLS
# ==============================================================================
@tool(description=f"Run Maven commands against the {AppConfig.APP_DIR} project")
def maven_tool(args: List[str], tail: int = 100) -> str:
    """
    Run Maven commands (e.g., clean, install, test).

    Args:
        args: List of Maven arguments.
        tail: Number of output lines to return (default: 100).
    """
    logger.info(f"🔨 Executing Maven: mvn {' '.join(args)}")
    return run_shell_command(["mvn", *args], tail_lines=tail)


@tool(description="Run Git commands")
def git_tool(args: List[str]) -> str:
    """Run Git commands (e.g., checkout, commit, push)."""
    logger.info(f"🌳 Executing Git: git {' '.join(args)}")
    return run_shell_command(["git", *args])


def execute_sonar_logic() -> str:
    """Helper function containing the actual SonarQube execution logic."""
    logger.info("🔍 Running SonarQube Analysis...")

    cmd = [
        "mvn", "-q", "clean", "verify",
        "org.sonarsource.scanner.maven:sonar-maven-plugin:sonar",
        f"-Dsonar.projectKey={AppConfig.SONAR_PROJECT_KEY}",
        f"-Dsonar.projectName={AppConfig.SONAR_PROJECT_KEY}",
        f"-Dsonar.host.url={AppConfig.SONAR_URL}",
        f"-Dsonar.token={AppConfig.SONAR_TOKEN}",
        "-Dsonar.qualitygate.wait=true",
    ]
    return run_shell_command(cmd, tail_lines=80)

@tool(description="Run Maven with SonarQube scanner")
def maven_sonar_tool() -> str:
    """Execute Maven build with SonarQube analysis and wait for quality gate."""
    # El agente llamará a esto
    return execute_sonar_logic()


# ==============================================================================
# 5. WORKFLOW STEP EXECUTORS
# ==============================================================================
def step_git_clone(step_input: StepInput) -> StepOutput:
    """
    Clones the repository.
    If the directory already exists, it is DELETED first to ensure a clean slate.
    """
    # 1. Check and Clean existing directory
    if AppConfig.APP_DIR.exists():
        logger.info(f"♻️  Existing directory {AppConfig.APP_DIR} detected. Removing it for a fresh clone...")
        try:
            # shutil.rmtree removes the directory and all its contents recursively
            # ignore_errors=True avoids crashing on minor permission issues (optional but recommended for students)
            shutil.rmtree(AppConfig.APP_DIR, ignore_errors=True)

            # Double check if it was removed, sometimes file locks (Windows) delay deletion
            if AppConfig.APP_DIR.exists():
                return StepOutput(
                    content=f"❌ Error: Could not delete existing directory {AppConfig.APP_DIR}. Check file permissions.",
                    step_name="git_clone")

        except Exception as e:
            logger.error(f"❌ Failed to remove directory: {e}")
            return StepOutput(content=f"Error removing directory: {e}", step_name="git_clone")

    # 2. Proceed with Clone
    logger.info(f"📥 Cloning {AppConfig.GIT_REPO_URL}...")

    # Clone into the specific directory, running from parent dir
    result = run_shell_command(
        ["git", "clone", AppConfig.GIT_REPO_URL, str(AppConfig.APP_DIR)],
        cwd=Path(".")
    )

    # Check result string for common git errors if exit code wasn't enough context
    success = "fatal" not in result.lower()

    return StepOutput(
        content=f"Clone Result: {result}",
        step_name="git_clone"
    )


def step_baseline_analysis(step_input: StepInput) -> StepOutput:
    """Runs an initial Sonar analysis to establish a baseline."""
    logger.info("📊 Running Baseline Analysis (Direct Execution)...")

    result = execute_sonar_logic()

    return StepOutput(content=result, step_name="baseline_analysis")

# ==============================================================================
# 6. MAIN PIPELINE ORCHESTRATION
# ==============================================================================
async def run_development_pipeline(task_description: str) -> None:
    """
    Orchestrates the full development lifecycle using AI Agents.
    """

    # 1. Check dependencies
    verify_dependencies()

    logger.info("🚀 Starting Development Pipeline...")

    # 2. Configure MCP Tools
    # ... (Configuración de Docker igual que antes) ...
    sonar_cmd = (
        f'docker run -i --network=host '
        f'-e SONARQUBE_URL="{AppConfig.SONAR_URL}" '
        f'-e SONARQUBE_TOKEN="{AppConfig.SONAR_TOKEN}" '
        f'--rm mcp/sonarqube'
    )

    fs_cmd = (
        f'docker run -i --rm '
        f'--mount "type=bind,src={AppConfig.APP_DIR},dst={AppConfig.APP_DIR}" '
        f'mcp/filesystem {AppConfig.APP_DIR}'
    )

    sonarqube_mcp = MCPTools(command=sonar_cmd)
    filesystem_mcp = MCPTools(command=fs_cmd)

    await sonarqube_mcp.connect()

    try:
        # 3. Initialize Agents
        branch_agent = Agent(
            name="Branch Manager",
            model=OpenAIChat(id=AppConfig.GENERIC_MODEL_ID, reasoning_effort="high"),
            tools=[git_tool],
            system_message=AgentPrompts.BRANCH_MANAGER,
            debug_mode=True,
        )

        developer_agent = Agent(
            name="Developer",
            model=OpenAIChat(id=AppConfig.GENERIC_MODEL_ID, reasoning_effort="high"),
            tools=[filesystem_mcp, maven_tool, git_tool],
            system_message=AgentPrompts.DEVELOPER,
            debug_mode=True,
        )

        sonar_agent = Agent(
            name="SonarScanner",
            model=OpenAIChat(id=AppConfig.GENERIC_MODEL_ID, reasoning_effort="high"),
            tools=[maven_sonar_tool, sonarqube_mcp],
            system_message=AgentPrompts.SONAR_ANALYST,
            debug_mode=True,
        )

        dev_team_lead = Team(
            name="Development Lead",
            model=OpenAIChat(id=AppConfig.COORDINATOR_MODEL_ID, reasoning_effort="high"),
            members=[developer_agent, sonar_agent],
            system_message=AgentPrompts.TEAM_LEAD,
            debug_mode=True,
        )

        def step_prepare_branch_task(step_input: StepInput) -> StepOutput:
            """Prepares the prompt for the Branch Manager using the outer task_description."""
            # We access task_description directly from the parent function scope
            return StepOutput(
                content=f"Analyze this task and create a branch: {task_description}",
                step_name="prepare_branch_task"
            )

        def step_prepare_dev_context(step_input: StepInput) -> StepOutput:
            """Combines the branch info (from previous step) with the outer task_description."""
            branch_output = step_input.previous_step_content

            prompt = f"""
CONTEXT:
- Repository: {AppConfig.GIT_REPO_URL}
- Active Branch: {branch_output} (Created in previous step)

TASK:
\"\"\"{task_description}\"\"\"

INSTRUCTIONS:
Please implement the task described above on the active branch.
            """
            return StepOutput(
                content=prompt,
                step_name="prepare_dev_context"
            )

        # ------------------------------------------------------------------

        # 5. Define Workflow Steps
        dev_workflow = Workflow(
            name="Java Feature Delivery Pipeline",
            steps=[
                Step(name="Setup: Clone Repo", executor=step_git_clone),
                Step(name="Setup: Baseline Analysis", executor=step_baseline_analysis),
                Step(name="Plan: Prepare Branch Task", executor=step_prepare_branch_task),
                Step(name="Plan: Create Branch", agent=branch_agent),
                Step(name="Plan: Prepare Dev Context", executor=step_prepare_dev_context),
                Step(name="Execute: Development Team", team=dev_team_lead)
            ],
            debug_mode=True
        )

        # 6. Execute Workflow
        print("\n" + "=" * 60)
        print("🤖 AGENTIC WORKFLOW STARTED")
        print("=" * 60 + "\n")

        await dev_workflow.aprint_response(input=task_description)

    finally:
        await sonarqube_mcp.close()
        logger.info("🏁 Pipeline execution finished. Resources released.")


# ==============================================================================
# ENTRY POINT
# ==============================================================================
if __name__ == "__main__":
    # Example Task (Ideally loaded from a file or user input)
    TASK_PAYLOAD = """
# Ticket: Bikes Pagination & Search

## Context / Goal
Enable a **paginated, sortable, and filterable** listing endpoint for bikes without breaking existing endpoints. The goal is to avoid loading full datasets into memory and provide an efficient API for clients to explore the list.

## Scope
- **New read-only endpoint**: `GET /bike/search`
- **Compatibility**: do not change behavior of existing endpoints.
- **Search**: free-text across multiple fields + field-based filters.
- **Standard pagination & sorting** via `page`, `size`, `sort`.
- **Paginated response** with page metadata.

---

## Functional Requirements

### Endpoint
`GET /bike/search`

### Query Parameters
All parameters are optional and can be freely combined.

**Free-text search**
- `q` *(string)*: case-insensitive term applied to `ownName`, `bikeNo`, `brand`, `model`, `status`.

**Specific filters**
- `ownName` *(string, contains)*
- `bikeNo` *(string, contains)*
- `brand` *(string, contains)*
- `model` *(string, contains)*
- `inProcess` *(boolean)*: `true|false`
- `success` *(boolean)*: `true|false`
- `handOver` *(boolean)*: `true|false`
- `dateFrom` *(string, format `yyyy-MM-dd`)*: lower bound (inclusive) applied to `dateOfAppointment`.
- `dateTo` *(string, format `yyyy-MM-dd`)*: upper bound (inclusive) applied to `dateOfAppointment`.

> Note: `dateOfAppointment` is currently stored as a **String** with format `yyyy-MM-dd`. Range comparison should respect this (lexicographic). A future change to `LocalDate` should not alter the endpoint contract.

**Pagination & sorting**
- `page` *(int, ≥0)*: default `0`
- `size` *(int, 1..100)*: default `10`
- `sort` *(string)*: one or more `field,direction` pairs (e.g., `sort=bookAt,desc`); default **`bookAt,desc`**  
  - Allowed sort fields: `bookAt`, `dateOfAppointment`, `ownName`, `brand`, `model`, `bikeNo`, `status`.

### Response
Standard paginated object containing:
- `content`: array of `Bike`
- `totalElements`, `totalPages`, `number` (current page), `size`, `first`, `last`, `sort`, etc.

**Response example (trimmed):**
```json
{
  "content": [
    {
      "bikeId": "id1",
      "ownName": "Alice",
      "mobile": "5551234",
      "bikeNo": "BIKE123",
      "brand": "Honda",
      "model": "CBR",
      "bookAt": "2025-11-08T09:30:12.123+00:00",
      "dateOfAppointment": "2025-11-20",
      "description": "Regular servicing",
      "inProcess": false,
      "success": false,
      "status": "wait upto 2025-11-20",
      "handOver": false
    }
  ],
  "totalElements": 1,
  "totalPages": 1,
  "number": 0,
  "size": 10,
  "first": true,
  "last": true,
  "sort": { "sorted": true, "unsorted": false, "empty": false }
}
```

### Usage Examples
- Free-text + pagination:  
  `GET /bike/search?q=honda&page=0&size=5&sort=dateOfAppointment,asc`
- Flag filters:  
  `GET /bike/search?inProcess=true&success=false&handOver=false&size=20`
- Date range:  
  `GET /bike/search?dateFrom=2025-01-01&dateTo=2025-12-31`
- Combined:  
  `GET /bike/search?brand=yamaha&model=mt&q=servicing&success=true&sort=bookAt,desc`

### Validation & Errors
- If `dateFrom` or `dateTo` is not `yyyy-MM-dd` → **400 BAD_REQUEST** with body:
  ```json
  { "error": "Validation Failed", "message": "Invalid date format. Use yyyy-MM-dd" }
  ```
- If a boolean cannot be parsed (e.g., `inProcess=maybe`) → **400 BAD_REQUEST** with a clear message.
- If `size` is outside the allowed range → **400 BAD_REQUEST**.
- Must **not** return 200 with the full list when invalid params are supplied.

### Business Rules
- If no filters are provided, the endpoint returns **all bikes, paginated**.
- `q` is **case-insensitive** and does a `contains` match on the specified fields.
- Specific filters are combined with **AND**; `q` is applied additionally.
- Filtering must be executed **in the database** (not `findAll()` + in-memory filtering).

### Compatibility
- Do **not** modify or remove existing endpoints (`/bike`, `/bike/{id}`, etc.).
- This endpoint is **additive**.

---

## Non-Functional Requirements
- Efficient and scalable queries; recommended DB indexes on: `bikeNo`, `ownName`, `brand`, `model`, `dateOfAppointment`.
- Deterministic default ordering (`bookAt,desc`) when `sort` is not provided.
- CORS policy should remain consistent with the current controller behavior.

---

## Acceptance Criteria
1. **Basic pagination**  
   Given more than 10 bikes, when calling `GET /bike/search?page=0&size=10`, then `content` contains 10 items and `totalElements`/`totalPages` are coherent.

2. **Default ordering**  
   When `sort` is not provided, results are ordered by `bookAt,desc`.

3. **Free-text search**  
   Given bikes with `brand="Honda"` and `model="CBR"`, when calling `GET /bike/search?q=cbr`, results include matches by `model` (case-insensitive).

4. **Combined filters**  
   When calling `GET /bike/search?brand=honda&inProcess=false&handOver=false&success=true`, only bikes satisfying **all** those filters are returned.

5. **Date range**  
   Given bikes with different `dateOfAppointment` values, when calling `GET /bike/search?dateFrom=2025-01-01&dateTo=2025-12-31`, only bikes within the inclusive range are returned.

6. **Validation**  
   When calling `GET /bike/search?dateFrom=2025/01/01`, the response is **400** with `{ "error":"Validation Failed", "message":"Invalid date format. Use yyyy-MM-dd" }`.

7. **No regression**  
   `GET /bike` continues to return the full (non-paginated) list as before.

---

## Required Tests
- **Unit tests**
  - Cover search/filter logic (combinations of `q`, specific filters, ranges, sorting).
  - Validation cases (date format, invalid booleans, `size` outside allowed range).
  - Verify filtering is executed via database queries (not in-memory).

- **E2E tests**
  - Seed data to cover: free-text search, flag filters, date ranges, pagination, and sorting.
  - Verify page metadata (`totalElements`, `totalPages`, `number`, `size`) and default ordering.

---

## Deliverables
- New endpoint `GET /bike/search` working as specified.
- Validation & error handling aligned with the existing `GlobalExceptionHandler`.
- **Unit tests** and **E2E tests** passing.
    """

    asyncio.run(run_development_pipeline(TASK_PAYLOAD))