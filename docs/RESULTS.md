# Measured results

Model: Groq `openai/gpt-oss-120b`, prompt v2.1, runner: isolated process. Raw files are in `eval/results/`.
Hidden tests were written and reference-checked by the team. They never enter prompts, retrieval or repair.

## Holdout (20 frozen tasks, v1): `eval/results/holdout-groq-20261028-132933.json`

| | Direct single prompt | SnipForge pipeline |
|---|---|---|
| Functional success (all hidden tests pass) | **20/20** | **20/20** |
| First attempt | 20/20 | 19/20 |
| Syntax valid | 100% | 100% |
| By category (text / list-dict / numeric / CSV-business) | 5/5 each | 5/5 each |
| Avg model calls | 1.0 | 3.3 |
| Avg latency | 2.3 s | 21.7 s |

- **Target ≥ 16/20 (80%): met by both.**
- `parse-duration`: the pipeline's first draft failed the hidden tests. Its own contract-derived tests caught the bug,
  and one code-only repair fixed it. That's the repair loop working on a real, unseeded failure.
- 6 tasks triggered a repair (4 calls) even though the first draft already passed the hidden tests: the pipeline's own
  tests disagreed with the draft on a detail the hidden tests don't check. The final code still passed every hidden test.
- **Interpretation:** a model this strong already solves small, well-specified functions from one prompt. The pipeline
  costs about 3× the calls and about 9× the latency, and adds no accuracy *on this benchmark*. Its value is the evidence
  and the workflow (contract, clarification, independent tests, requirement-level evidence, isolated execution,
  challenge, revisions, mutation testing), not raw pass rate.

## Development set (10 tasks, used for prompt tuning; not a holdout)

| Run | Direct prompt | Pipeline |
|---|---|---|
| prompt v2.0 | 10/10 | 3/10 (5 lost to HTTP 429 rate limits; 1 renamed function; 1 bad repair) |
| v2.1: binding names, best-attempt selection, 429 retry + key rotation | — | 9/10 (1 dropped connection, now retried) |

## Not yet measured
- Small/local models (e.g. Llama 3.2 3B, Qwen 2.5 Coder via Ollama), where the pipeline is most likely to add accuracy.
- Relevance checklist scoring by a teammate.
