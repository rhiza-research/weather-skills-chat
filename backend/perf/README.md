# Event-loop performance tests

The backend serves every request, socket event and background job from one
asyncio event loop per worker. Anything synchronous that runs on that loop (a
database query, a JuiceFS call, a long CPU step) makes every other user wait,
and a long enough stall fails the 1-second `/health` liveness probe, which
restarts the pod. These tests measure how long realistic scenarios hold the
loop, and fail when a scenario holds it longer than its budget.

They live here, apart from `backend/open_webui/test`, so that
`scripts/perf_compare.py` can run the same scenarios against an older checkout
of the app.

## How a test works

1. **Production-like I/O.** Locally a query or a `stat` takes microseconds, so
   blocking the loop with one costs nothing. `perf_harness.io_delay` puts a
   real `time.sleep` inside the synchronous call: on the loop it stalls the
   loop, on a worker thread only that thread waits.
   - `db_delay()` sleeps before every SQL statement on any SQLAlchemy engine.
   - `fs_delay(roots)` slows `os` path calls and `open()` for paths under
     `roots` only, so pytest and the SQLite file keep local speed.
2. **A loop probe.** `perf_harness.LoopProbe` wakes every 5 ms and records how
   late each wake-up is. Lateness is time the loop spent on something else.
3. **A scenario** drives the app through interfaces that exist across versions:
   routes through `httpx.ASGITransport` (so `def` routes run in the threadpool
   as in production), built-in tools, `process_chat_response` with a fake model
   stream, the runner pack push with a fake runner.
4. **Report and budget.** `record()` prints the numbers and saves them for the
   comparison script. `check_budget()` fails the test above its limit.

### Metrics

| Metric | Meaning |
|---|---|
| max stall | Longest single time the loop could not serve anything else. This is what fails `/health`. |
| p99 stall | The tail other users feel. |
| loop blocked | Time spent in stalls over 2 ms, as a share of the run. Shorter lateness is timer jitter. |

Lateness includes time the loop thread waits for the GIL while worker threads run
Python, so moving CPU-heavy work to a thread lowers it but does not remove it.
The probe also runs a garbage collection before measuring, so objects left by
earlier tests are not collected mid-measurement.

### Calibration

From production `chat-timing` logs (2026-10-21):

| Delay | Value | Evidence |
|---|---|---|
| SQL statement | 4 ms | Small lookups average 4-5 ms in prod (`db.Models.get_model_by_id`, 882 calls, 4.6 ms). |
| JuiceFS metadata call | 0.35 ms | `juicefs.chat_sandbox` makes ~26 metadata calls in 9.4 ms on average. |
| JuiceFS file open | 1 ms | With both values, listing a 753-entry sandbox takes about as long as prod's 2.1 s. |
| Langfuse export | 55 ms and 200 ms | `client.flush()` waits for the HTTP export. From the staging pod, an export to Langfuse Cloud takes 55 ms when small and 357 ms for 900 KB. Each generation exports its input; prod requests were 439 KB at the median, about 200 ms. |

Model streams arrive as one buffered burst: the case that never yields.

## Scenarios

| Test | Reproduces |
|---|---|
| `test_artifact_listing.py` | Recent-chats artifact prefetch burst (prod restart 07:26 UTC, 2026-10-21); the `list_artifacts` tool on a 753-entry sandbox. |
| `test_langfuse_flush.py` | A 38-round traced agent turn, with small and median-size Langfuse exports. |
| `test_runner_pack_push.py` | A runner start pushing 9 skill packs from JuiceFS. |
| `test_access_checks.py` | Message events, chat actions and tool calls checking access on a 1.5 MB chat. |
| `test_stream_reply.py` | The final reply of a 38-round agent turn, streamed as a buffered burst (prod restart 16:39 UTC, 2026-10-21). |

Costs these scenarios show are still on the loop:

- Routes that return a whole chat: FastAPI validates and serializes an `async def`
  route's response on the loop (`test_chat_actions_on_a_large_chat`).
- `chat_sandbox()` creates and re-owns the sandbox folders on JuiceFS on every
  path lookup, on the loop in the built-in tools (`test_tool_calls_on_a_large_chat`).

## Running

Like the backend unit tests, from the repository root:

```bash
PYTHONPATH=backend:backend/open_webui uv run python -m pytest backend/perf -s
```

`-s` prints each scenario's numbers.

### Comparing revisions

```bash
uv run python scripts/perf_compare.py <old-rev> <new-rev>
uv run python scripts/perf_compare.py --runs 3 origin/dev HEAD -- -k stream
```

Each revision is checked out into a temporary worktree and the tests in your
checkout run against its app code. Budgets are not enforced there. The script
prints a markdown table; with `--runs N` each value is the median.

## Performance PRs

A PR that aims to make the backend faster or keep the loop free:

1. Adds or extends a scenario here that reproduces the slow path with
   production-like delays. Reuse `perf_harness`; add a delay helper if a new
   kind of I/O is involved, with its calibration in the table above.
2. Sets a budget that the old code fails and the new code meets with margin:
   CI runners are slower than a laptop and the numbers vary from run to run.
3. Runs `scripts/perf_compare.py <base> <branch>` and puts the table in the PR
   description.
