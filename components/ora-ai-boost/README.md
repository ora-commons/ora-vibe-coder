# Ora AI Boost

Sharper, more reliable AI work, with less flattery, hallucination, and drift.

Ora AI Boost is a performance turbo-charger for AI coding and writing work. It wraps your
request in an adversarial review pipeline, so the answer you keep has already been
challenged and corrected: greater reliability and intelligence, with less sycophancy and
flattery, less hallucination, and less drift away from what you actually asked.

It is one of the Ora products — see Ora at https://ora-ai.app. The sibling products are
Ora Agent Bridge (https://github.com/ora-commons/ora-agent-bridge), Ora Programming Loop
(https://github.com/ora-commons/ora-programming-loop), and Ora Vibe Coder
(https://github.com/ora-commons/ora-vibe-coder).

It is a tool for getting better answers — not a benchmark, and not a promise to eliminate
errors. Adversarial review catches defects; it does not guarantee correctness.

The Python package is `ora-adversarial-review`. It installs three commands:

- `ora-gear-3` — one strong answer, hardened by a fresh adversarial review. It produces
  or accepts one complete answer, gives it a fresh adversarial review, and revises it
  when the review finds a material defect.
- `ora-gear-4` — two independent answers, cross-reviewed and combined. It creates blind
  Depth and Breadth answers, cross-reviews them against each other, consolidates both,
  and independently reviews the complete synthesis.
- `ora-validator` — a strict outside check you can rely on. It sends one exact
  validation request to one explicit external peer and accepts the result only when
  that peer directly supplies one strict `ACCEPT` or `REJECT` decision for every
  explicitly named root.

Gear one-pass is the default; `--consensus` is capped at three reviews and two
revisions. A run returns the latest complete deliverable when one exists, and keeps
status and the human-readable `RUN.md` record path outside the answer. The editable
Markdown method and small standard-library Python runner are standalone from any other
Ora product; the validator has one strict external-call result contract instead.

## Install on a clean setup

You need Python 3.10 or later and `git`. Clone the public repository at the release tag
and install into a virtual environment. In a POSIX shell:

```sh
git clone --branch v0.5.0 https://github.com/ora-commons/ora-adversarial-review.git
cd ora-adversarial-review
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
```

This installs all three commands plus their role Markdown as a packaged copy. Nothing
from any private repository or personal setup is needed. Repeat
`python -m pip install .` from a checkout to update it; an in-progress invocation keeps
its starting instruction snapshot.

## One working use of each command

Write a small request file with an exact, self-contained question:

```sh
printf 'What is 17 * 23? Give the number, then one sentence of reasoning.\n' > /tmp/request.md
```

Run Gear 4 (two independent answers, cross-reviewed, consolidated):

```sh
ora-gear-4 --request /tmp/request.md
```

Run Gear 3 (one answer, adversarially reviewed and revised when needed):

```sh
ora-gear-3 --request /tmp/request.md
```

Run the validator with explicitly named roots and an outside peer (the Bridge
prerequisite is described below):

```sh
printf 'Claim A: 17 * 23 = 391.\nClaim B: 17 * 23 = 392.\nDecide ACCEPT or REJECT for each claim.\n' > /tmp/validation.md
ora-validator --request /tmp/validation.md --root claim-a --root claim-b --peer zcode
```

`zcode` is the peer ID passed to Agent Bridge; use an ID your Bridge checkout supports.
On success the validator prints a trusted wrapper with the peer's exact decisions. A
well-formed, substantive `REJECT` is a completed result, not a failure.

## Check the installed version, update, remove

Check the installed version:

```sh
python -m pip show ora-adversarial-review
```

Update to a newer release by fetching tags, checking out the new tag, and reinstalling:

```sh
cd ora-adversarial-review
git fetch --tags
git checkout v0.2.1   # replace with the newest release tag
python -m pip install .
```

Remove it by uninstalling the package in that environment, then deleting the virtual
environment and the clone if you want:

```sh
python -m pip uninstall ora-adversarial-review
```

If you copied host skill entries from `packages/`, remove only those copied Gear skill
directories. Run records under `~/.ora-adversarial-review/runs/` are user-owned output;
delete them manually if you wish.

## Problems and support

Report problems at https://github.com/ora-commons/ora-adversarial-review/issues —
include the command, the `RUN.md` record path it printed, and your platform. That issue
tracker is the only support route; no other support is offered or promised. If a
release proves defective, its guidance there directs you to a known usable version, and
older releases stay reachable.

## Prerequisites: the AI engine

Gear 3 and Gear 4 name their native engine with `--native`; all six tools are
selectable for the primary analytical role:

- `codex` is the compatible default. Gear starts a fresh ephemeral read-only
  `codex exec` call for every native role. `--codex-model` and `--codex-effort`
  name the model and reasoning effort for every Codex call, passed to
  `codex exec` as `-m` and one `model_reasoning_effort=` override; with none
  named, Codex's own default applies. Each run record states the model and
  reasoning effort Codex reports using, read from the start-up lines of its
  own output.
- `claude` is selected with `--native claude`. Gear calls Claude Code directly through
  its ordinary subscription route; Agent Bridge is not involved in native roles. Each
  call is fresh, non-persistent, restricted to no model tools, and run in a temporary
  neutral directory.
- `zcode`, `hermes`, `qwen`, and `minimax` are selected with `--native TARGET`. Gear
  runs every native role as a fresh text-only analytical call to that exact target
  through the Agent Bridge review transport. These are analytical roles only: Gear
  claims and implements no project-editing work mode for them. Hermes and Qwen have
  no project-editing work mode in Bridge, and Gear does not invent one.

An unavailable selected engine is reported with its readiness failure and the
selectable alternatives; Gear never silently substitutes Codex, Claude, or another
vendor for the participant you chose.

No analytical call — native or peer — has an elapsed-time cutoff. Work ends on
completion, explicit cancellation, or a real terminal error; only readiness
checks and cleanup stay bounded.

The validator has no native role at all: it is external-only and always requires a
peer. `--model` is valid only with `--native claude` and pins either accepted Fable
selector:

```text
ora-gear-3 --request /absolute/path/request.md --native claude --model fable
```

`--codex-model` and `--codex-effort` are valid wherever Codex serves — with
`--native codex` or `--peer codex` — and reach every Codex call the run makes:

```text
ora-gear-3 --request /absolute/path/request.md --native codex --codex-model gpt-5.3 --codex-effort high
```

The same selected native adapter, model selector, and any named Codex model or
effort are retained for every native producer, reviewer, reviser, lane,
consolidation, technical retry, peer-failure recovery, and the labelled Gear
4-to-Gear 3 fallback. Gear never changes engine or model silently.

Every successful Claude call must return one unambiguous effective model in its JSON
`modelUsage`; a selected Fable alias must match it. Gear records every exact model in
`RUN.md`, reports the last after successful completion, and uses the JSON `result`
text unchanged; anything missing, ambiguous, or mismatched is a bounded technical
failure. This route is implemented but not live-qualified: no live Claude or Fable
model call has been made.

## Exact input

The original request is protected data. Read it from a UTF-8 file:

```text
ora-gear-3 --request /absolute/path/request.md
ora-gear-4 --request /absolute/path/request.md
```

Or pipe exact bytes on standard input. Gear never cleans, summarizes, or reconstructs
protected material. Repeated `--later-user`, `--assistant-context`, and `--context`
files remain separate exact blocks; later user corrections control conflicts without
turning assistant or stage artifacts into user instructions or established facts.

Gear 3 accepts `--current-answer FILE` for "review this answer." Gear 4 uses analytical
Breadth unless `--breadth committed --commitment FILE` is explicitly selected; the
commitment file must contain the user's own nonempty words.

### Global instruction master (optional)

Every Gear 3 and Gear 4 packet leads with the universal core rules read from your
global instruction master — an optional Markdown file you select with the
`ORA_INSTRUCTION_MASTER` environment variable or provision at the default path
`~/.config/ora/global-instructions.md`. The file must carry exactly one
`<!-- ORA-CORE-BEGIN -->` and `<!-- ORA-CORE-END -->` marker pair around a nonempty
core. A selected or provisioned master that is missing, unreadable, or malformed
stops the run with an error naming the file. With no master configured at all, the
run still works: every packet carries the role instructions only, and the notices
and the run record disclose that. The validator is unchanged and carries no
instruction prefix.

Three further options carry instructions into every Gear packet.
`--turn-instructions-file FILE` forwards this turn's original user message verbatim —
use it when the current message carries instructions for this turn, and omit it when
it does not. `--repository PATH` names the target repository or task worktree, whose
complete AGENTS.md, imports expanded, joins every packet; repeatable
`--assigned-path PATH` adds the narrower AGENTS.md rules covering those paths and
requires `--repository`.

The validator requires a file, explicit safe root IDs, and a peer. It neither reads
standard input nor infers roots, and never accepts `--native` or `--model`.

## Outside review through Agent Bridge

Without `--peer`, every Gear role is a fresh selected-engine call. That proves context
separation, not different evidence, training, models, or blind spots; diversity is
claimed only when independently established.

`--peer TARGET` passes one user-selected ID unchanged to Agent Bridge for peer-owned
roles. Bridge owns readiness. On failure, Gear shows it exactly and then uses the
already selected native engine and model; it never chooses another peer or provider.
Only Gear falls back — Gear 4 does so loudly, with the status line
`GEAR 4 UNAVAILABLE — GEAR 3 FALLBACK`. The validator ends without certification on
readiness, transport, shape, root-set, or provenance failure, and certifies only the
one bounded decision body.

External operation requires the frozen Bridge Format 2 checkout at `AGENT_BRIDGE_HOME`
or `~/agent-bridge`, and a signed-in tool for the peer you name. When
`AGENT_BRIDGE_HOME` is set, that exact copy is used: an invalid selected path fails
naming that path, and never falls back to another installation such as
`~/agent-bridge`. With no selection, the documented standalone default
`~/agent-bridge` is used. Every run reports the Bridge copy actually used, by path
and version, beside the readiness line. Gear invokes
`-m ora_agent_bridge` through its own Python, omits `Project:`, and has no Format 1
path.

Gear surfaces all Bridge readiness and limitation warnings outside the answer.
Bridge chooses neither engine, model, nor effort itself; when Codex serves as the
outside reviewer through Bridge, Gear passes the same named Codex model and
reasoning effort to Bridge's call, and the run record takes the requested and
recorded values the reply reports. Qwen alone may
preprocess `@` references or leading `/` commands before model input, so only Bridge's
packet record is promised for that target.

## Records and output

For Gear 3 and Gear 4, standard output contains only the complete current answer
bytes. Standard error carries configuration, the selected native engine and model
selector where applicable, route and readiness, status, notices, the verified final
Claude model attribution after success, and the run-record path; every successful
Claude-native role also has its own exact attribution in the record, and every
successful Codex-native role states the model and reasoning effort Codex reported
for that call.

Validator failure leaves stdout empty; success contains its trusted wrapper and the
exact peer decisions. Runs are recorded under
`~/.ora-adversarial-review/runs/<run-id>/RUN.md`.

## Host entries

Optional thin host entries are under `packages/codex/` and `packages/claude/`; they
invoke the installed commands without copying the method or runner. Claude entries
select `--native claude` by default and Codex entries keep the Codex default; each
passes the caller's explicit engine choice through unchanged. A host installer may
place the chosen entry in its normal skill directory; the initiating host remains
distinct from the engine named by `--native`.

## Tested scope

Ora AI Boost was qualified on macOS (arm64) with Codex as the native engine and ZCode
as the outside reviewer through Agent Bridge. This release is checked against Ora
Agent Bridge 1.5.0 and its `python3 -m ora_agent_bridge` command; the Codex
model/effort selection and the Bridge reply reporting are exercised with fake
executables and fake Bridge replies, and no live model call was made for them. The
Claude Code route is implemented but not live-qualified. Other platforms, engines,
and peers are not thereby qualified.

## Contract and licence

[`SPECIFICATION.md`](SPECIFICATION.md) is the product contract and bounded plan.
First-party files use CC0 1.0 Universal; see [`LICENSE`](LICENSE) and
[`NOTICE`](NOTICE). Unbundled CLIs and Agent Bridge retain their own terms.
