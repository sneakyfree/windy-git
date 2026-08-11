# patches/ — Gitea source patches (I-1)

EMPTY, and it should stay that way.

Windy Git runs STOCK Gitea and builds beside it against its REST API (D-2).
Any patch here must be a numbered, rebasable diff with a one-line justification.

**`make check` fails if this directory holds more than 3 patches without an ADR
naming the decision it overturns.** A hard fork requires a written list of the
specific files that must change and why an API cannot reach them.
