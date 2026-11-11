# Running and sharing xconf with Docker

The whole lab — the three protocol servers and the web control panel —
ships as a single container image. This document covers building it,
running it, and sharing it with others.

> Note: the image bundles all four processes (NETCONF, RESTCONF,
> CORECONF, and the web client) in one container for convenience. That is
> fine for a lab; it is not how you would run these as independent
> production services.

## What's in the image

| Process   | Protocol | Port (container) |
|-----------|----------|------------------|
| Web UI    | HTTP     | 8080/tcp         |
| NETCONF   | TCP/XML  | 8300/tcp         |
| RESTCONF  | HTTP/JSON| 8400/tcp         |
| CORECONF  | CoAP/CBOR| 5683/udp         |

The three servers bind to loopback inside the container (only the client
talks to them, and all processes share the container's network
namespace). The **web UI binds to `0.0.0.0`** inside the container so the
published port is reachable from the host. This is controlled by the
`XCONF_WEB_HOST` environment variable (default `127.0.0.1` for bare-metal
runs; the Dockerfile sets it to `0.0.0.0`).

## Build

From the project root (where the `Dockerfile` is):

```bash
docker build -t xconf:latest .
```

The build installs `flask`, `requests`, `cbor2`, and `aiocoap` from
`requirements.txt`. A `.dockerignore` keeps `state/`, `__pycache__/`, and
`.git/` out of the build context.

## Run

```bash
docker run --rm -p 8080:8080 xconf:latest
```

Then open **http://localhost:8080** in your browser.

- `--rm` removes the container when it stops.
- `-p 8080:8080` publishes the web UI. That is all you need to use the
  panel, because the client talks to the three servers *inside* the
  container.

### Exposing the protocol servers too (optional)

If you want to reach the NETCONF / RESTCONF / CORECONF servers directly
from the host (e.g. with your own client or `curl`), publish their ports
as well:

```bash
docker run --rm \
  -p 8080:8080 \
  -p 8300:8300 \
  -p 8400:8400 \
  -p 5683:5683/udp \
  xconf:latest
```

Now, for example:

```bash
curl http://localhost:8400/restconf/data/example:system
```

### Run detached

```bash
docker run -d --name xconf -p 8080:8080 xconf:latest
docker logs -f xconf      # watch startup output
docker stop xconf         # clean shutdown (servers are stopped first)
docker rm xconf
```

### Persisting datastore state across runs (optional)

By default each run starts fresh (datastores seed to a single `default`
instance). To keep state between runs, mount a volume at `/app/state`:

```bash
docker run --rm -p 8080:8080 -v xconf-state:/app/state xconf:latest
```

## Sharing the image

Three common ways, from simplest to most shareable.

### 1. Share a tar file (no registry needed)

Good for air-gapped machines or a quick hand-off.

```bash
# On your machine:
docker save xconf:latest | gzip > xconf-latest.tar.gz

# Send xconf-latest.tar.gz however you like, then on the other machine:
docker load < xconf-latest.tar.gz
docker run --rm -p 8080:8080 xconf:latest
```

### 2. Push to Docker Hub

```bash
# Tag with your Docker Hub username and log in.
docker tag xconf:latest <dockerhub-user>/xconf:latest
docker login
docker push <dockerhub-user>/xconf:latest
```

Others then run it directly — Docker pulls it automatically:

```bash
docker run --rm -p 8080:8080 <dockerhub-user>/xconf:latest
```

Use an immutable version tag (e.g. `:v1`) in addition to `:latest` so
people can pin a known-good build.

### 3. Push to GitHub Container Registry (ghcr.io)

Convenient if the source already lives on GitHub.

```bash
# Create a GitHub personal access token with write:packages, then:
echo "$GITHUB_TOKEN" | docker login ghcr.io -u <github-user> --password-stdin
docker tag xconf:latest ghcr.io/<github-user>/xconf:latest
docker push ghcr.io/<github-user>/xconf:latest
```

Pull/run:

```bash
docker run --rm -p 8080:8080 ghcr.io/<github-user>/xconf:latest
```

## Health check

The image declares a `HEALTHCHECK` that polls the web UI. Check it with:

```bash
docker ps              # shows (healthy) once the UI is up
docker inspect --format '{{.State.Health.Status}}' xconf
```

## Troubleshooting

- **Can't reach http://localhost:8080** — confirm you passed `-p
  8080:8080` and that the container is running (`docker ps`). Check
  `docker logs <container>` for the `[entrypoint]` and
  `[client] web interface` lines.
- **Port already in use on the host** — map to a different host port, e.g.
  `-p 9090:8080`, then browse to `http://localhost:9090`.
- **CORECONF from the host doesn't respond** — make sure you published the
  UDP port specifically: `-p 5683:5683/udp` (TCP mapping won't work for
  CoAP).
- **Permission denied talking to Docker** — your user may not be in the
  `docker` group; use `sudo docker ...` or add yourself to the group.
