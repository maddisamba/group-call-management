# Radio Group Call Management API

A small REST service that simulates the **floor control** part of a radio
group call system (push-to-talk). Radios in the same group share one
"floor": only the user who holds the floor may transmit. This service
manages who holds the floor for each group — obtaining it, releasing it,
timing it out, and keeping a history of every hold.

> **In plain words:** imagine a walkie-talkie channel where only one person
> can speak at a time. This program is the referee. It decides who gets to
> speak, makes them give up the microphone after 10 seconds, lets someone
> with higher priority take the microphone away, and writes down who spoke
> and when.

Built with **Python 3.12 / FastAPI**, fully covered by automated tests.

## Features

| Feature | Status |
|---|---|
| Obtain / release the floor (core challenge) | ✅ |
| Floor timeout — auto-release after **10 seconds** (bonus) | ✅ |
| Current floor holder endpoint (bonus) | ✅ |
| Prioritized requests — preempt the current holder (bonus) | ✅ |
| Audit endpoint — full hold history (bonus) | ✅ |
| CI — GitHub Actions runs the test suite on every push (bonus) | ✅ |
| Kubernetes deployment manifests (bonus) | ✅ |

## API overview

Once running, interactive documentation is served at
**http://localhost:8080/docs** (Swagger UI, generated from the OpenAPI spec).

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/groups/{groupId}/floor` | Obtain the floor. Body: `{"userId": "user-1", "priority": false}` |
| `DELETE` | `/groups/{groupId}/floor/{userId}` | Release the floor |
| `GET` | `/floor/holder/{groupId}` | Who currently holds the floor for a group |
| `GET` | `/audit` | History of every hold: who, which group, when obtained, when released |

Example session with `curl`:

```bash
# user-1 takes the floor for group-alpha
curl -X POST http://localhost:8080/groups/group-alpha/floor \
     -H "Content-Type: application/json" -d '{"userId": "user-1"}'
# -> 200 {"message": "Floor obtained by user-1 for group group-alpha"}

# user-2 tries while user-1 holds it
curl -X POST http://localhost:8080/groups/group-alpha/floor \
     -H "Content-Type: application/json" -d '{"userId": "user-2"}'
# -> 409 {"message": "Floor is currently held by user-1 for group group-alpha"}

# user-2 takes it anyway with priority
curl -X POST http://localhost:8080/groups/group-alpha/floor \
     -H "Content-Type: application/json" -d '{"userId": "user-2", "priority": true}'
# -> 200

# user-2 releases it
curl -X DELETE http://localhost:8080/groups/group-alpha/floor/user-2
# -> 200

# full history
curl http://localhost:8080/audit
```

## How to run

There are two ways to run the service: **Docker** (quickest) and
**Kubernetes** (how it would run in a production-like cluster). Each is
described twice — first in plain words, then with the exact commands.

### Option 1 — Docker

> **In plain words:** Docker packs the whole application — Python, the
> libraries, the code — into a single sealed box called an *image*. Anyone
> with Docker installed can then run that box with one command, without
> installing Python or anything else. Think of it like a ready-made meal:
> we cook everything into one container, you just heat it up.

Prerequisite: [Docker Desktop](https://www.docker.com/products/docker-desktop/)
installed and running.

```bash
# 1. Build the image (the "sealed box") from the project folder
docker build -t group-call-1 .

# 2. Run it, connecting your computer's port 8080 to the app
docker run --rm -p 8080:8080 group-call-1
```

The API is now available at http://localhost:8080 — open
http://localhost:8080/docs in a browser to try it out. Stop it with
`Ctrl-C`.

### Option 2 — Kubernetes (local cluster with kind)

> **In plain words:** Kubernetes is a system that companies use to run many
> containers reliably — it restarts them if they crash and spreads them
> across machines. [kind](https://kind.sigs.k8s.io/) ("Kubernetes in
> Docker") creates a miniature practice cluster on your own computer so you
> can try this out without any servers. We hand Kubernetes two instruction
> sheets from the `kubernetes/` folder: one says *"keep one copy of this
> app running"* (the Deployment), the other says *"make it reachable on
> port 30080"* (the Service).

Prerequisites: Docker Desktop, [kind](https://kind.sigs.k8s.io/docs/user/quick-start/#installation),
and [kubectl](https://kubernetes.io/docs/tasks/tools/) installed.

```bash
# 1. Create a local practice cluster, mapping its port 30080 to your machine
kind create cluster --name group-call --config kubernetes/kind-config.yaml

