# Background Worker

The background worker processes agent tasks from the MongoDB task queue.

## Features

- ✅ **Durable execution** - Tasks survive server restarts
- ✅ **Lease-based locking** - Multiple workers can run simultaneously
- ✅ **Automatic retry** - Failed tasks retry up to max_attempts
- ✅ **Graceful shutdown** - SIGTERM/SIGINT handled cleanly
- ✅ **Lease renewal** - Long-running tasks don't timeout

## Running the Worker

### Basic Usage

```bash
# From project root
python scripts/worker.py
```

### Environment Variables

- `MONGODB_URL` - MongoDB connection string (default: mongodb://localhost:27017)
- `WORKER_ID` - Unique worker identifier (default: hostname-pid)
- `WORKER_POLL_INTERVAL` - Poll interval in seconds (default: 1.0)
- `WORKER_LEASE_SECONDS` - Task lease duration in seconds (default: 600)

### Example

```bash
export MONGODB_URL="mongodb://localhost:27017"
export WORKER_ID="worker-01"
export WORKER_POLL_INTERVAL="0.5"
export WORKER_LEASE_SECONDS="900"

python scripts/worker.py
```

## Deployment

### Development

Run worker in a separate terminal:

```bash
# Terminal 1: API server
python main.py

# Terminal 2: Worker
python scripts/worker.py
```

### Production

Use a process manager like systemd, supervisor, or Docker.

#### Systemd Example

```ini
[Unit]
Description=DeepAgents Background Worker
After=network.target

[Service]
Type=simple
User=deepagents
WorkingDirectory=/path/to/deepagents
Environment="MONGODB_URL=mongodb://localhost:27017"
Environment="WORKER_ID=worker-01"
ExecStart=/path/to/venv/bin/python scripts/worker.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

#### Docker Compose Example

```yaml
version: '3.8'

services:
  api:
    build: .
    command: python main.py
    ports:
      - "8000:8000"
    environment:
      - MONGODB_URL=mongodb://mongo:27017
    depends_on:
      - mongo

  worker:
    build: .
    command: python scripts/worker.py
    environment:
      - MONGODB_URL=mongodb://mongo:27017
      - WORKER_ID=worker-01
      - WORKER_POLL_INTERVAL=1.0
    depends_on:
      - mongo
    # Scale workers horizontally:
    # docker-compose up --scale worker=3

  mongo:
    image: mongo:7
    ports:
      - "27017:27017"
    volumes:
      - mongo_data:/data/db

volumes:
  mongo_data:
```

## Scaling

Run multiple workers for horizontal scaling:

```bash
# Worker 1
WORKER_ID=worker-01 python scripts/worker.py &

# Worker 2
WORKER_ID=worker-02 python scripts/worker.py &

# Worker 3
WORKER_ID=worker-03 python scripts/worker.py &
```

Workers will claim tasks from the queue in FIFO order. MongoDB ensures atomic locking.

## Monitoring

Check active tasks:

```bash
curl http://localhost:8000/api/agents/active
```

Check queue metrics:

```bash
curl http://localhost:8000/api/agents/metrics
```

## Task Recovery

On startup, workers automatically recover stale tasks (tasks with expired leases):

```
2025-10-25 10:00:00 - Worker worker-01 starting...
2025-10-25 10:00:00 - Recovered 2 stale tasks on startup
```

This ensures tasks complete even if workers crash.

## Graceful Shutdown

Workers handle SIGTERM and SIGINT gracefully:

1. Stop claiming new tasks
2. Allow current task to complete (or reassign when lease expires)
3. Close MongoDB connection
4. Exit cleanly

```bash
# Graceful shutdown
kill -TERM <worker_pid>

# Or Ctrl+C
^C
2025-10-25 10:00:00 - Shutdown requested (signal: 2)
2025-10-25 10:00:00 - Worker worker-01 shutting down...
```

## Troubleshooting

### Worker not picking up tasks

Check:
1. MongoDB connection: `mongo mongodb://localhost:27017`
2. Tasks in queue: `db.pa_tasks.find({status: "queued"})`
3. Worker logs for errors

### Tasks stuck in "running" state

Stale tasks with expired leases will be reclaimed:
- On worker startup
- By other workers after lease expires (default 600s)

Force reset:

```python
from api.task_queue import TaskQueue
from pymongo import MongoClient

client = MongoClient("mongodb://localhost:27017")
queue = TaskQueue(client, "org_1")
reset_count = queue.reset_stale_tasks()
print(f"Reset {reset_count} stale tasks")
```

### High memory usage

Workers execute agent tasks which can be memory-intensive. Monitor with:

```bash
ps aux | grep worker.py
```

Consider:
- Limiting concurrent workers
- Running workers on separate machines
- Adjusting task lease duration

