# Kubernetes Deployment

This guide covers deploying the SOLVE-IT MCP Server to Kubernetes.

## Overview

Kubernetes deployment is best suited for the HTTP transport mode, which exposes the `/health` endpoint for liveness probes. The server is stateless after startup, making it straightforward to run as a Deployment.

The main consideration compared to Docker is how to provide the SOLVE-IT data. Options:

1. **PersistentVolumeClaim** — store a clone of the SOLVE-IT repository on a PVC
2. **Init container** — clone or download the repository at Pod startup
3. **Bake into a custom image** — build a derived image with the data included (simplest for reproducibility)

## Prerequisites

- A running Kubernetes cluster
- `kubectl` configured for your cluster
- The SOLVE-IT MCP Docker image built and pushed to a registry

## Quick Start

### 1. Build and Push the Image

```bash
docker build -t your-registry/mcp-solve-it:0.1.0 .
docker push your-registry/mcp-solve-it:0.1.0
```

### 2. Create a ConfigMap for the TOML Config

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: solveit-mcp-config
  namespace: forensics
data:
  default.toml: |
    [server]
    name = "solveit-mcp"
    version = "0.1.0"
    transport = "http"
    log_level = "INFO"

    [security]
    profile = "moderate"

    [security.rate_limits]
    enabled = true
    global_rpm = 120
    per_tool_rpm = 60
    burst_size = 10

    [security.io_limits]
    max_request_size = 5000000
    max_response_size = 10000000

    [security.input_validation]
    enabled = true
    max_string_length = 10000
    max_array_length = 100
    max_object_depth = 10

    [security.input_sanitization]
    enabled = true
    level = "moderate"

    [security.auth]
    enabled = false
    provider = "none"

    [extensions]
    auto_discover = true
    init_module = "mcp_chassis.extensions.solveit_init"

    [diagnostics]
    health_check_enabled = true
    include_config_summary = false

    [app]
    solveit_data_path = "/data/solve-it"
    objective_mapping = "solve-it.json"
    enable_extensions = true
    init_required = true
    enable_full_detail_tools = false

    [app.search]
    enable_item_types_filter = true
    enable_substring_match = true
    enable_search_logic = true
```

```bash
kubectl apply -f configmap.yaml
```

### 3. Create a PersistentVolumeClaim for SOLVE-IT Data

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: solveit-data
  namespace: forensics
spec:
  accessModes:
    - ReadOnlyMany    # Multiple pods can read simultaneously
  resources:
    requests:
      storage: 1Gi
  storageClassName: standard
```

Populate the PVC with the SOLVE-IT repository. One approach is an init job:

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: solveit-data-init
  namespace: forensics
spec:
  template:
    spec:
      containers:
      - name: init
        image: alpine/git
        command: ["git", "clone", "https://github.com/SOLVE-IT-DF/solve-it.git", "/data/solve-it"]
        volumeMounts:
        - name: solveit-data
          mountPath: /data
      restartPolicy: OnFailure
      volumes:
      - name: solveit-data
        persistentVolumeClaim:
          claimName: solveit-data
```

### 4. Deploy the Server

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: solveit-mcp
  namespace: forensics
  labels:
    app: solveit-mcp
spec:
  replicas: 2
  selector:
    matchLabels:
      app: solveit-mcp
  template:
    metadata:
      labels:
        app: solveit-mcp
    spec:
      containers:
      - name: solveit-mcp
        image: your-registry/mcp-solve-it:0.1.0
        ports:
        - containerPort: 8000
          name: http
        env:
        - name: MCP_CHASSIS_CONFIG
          value: "/config/default.toml"
        - name: MCP_TRANSPORT
          value: "http"
        resources:
          requests:
            cpu: 250m
            memory: 256Mi
          limits:
            cpu: 1000m
            memory: 512Mi
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 15
          periodSeconds: 30
          timeoutSeconds: 5
          failureThreshold: 3
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 10
          timeoutSeconds: 3
          failureThreshold: 3
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          runAsNonRoot: true
          runAsUser: 1000
        volumeMounts:
        - name: config
          mountPath: /config
          readOnly: true
        - name: solveit-data
          mountPath: /data/solve-it
          readOnly: true
        - name: tmp
          mountPath: /tmp
      volumes:
      - name: config
        configMap:
          name: solveit-mcp-config
      - name: solveit-data
        persistentVolumeClaim:
          claimName: solveit-data
      - name: tmp
        emptyDir: {}
```

