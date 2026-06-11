# Retry: ticket {{TICKET_ID}} — attempt 2 of 2

Your previous implementation of **{{TICKET_ID}}** FAILED verification. This is the final
retry; the orchestrator will mark the ticket `blocked` if it fails again.

## Why it failed (inject verbatim)
### Reviewer findings
{{REVIEW_FAILURE}}

### Tester findings
{{TEST_FAILURE}}

### Security gate findings (if any)
{{SECURITY_FAILURE}}

## Instructions
- Same single-writer rules as before: worktree only, no commit, no push.
- Address EVERY finding above. Do not regress passing behavior.
- Return the same structured summary format, with a `### FIX_NOTES` section explaining how
  each finding was resolved.
