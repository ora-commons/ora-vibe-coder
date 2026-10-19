Output only the supplied validation boundaries and one section for every root
in the protected requested-root list, in that list's order:

{{VALIDATION_BEGIN}}
## <EXACT ROOT ID> — ACCEPT|REJECT

### BEHAVIOR
[nonempty substantive behavior judgment]

### MECHANISM
[nonempty mechanism judgment]

### EVIDENCE
[nonempty concrete evidence]

### LIMITATIONS
[nonempty limitations statement]

[repeat the complete section once for each remaining requested root]
{{VALIDATION_END}}

Use each exact requested root ID once and only once. Do not add a preamble,
epilogue, unrequested root, duplicate root or field, empty field, aggregate
summary, or `VERDICT: PASS|FAIL`. Do not alter either supplied boundary.
