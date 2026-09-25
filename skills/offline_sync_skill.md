# Skill: Offline Sync

**Purpose:** Manage the full lifecycle of offline session data — from local capture to server upload. Handles queue management, retry logic, compression, deduplication, and sync status reporting.

---

## Core Invariant

The sync manager must never block or fail a capture operation. If sync fails, capture continues. If the upload queue fills up, compress more aggressively. If the server rejects a frame, log and skip — do not halt the session.

---

## Sync Manager Lifecycle

```
App Launch
    │
    ├── Load sync queue from SQLite
    ├── Check for PENDING items
    │
    ├─[internet available]─► Start SyncWorker
    │
    └─[no internet]────────► Register connectivity listener
                                    │
                             [internet restored]
                                    │
                                    ▼
                              Start SyncWorker
```

---

## SyncWorker Algorithm

```python
class SyncWorker:
    MAX_RETRIES = 5
    BACKOFF_SECONDS = [30, 60, 120, 300, 900]  # per retry attempt

    def run(self):
        items = db.query_sync_queue(
            status__in=["pending", "failed"],
            retry_count__lt=self.MAX_RETRIES,
            order_by="created_at ASC"
        )

        for item in items:
            if not has_internet():
                break  # stop and wait for next trigger

            try:
                self.process(item)
            except Exception as e:
                self.handle_failure(item, e)

    def process(self, item):
        db.update_sync_status(item.id, "uploading")

        if item.entity_type == "session_meta":
            response = api.post("/sessions", payload=item.payload)
            db.update_remote_id(item.local_id, response["session_id"])

        elif item.entity_type == "frame":
            compressed = compress_image(item.local_path)
            response = api.post_frame(item.remote_session_id, compressed)
            db.update_remote_id(item.local_id, response["frame_id"])

        db.update_sync_status(item.id, "done")

    def handle_failure(self, item, error):
        item.retry_count += 1
        if item.retry_count >= self.MAX_RETRIES:
            db.update_sync_status(item.id, "skipped")
            notify_teacher("sync_failed", item)
        else:
            delay = self.BACKOFF_SECONDS[item.retry_count - 1]
            db.schedule_retry(item.id, delay_seconds=delay)
            db.update_sync_status(item.id, "failed")
```

---

## Enqueue Operations

### Enqueue Session Metadata
Called when `session.status` changes to `"completed"`:
```python
def enqueue_session(session: LocalSession):
    db.insert_sync_queue({
        "entity_type": "session_meta",
        "local_id": session.id,
        "status": "pending",
        "payload": session.to_dict()
    })
```

### Enqueue Frame
Called immediately after each frame is captured and saved to disk:
```python
def enqueue_frame(frame: LocalFrame):
    db.insert_sync_queue({
        "entity_type": "frame",
        "local_id": frame.id,
        "status": "pending",
        "payload": {"image_path": frame.image_path, "session_local_id": frame.session_id}
    })
```

Ordering guarantee: session metadata must be uploaded before any frame in that session. SyncWorker enforces this by processing `session_meta` items first within each session group.

---

## Image Compression

```python
def compress_image(path: str) -> bytes:
    img = PIL.Image.open(path)
    size_kb = os.path.getsize(path) / 1024

    if size_kb > 500:
        quality = 75
    elif size_kb > 200:
        quality = 85
    else:
        return open(path, "rb").read()  # no compression needed

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=quality, optimize=True)

    if buffer.tell() / 1024 > 300:
        # Still too large — resize
        img = img.resize((1280, 960), PIL.Image.LANCZOS)
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=quality)

    return buffer.getvalue()
```

Target: **<200KB per frame** for reliable upload on 2G/EDGE.

---

## Deduplication

The server enforces `UNIQUE(session_id, local_frame_id)`. The mobile client uses this to safely retry without creating duplicates:

```python
def upload_frame(frame, remote_session_id):
    response = api.post_multipart("/sessions/{id}/frames", {
        "image": compressed_bytes,
        "local_frame_id": frame.local_id,
        "captured_at": frame.captured_at,
        "sequence_no": frame.sequence_no
    })

    if response.status == 409:
        # Already uploaded — treat as success
        db.update_sync_status(frame.local_id, "done")
        return

    if response.status in (200, 201, 202):
        db.update_sync_status(frame.local_id, "done")
        db.set_remote_id(frame.local_id, response["frame_id"])
```

---

## Connectivity Detection

```python
def has_internet() -> bool:
    # Primary: check Android NetworkInfo
    network_info = connectivity_manager.get_active_network_info()
    if not network_info or not network_info.is_connected:
        return False

    # Secondary: lightweight ping to known reliable endpoint
    try:
        requests.head("https://api.aci.xperimentor.com/health", timeout=3)
        return True
    except:
        return False
```

Avoid relying on Android's connectivity API alone — it reports "connected" on captive portals that have no actual internet.

---

## Sync Status Reporting

The mobile app maintains a `SyncStatusLiveData` observable:
```python
@dataclass
class SyncStatus:
    total_pending: int       # sessions + frames in queue
    currently_uploading: bool
    last_sync_at: datetime | None
    failed_items: int        # items at max retries

def get_display_state(status: SyncStatus) -> str:
    if status.failed_items > 0:
        return "error"       # orange warning
    if status.currently_uploading:
        return "syncing"     # blue spinner
    if status.total_pending > 0:
        return "pending"     # grey dot
    return "synced"          # green dot
```

---

## Post-Sync Trigger

After all frames for a session are synced (all `sync_status = "done"`):
```python
def on_session_fully_synced(session_id: str):
    api.post(f"/sessions/{session_id}/generate", {
        "outputs": ["notes", "quiz", "bloom", "summary", "missing_concepts", "experiments"]
    })
```

This triggers the AI pipeline on the server automatically — teachers do not need to manually request AI generation.

---

## Storage Cleanup Policy

After a session is fully synced and AI outputs are available on the server:
- Keep local SQLite metadata forever (lightweight, used for offline dashboard)
- Keep local images for **7 days** after sync (in case re-upload needed)
- Delete local images after 7 days to free device storage
- Thumbnails (cache): evict immediately after sync

Notify teacher before auto-deletion: "Old session images cleared to free space."