```bash
kubectl apply -f deployment.yaml
```

### 5. Create a Service

```yaml
apiVersion: v1
kind: Service
metadata:
  name: solveit-mcp
  namespace: forensics
spec:
  selector:
    app: solveit-mcp
  ports:
  - name: http
    port: 8000
    targetPort: 8000
  type: ClusterIP
```

### 6. Verify

```bash
kubectl get pods -n forensics -l app=solveit-mcp
kubectl port-forward svc/solveit-mcp 8000:8000 -n forensics
curl http://localhost:8000/health
```

A healthy response:
```json
{"status": "healthy", "tools": 21}
```

## Using a Secret for the Data Path

If the SOLVE-IT data path or other sensitive config values should not appear in a ConfigMap, use a Secret:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: solveit-mcp-secrets
  namespace: forensics
stringData:
  SOLVE_IT_DATA_PATH: "/data/solve-it"
```

Reference it in the Deployment:

```yaml
env:
- name: MCP_APP_SOLVEIT_DATA_PATH
  valueFrom:
    secretKeyRef:
      name: solveit-mcp-secrets
      key: SOLVE_IT_DATA_PATH
```

## Baking SOLVE-IT Data into the Image

For pinned, reproducible deployments (recommended for forensic use), build a derived image with the SOLVE-IT data included:

```dockerfile
FROM mcp-solve-it:0.1.0

# Pin to a specific release
ARG SOLVE_IT_VERSION=v0.2025-10
RUN apt-get update && apt-get install -y git && \
    git clone --depth 1 --branch ${SOLVE_IT_VERSION} \
      https://github.com/SOLVE-IT-DF/solve-it.git /data/solve-it && \
    apt-get remove -y git && apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

ENV MCP_APP_SOLVEIT_DATA_PATH=/data/solve-it
```

```bash
docker build --build-arg SOLVE_IT_VERSION=v0.2025-10 -t my-registry/solveit-mcp-pinned:0.2025-10 -f Dockerfile.release .
docker push my-registry/solveit-mcp-pinned:0.2025-10
```

This approach eliminates the need for a PVC and makes the image fully self-contained.

## Health Probes

The `/health` endpoint is available only when `MCP_TRANSPORT=http` (or `[server] transport = "http"` in TOML). It returns:

- `200 OK` with JSON body when the server is healthy and the KB is loaded
- `503 Service Unavailable` if the KB is in a degraded state (only when `init_required = false`)

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 15
  periodSeconds: 30
  timeoutSeconds: 5
  failureThreshold: 3

readinessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 10
  timeoutSeconds: 3
  failureThreshold: 3
```

Set `initialDelaySeconds` to at least 10 seconds to allow the KB to load before the first probe fires.

## Scaling

The KnowledgeBase is read-only and loaded once per Pod, so multiple replicas are safe:

```bash
kubectl scale deployment solveit-mcp --replicas=3 -n forensics
```

Or use a HorizontalPodAutoscaler:

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: solveit-mcp
  namespace: forensics
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: solveit-mcp
  minReplicas: 2
  maxReplicas: 8
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

## Troubleshooting

### Pod stuck in CrashLoopBackOff

```bash
kubectl logs -n forensics <pod-name>
kubectl describe pod -n forensics <pod-name>
```

Common causes:

- `solveit_data_path` inside the container does not match the volume mount path
- PVC not populated — the SOLVE-IT data directory is empty
- Resource limits too low (OOMKilled)
- `MCP_TRANSPORT` not set to `http` — health probe returns connection refused

### Health check failing

```bash
# Test from within the cluster
kubectl run -it --rm debug --image=curlimages/curl --restart=Never -n forensics -- \
  curl http://solveit-mcp:8000/health
```

If the endpoint returns connection refused, verify `MCP_TRANSPORT=http` is set.

### ImagePullBackOff

Ensure the image is pushed to a registry the cluster can reach and that any image pull secrets are configured.

## Next Steps

- [Docker Deployment](docker.md) — local and container-based deployment
- [Environment Variables](../reference/environment-variables.md) — all configuration options
- [Troubleshooting](../guides/troubleshooting.md) — common issues