# 2. Build the app image and copy it into the cluster
docker build -t group-call-1 .
kind load docker-image group-call-1:latest --name group-call

# 3. Apply the two instruction sheets
kubectl apply -f kubernetes/deployment.yaml
kubectl apply -f kubernetes/service.yaml

# 4. Check the app is up (STATUS should say "Running")
kubectl get pods
```

The API is now available at http://localhost:30080 (note the different
port) — e.g. http://localhost:30080/docs.

> **Note:** the localhost:30080 access relies on the port mapping in
> `kind-config.yaml`, so it only works for clusters created with that
> config (step 1). For a cluster created without it, use port-forwarding
> instead — it works with any cluster:
>
> ```bash
> kubectl port-forward service/group-call-service 30080:8080
> ```
>
> and keep that command running while you use http://localhost:30080.

Tear everything down with:

```bash
kind delete cluster --name group-call
```

### Running locally without containers (for development)

```bash
python -m venv venv
venv\Scripts\activate          # Windows (use source venv/bin/activate on macOS/Linux)
pip install -r requirements.txt
uvicorn app.main:app --port 8080
```

## Running the tests

The suite (36 tests) covers every endpoint, every status code, the timeout
behaviour, priority preemption, the audit log, and concurrent access:

```bash
pip install -r requirements.txt
pytest
```

GitHub Actions runs the same suite automatically on every push to `main`
(see `.github/workflows/test.yml`).

## Design decisions

- **In-memory state, single process.** Floor state and the audit log live
  in Python dictionaries/lists, so the server deliberately runs with one
  uvicorn worker (see `Dockerfile`) and one Kubernetes replica. Multiple
  workers would each have their own idea of who holds the floor. Scaling
  out would require moving state to a shared store (e.g. Redis).
- **Concurrency safety.** Every group has its own `asyncio.Lock`;
  simultaneous requests for the same group are serialized, so exactly one
  of N concurrent obtain requests wins (covered by a test).
- **Floor timeout: 10 seconds, hybrid enforcement.** Each grant stores an
  expiry timestamp *and* schedules an async task that releases the floor
  at the deadline. Every operation also treats an expired hold as free
  (lazy check) as a safety net. A re-request by the current holder does
  **not** reset the timer — the original 10 seconds keep counting down.
- **Priority is a boolean.** A request with `"priority": true` takes the
  floor even if someone else holds it; the preempted hold is closed in the
  audit log at the moment of takeover.
- **Audit log** records one entry per hold: `groupId`, `userId`,
  `priority`, `obtainedAt`, `releasedAt` (UTC). `releasedAt` is `null`
  while the hold is active. A timed-out hold is closed at its exact
  deadline. The log is in-memory and unbounded, so it resets on restart.
- **Spec deviations, on purpose.** The provided OpenAPI spec has a typo
  (`mesage`) in two response schemas; this implementation consistently
  uses `message`. A re-obtain by the current holder returns 200 (the
  spec's 409 is defined as "held by *another* user"). Validation failures
  return 400 with the spec's error shape instead of FastAPI's default 422.

## Project structure

```
app/
  main.py            # FastAPI app factory, 400 handler, shutdown hook
  models.py          # Request/response schemas (Pydantic)
  routers/floors.py  # The four API endpoints
  service.py         # FloorService: state, locks, timeout, audit
kubernetes/
  deployment.yaml    # Runs 1 replica of the app image
  service.yaml       # Exposes it on NodePort 30080
  kind-config.yaml   # Local kind cluster with port 30080 forwarded
tests/
  test_api.py        # 36 end-to-end API tests
Dockerfile
.github/workflows/test.yml   # CI: pytest on every push
```
