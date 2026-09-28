# Agent workflow

This is the exact workflow text supplied for this project.

```text
Astra Medium – Build / Orchestrate

Prompt outline:

Execute the approved plan. Start with shared dependencies/contracts before parallelizing work.
Maintain architectural consistency, run validation as you go, and delegate only clearly bounded independent tasks.
Stop at the next agreed checkpoint and summarize progress, deviations, decisions, risks, tests, and Git state.

If independent work exists

Terra Medium – Feature Workers

Prompt outline:

Implement this bounded workstream: [FEATURE]. Follow AGENTS.md and the approved architecture. Stay within [FILES/SCOPE].
Do not change shared architecture or interfaces unless necessary; escalate instead. Run relevant tests and return a concise summary of changes,
assumptions, failures, and anything the integrator needs to know.

Workers finish

Astra Medium – Integrate

Prompt outline:

Integrate the completed workstreams into the main system. Review their diffs and assumptions, resolve conflicts and duplicated abstractions,
verify shared interfaces, run the full relevant test/build/typecheck suite, and fix cross-feature issues. Do not expand scope unnecessarily.
Stop at the next checkpoint with status, deviations, risks, and Git state.
```

The build coordinator owns shared contracts and integration. Feature workers only change the files assigned to their workstream. Each checkpoint reports implementation status, deviations from the approved specification, unresolved risks, validation performed, and `git status`.
