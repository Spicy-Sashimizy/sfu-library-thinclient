# deployprep host-action queue (2026-07-16)

Protocol: GLM appends `## REQ-<n>` blocks (status: PENDING); the host monitor
flips status to RUNNING/DONE/REJECTED with timestamp + evidence, output in
`_deployprep_hostreq_<n>.log`. See `docs/infrastructure/HEADLESS_GLM_DRIVE_RUNBOOK.md`.

Owner constraints in force: NO demo deployment, NO DigitalOcean spend, NO
TrueNAS access, NO served-default flips without owner approval.
