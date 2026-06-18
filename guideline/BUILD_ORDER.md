# BUILD ORDER
## Hermes YouTube Automation System — Urutan Implementasi
**Versi:** 1.0
**Tanggal:** Juni 2025

> **Aturan Dokumen Ini**
> Jangan lompat fase. Setiap fase harus selesai dan SEMUA checklist centang sebelum fase berikutnya dimulai.
> Jika ada yang tidak bisa diselesaikan, catat blockernya dan selesaikan dulu — jangan lanjut.

---

## PERSIAPAN SEBELUM MULAI CODING

Checklist ini harus selesai sebelum satu baris kode pun ditulis.

### Akun & Akses
- [ ] Google Cloud Console account tersedia
- [ ] Google Cloud Project pertama sudah dibuat (`hermes-project-01`)
- [ ] YouTube Data API v3 sudah di-enable di project tersebut
- [ ] YouTube Analytics API sudah di-enable
- [ ] OAuth 2.0 consent screen sudah dibuat (mode: External atau Internal)
- [ ] OAuth Client ID + Client Secret sudah didownload (`credentials.json`)
- [ ] OpenRouter account tersedia (https://openrouter.ai)
- [ ] OpenRouter API key sudah didapat (bisa gratis)
- [ ] Minimal 1 channel YouTube tersedia untuk test

### Infrastructure
- [ ] Ubuntu Server VM sudah berjalan di Proxmox
- [ ] Docker + Docker Compose sudah terinstall di Ubuntu VM
- [ ] NFS mount dari OMV ke Ubuntu sudah berfungsi (`ls /mnt/omv-videos/` berhasil)
- [ ] File test sudah ada di `/mnt/omv-videos/[channel_test]/` (1 file video MP4)
- [ ] OMV sudah punya folder: `Video_Ready/`, `Archive/`, `Backups/`, `Thumbnails/`
- [ ] Git sudah terinstall, repository sudah dibuat (private)

### Tools Developer
- [ ] Python 3.11+ tersedia di local/VM
- [ ] VS Code atau editor pilihan siap
- [ ] `ffmpeg` tersedia (`ffmpeg -version`)

---

## FASE 1A — FONDASI OAUTH & UPLOAD MANUAL
**Estimasi:** 1–2 minggu
**Target:** Upload 1 video ke 1 channel secara manual via script Python

### Setup Project
- [ ] Buat struktur folder project:
  ```
  hermes/
  ├── app/
  │   ├── api/          # FastAPI routes
  │   ├── services/     # Business logic
  │   ├── repositories/ # Database queries
  │   ├── gateways/     # External API adapters
  │   ├── workers/      # Celery tasks
  │   ├── models/       # SQLAlchemy models
  │   └── schemas/      # Pydantic schemas
  ├── migrations/       # Alembic
  ├── tests/
  ├── docker/
  ├── docs/
  ├── .env.example
  ├── docker-compose.yml
  └── requirements.txt
  ```
- [ ] `requirements.txt` minimal: fastapi, uvicorn, sqlalchemy, alembic, celery, redis, google-api-python-client, google-auth-oauthlib, pillow, structlog, pydantic, pytest
- [ ] `.env.example` dibuat dengan semua key yang dibutuhkan (tanpa value)
- [ ] `.gitignore` include `.env`, `*.pyc`, `__pycache__`, `credentials.json`

### Docker Compose Tier 1
- [ ] `docker-compose.yml` dengan service: `mysql`, `redis`, `api`, `worker`, `beat`
- [ ] MySQL volume persisten (named volume, bukan bind mount)
- [ ] Health check untuk MySQL dan Redis di compose
- [ ] Non-root user di Dockerfile (`USER 1000:1000`)
- [ ] `docker compose up -d` berhasil semua service running

### Database & Alembic
- [ ] Alembic diinisialisasi (`alembic init migrations`)
- [ ] `alembic.ini` dikonfigurasi ke MySQL connection string dari env var
- [ ] Migration pertama dibuat: semua tabel Tier 1
  - channels, channel_credentials, file_checksums
  - upload_queue, video_tags, upload_attempts
  - metadata_history, upload_state_history
  - system_config, system_audit_log, gcp_quota_tracker
- [ ] Seed data system_config dijalankan
- [ ] `alembic upgrade head` berhasil tanpa error
- [ ] `alembic downgrade -1` berhasil (migration reversible)

### OAuth Flow (1 Channel)
- [ ] `YoutubeGateway` adapter class dibuat (internal code tidak import google library langsung)
- [ ] OAuth flow script: generate authorization URL
- [ ] User buka URL di browser, approve, dapat authorization code
- [ ] Script exchange code → access token + refresh token
- [ ] Refresh token disimpan ke `channel_credentials` (terenkripsi dengan Fernet)
- [ ] Script verify: token bisa digunakan untuk list channel info
- [ ] Test: token bisa di-refresh otomatis

### Upload Manual (Script, Belum Otomatis)
- [ ] Fungsi `upload_video()` di `YoutubeGateway`:
  - `privacyStatus=private`
  - `publishAt=null`
  - Return `youtube_video_id`
- [ ] Fungsi `upload_thumbnail()` di `YoutubeGateway`
- [ ] Fungsi `set_scheduled()` di `YoutubeGateway`
- [ ] Script end-to-end manual:
  ```
  python scripts/manual_upload.py \
    --channel_id 1 \
    --video /path/to/video.mp4 \
    --thumbnail /path/to/thumb.jpg \
    --title "Test Video" \
    --publish_at "2025-06-20T22:00:00+07:00"
  ```
- [ ] Script berhasil dijalankan
- [ ] Video muncul di YouTube Studio sebagai Private
- [ ] Thumbnail terpasang
- [ ] Video terjadwal publish di waktu yang ditentukan

### Checklist Fase 1A Selesai
- [ ] 1 video berhasil di-upload via script manual
- [ ] Token tidak expired setelah 24 jam
- [ ] Tidak ada plaintext secret di kode atau log
- [ ] `alembic upgrade/downgrade` berfungsi

---

## FASE 1B — MULTI-CHANNEL TOKEN MANAGER
**Estimasi:** 1 minggu
**Target:** Generalisasi ke multiple channel, token management aman

### Token Manager
- [ ] `CredentialService` dibuat di service layer
- [ ] Fungsi `get_valid_token(channel_id)`:
  - Cek apakah token masih valid
  - Jika hampir expired (< 1 jam): refresh otomatis
  - Setiap akses credential di-log ke `system_audit_log`
- [ ] Fungsi `handle_token_revocation(channel_id)`:
  - Set `auth_status = REVOKED`
  - Set `is_active = FALSE` di channels
  - Log ke system_audit_log
- [ ] Deteksi `invalid_grant` pada 401 response dari YouTube API

### GCP Quota Manager
- [ ] `QuotaService` dibuat
- [ ] Fungsi `check_and_reserve_quota(project_id, units)`:
  - `SELECT ... FOR UPDATE` pada `gcp_quota_tracker`
  - Optimistic locking dengan `version` column
  - Return True jika quota cukup, False jika tidak
- [ ] Fungsi `reset_daily_quota()`: dipanggil Celery Beat tiap tengah malam UTC

### Multi-Channel OAuth Setup
- [ ] Endpoint `/auth/youtube/{channel_id}` di FastAPI:
  - Step 1: Return authorization URL
  - Step 2: Callback handler → simpan token
- [ ] Test: 3 channel berbeda bisa di-onboard
- [ ] Test: token masing-masing channel tidak saling interferensi

### Checklist Fase 1B Selesai
- [ ] 3+ channel bisa di-onboard via OAuth
- [ ] Token refresh berjalan otomatis
- [ ] Quota tracker update setelah setiap upload
- [ ] `invalid_grant` terdeteksi dan channel di-pause otomatis
- [ ] Semua akses credential tercatat di system_audit_log

---

## FASE 1C — QUEUE SYSTEM & UPLOAD OTOMATIS
**Estimasi:** 1–2 minggu
**Target:** Upload berjalan otomatis dari database tanpa intervensi manual

### Queue Worker
- [ ] Celery disetup dengan Redis sebagai broker
- [ ] Celery Beat disetup (satu-satunya scheduler — tidak ada APScheduler)
- [ ] Task `process_scheduled_uploads`:
  ```python
  # SELECT FOR UPDATE SKIP LOCKED
  SELECT * FROM upload_queue
  WHERE status = 'SCHEDULED'
    AND scheduled_time <= NOW()
    AND deleted_at IS NULL
  LIMIT 1
  FOR UPDATE SKIP LOCKED
  ```
- [ ] Anti race condition diverifikasi:
  - Jalankan 2 worker bersamaan
  - Pastikan tidak ada upload duplikat
- [ ] State transition dicatat ke `upload_state_history` di setiap perubahan status

### Retry Logic
- [ ] Decorator `@retry_with_backoff` (exponential backoff + jitter)
- [ ] `retry_count` diincrement setiap gagal
- [ ] `next_retry_at` dihitung: `2^retry_count * 60 detik` + random jitter
- [ ] Setelah `retry_count >= max_retry_count`: status → `FAILED_PERMANENT`
- [ ] Log setiap retry ke system_audit_log

### Idempotency
- [ ] Setiap attempt: generate UUID sebagai `idempotency_key`
- [ ] INSERT `upload_attempts` sebelum API call
- [ ] Jika worker crash dan restart: cek `upload_attempts` untuk queue_id ini
  - Jika ada attempt SUCCESS untuk VIDEO → skip upload video, ambil youtube_video_id
  - Lanjut ke THUMBNAIL
- [ ] Test: kill worker saat UPLOADING → restart → verify tidak upload duplikat

### Upload Atomik Flow
- [ ] Implementasi full flow: PENDING → METADATA_READY → SCHEDULED → UPLOADING → PRIVATE_UPLOADED → THUMBNAIL_ATTACHED → SCHEDULED_PUBLIC → DONE
- [ ] Jika thumbnail gagal: status → THUMBNAIL_FAILED, video tetap PRIVATE
- [ ] Jika video gagal: retry → FAILED_PERMANENT

### Timeout Detection
- [ ] Celery Beat task setiap 5 menit: cek upload_queue WHERE status='UPLOADING' AND locked_at < NOW() - INTERVAL 30 MINUTE
- [ ] Jika ditemukan: jalankan reconciliation (cek YouTube Studio via API)
- [ ] Update status sesuai realita

### Checklist Fase 1C Selesai
- [ ] Video masuk DB → upload otomatis tanpa intervensi
- [ ] 2 worker bersamaan: tidak ada duplikat upload
- [ ] Worker crash saat upload: recovery berfungsi
- [ ] FAILED_PERMANENT tercatat dengan error_message jelas
- [ ] upload_state_history terisi untuk setiap transisi

---

## FASE 2A — STORAGE INTEGRATION
**Estimasi:** 1 minggu
**Target:** File baru di OMV otomatis masuk queue

### Storage Crawler
- [ ] Celery Beat task `scan_omv_storage` (setiap 1 jam)
- [ ] Scan semua subfolder di `/mnt/omv-videos/`
- [ ] Nama subfolder = nama channel (cek di tabel `channels`)
- [ ] Per file baru:
  - Hitung SHA-256
  - Cek `file_checksums` (channel_id + sha256) — jika ada: SKIP
  - Log skip ke system_audit_log
- [ ] Copy ke `/var/staging/[channel]/`
- [ ] Verify SHA-256 setelah copy
- [ ] INSERT `upload_queue` (status: PENDING)
- [ ] INSERT `file_checksums`

### NFS Health Check
- [ ] Health check NFS: cek keberadaan `/mnt/omv-videos/.nfs_check`
- [ ] Jika NFS down: log WARNING, skip scan untuk iterasi ini
- [ ] Tidak crash, tidak throw exception yang tidak ter-handle

### Archive Logic
- [ ] Setelah status DONE:
  - `shutil.copy2` staging → `/NAS/Archive/[channel]/[YYYY-MM]/`
  - Verify SHA-256 setelah copy
  - Delete staging file
- [ ] Test: file staging dihapus setelah archive berhasil
- [ ] Test: jika archive gagal, staging file tidak dihapus

### Disk Space Monitor
- [ ] Health check: cek disk usage `/var/staging/` dan NFS
- [ ] Jika > `disk_warning_percent` (80%): log WARNING
- [ ] Jika > `disk_halt_percent` (90%): halt ingestion, log CRITICAL

### Checklist Fase 2A Selesai
- [ ] Letakkan file baru di OMV → muncul di upload_queue tanpa intervensi
- [ ] File yang sama di-drop dua kali: hanya satu yang masuk queue
- [ ] NFS disconnect: crawler tidak crash, skip gracefully
- [ ] Archive berhasil: staging dihapus, file ada di /NAS/Archive/

---

## FASE 2B — HERMES AI METADATA GENERATOR
**Estimasi:** 1–2 minggu
**Target:** Metadata dibuat otomatis oleh AI untuk setiap video baru

### OpenRouter Integration
- [ ] `OpenRouterGateway` adapter class
- [ ] Fungsi `generate_text(prompt, model)`:
  - HTTP POST ke OpenRouter API
  - Timeout: 30 detik (dari system_config)
  - Response parsing
- [ ] Circuit breaker:
  - Counter error per model
  - Setelah `circuit_breaker_errors` (5): fail fast untuk model ini
  - Wait `circuit_breaker_wait_sec` (300) sebelum half-open
- [ ] Fallback chain:
  ```
  Try primary model
  → If 429/5xx 3x: switch ke fallback model
  → If fallback also fails: switch ke last_resort
  → If all fail: status PAUSED_EXTERNAL, alert
  ```

### Hermes Metadata Generation
- [ ] `HermesService` di service layer
- [ ] Prompt template per genre (lofi, phonk, jazz, ambient, dll)
  - Prompt untuk judul (CTR-oriented, <= 100 chars)
  - Prompt untuk deskripsi (keyword-rich, <= 5000 chars)
  - Prompt untuk tags (list <= 15 items)
- [ ] Pydantic schema `MetadataOutput`:
  ```python
  class MetadataOutput(BaseModel):
      title: str = Field(max_length=100)
      description: str = Field(max_length=5000)
      tags: List[str] = Field(max_items=15)

      @validator('tags')
      def validate_tags(cls, v):
          for tag in v:
              assert len(tag) <= 30, f"Tag terlalu panjang: {tag}"
          return v
  ```
- [ ] Jika validasi gagal: retry generate (max 2x) lalu FAILED_PERMANENT dengan log

### Worker Metadata Task
- [ ] Task `generate_metadata` dipanggil untuk setiap item PENDING
- [ ] INSERT metadata_history (changed_by: AI, field_name: title/description/tags)
- [ ] trust_level=NEW → AWAITING_APPROVAL
- [ ] trust_level=TRUSTED → METADATA_READY

### Checklist Fase 2B Selesai
- [ ] Video baru masuk → metadata digenerate dalam < 2 menit
- [ ] Judul selalu <= 100 chars (tidak pernah gagal validasi YouTube)
- [ ] Tags selalu <= 15 items, masing-masing <= 30 chars
- [ ] Circuit breaker berfungsi: OpenRouter mati → task PAUSED_EXTERNAL, tidak hang
- [ ] metadata_history terisi untuk setiap generate

---

## FASE 2C — THUMBNAIL ENGINE
**Estimasi:** 1–2 minggu
**Target:** Thumbnail dibuat otomatis dengan template

### FFmpeg Frame Extraction
- [ ] Fungsi `extract_frame(video_path, position_ratio=0.3)`:
  - Extract frame pada 30% durasi video
  - Output: PNG file di /tmp/
  - Handle: file tidak ditemukan, file bukan video valid
- [ ] Test: frame berhasil di-extract dari berbagai format (mp4, mkv)

### Template System
- [ ] Struktur folder template:
  ```
  /NAS/Thumbnails/templates/
    ├── lofi_default.png
    ├── phonk_default.png
    ├── jazz_default.png
    └── default.png
  ```
- [ ] Konvensi template: 1280x720 PNG dengan area kosong untuk teks overlay
- [ ] Fungsi `load_template(channel_id)`:
  - Cek thumbnail_styles aktif untuk channel
  - Fallback ke genre default template
  - Fallback ke `default.png`

### Pillow Overlay
- [ ] Fungsi `create_thumbnail(frame_path, template_path, title, output_path)`:
  - Composite frame dengan template
  - Overlay judul (word wrap, font pilihan, drop shadow)
  - Resize output ke 1280x720
  - Save ke JPG
  - Compress jika > 2MB (reduce quality iteratif)
- [ ] Test: output selalu 1280x720 dan < 2MB

### Thumbnail Worker Task
- [ ] Task `generate_thumbnail` dipanggil setelah metadata ready
- [ ] Output disimpan ke `/NAS/Thumbnails/[channel]/[queue_id].jpg`
- [ ] Update `thumbnail_path` di upload_queue

### Onboarding Template
- [ ] Dashboard page untuk upload template per channel
- [ ] Form: upload PNG template, preview hasil overlay dengan dummy title
- [ ] Save ke `/NAS/Thumbnails/templates/[channel_id]/[style_name].png`
- [ ] INSERT ke `thumbnail_styles`

### Checklist Fase 2C Selesai
- [ ] Thumbnail digenerate otomatis untuk setiap video baru
- [ ] Output selalu 1280x720 JPG < 2MB
- [ ] Template per channel berfungsi
- [ ] Fallback ke default template jika channel tidak punya template
- [ ] Thumbnail terpasang ke video YouTube setelah upload

---

## FASE 3A — DASHBOARD WEB UI
**Estimasi:** 2 minggu
**Target:** Dashboard lokal yang bisa digunakan untuk monitor dan override

### Setup FastAPI + Jinja2
- [ ] Jinja2 templates disetup di FastAPI
- [ ] Static files (CSS, JS minimal) disetup
- [ ] Layout template: header dengan navigasi antar tab
- [ ] Authentication: simple HTTP Basic Auth untuk LAN access (tidak expose ke internet)

### Tab 1: Queue Monitor
- [ ] Tabel semua video di queue, dikelompokkan per channel
- [ ] Kolom: channel, filename, status (badge warna), scheduled_time, youtube_video_id
- [ ] Filter: per channel, per status
- [ ] Badge counter per status (Queue, Uploading, Done, Error)
- [ ] Auto-refresh setiap 30 detik (atau HTMX/polling)

### Tab 2: Manual Override
- [ ] List video dengan status AWAITING_APPROVAL dan METADATA_READY
- [ ] Per video: form edit judul dan deskripsi
- [ ] Tombol: Approve, Reject, Edit
- [ ] Setelah edit: INSERT metadata_history (changed_by: HUMAN)
- [ ] Approve → status SCHEDULED, Reject → status METADATA_READY (generate ulang)

### Tab 3: Error / Failed
- [ ] List video dengan status FAILED_PERMANENT dan THUMBNAIL_FAILED
- [ ] Per video: tampilkan error_message, upload_state_history
- [ ] Tombol: Re-queue (buat record baru), Mark as Resolved
- [ ] Filter per channel

### Tab 4: Channel Management
- [ ] List semua channel dengan status aktif/nonaktif
- [ ] Per channel: trust_level, auth_status, total video uploaded
- [ ] Tombol: Onboard Channel Baru (OAuth flow)
- [ ] Tombol: Set trust_level (NEW/TRUSTED)
- [ ] Tombol: Pause/Resume channel
- [ ] Upload template thumbnail per channel

### Health & System Status
- [ ] Widget di header/sidebar: status Redis, DB, NFS, Celery Worker
- [ ] Data dari `/ready` endpoint
- [ ] Warna: green=ok, red=down
- [ ] Queue depth counter

### Checklist Fase 3A Selesai
- [ ] Dashboard bisa diakses dari browser di LAN
- [ ] Queue monitor menampilkan semua video dengan status akurat
- [ ] Override judul/deskripsi berfungsi dan tercatat di metadata_history
- [ ] Channel onboarding via OAuth bisa dilakukan dari dashboard
- [ ] Error tab menampilkan video yang perlu perhatian

---

## FASE 3B — ANALYTICS & EVALUASI (TIER 2)
**Estimasi:** 2 minggu
**Target:** Sistem evaluasi H+24 berjalan otomatis, rekomendasi tampil di dashboard

### Analytics Puller
- [ ] `YouTubeAnalyticsGateway` adapter class
- [ ] Fungsi `pull_video_analytics(youtube_video_id, channel_id)`:
  - Pull: views, impressions, CTR, AVD, likes
  - Simpan ke `analytics_logs` dengan log_type
- [ ] Celery Beat schedule:
  - H+24: 24 jam setelah `scheduled_public` time
  - H+7: 7 hari setelah publish
  - H+28: 28 hari setelah publish

### Hermes Evaluator
- [ ] `HermesEvaluatorService`:
  - Input: analytics data + channel baseline
  - Hitung `performance_score` (0-100)
  - Jalankan 4-langkah diagnosis
  - Output: `diagnosis_summary`, `recommended_action`, `hermes_confidence`
- [ ] Baseline: rata-rata CTR dan AVD channel pada video dengan umur serupa (cohort comparison)
- [ ] Jika confidence < 0.70: recommended_action = WAIT_MORE_DATA, nyatakan "DATA TIDAK CUKUP"

### Evaluasi Dashboard Tab
- [ ] Badge merah di navigasi jika ada video ACTION_REQUIRED
- [ ] List video yang perlu tindakan: card per video
- [ ] Per card: nama video, channel, diagnosis Hermes, confidence score, recommended_action
- [ ] Tombol aksi: Generate Judul Baru, Generate Thumbnail Baru, Pertahankan, Skip
- [ ] Flow Generate Judul Baru:
  - Hermes generate 1 judul alternatif (bukan 3 — mengurangi decision fatigue)
  - Tampilkan di modal/panel
  - Tombol: Terapkan, Generate Lagi, Batal
  - Setelah Terapkan: update YouTube via API, log ke metadata_history

### Tracking Efek Perubahan
- [ ] Setelah metadata diubah: catat `change_reason = 'h24_eval'` di metadata_history
- [ ] H+48 analytics pull dijadwalkan setelah ada perubahan di H+24
- [ ] Bandingkan CTR H+24 (sebelum perubahan) vs CTR H+48 (setelah perubahan) — dengan catatan caveat waktu

### Smart Prime Time Engine
- [ ] `TimeslotService`:
  - Update `timeslot_performance` setelah setiap evaluasi H+7
  - Hanya dari video clean sample (tidak ada perubahan metadata)
  - Hitung `confidence_score` berdasarkan sample_count
- [ ] Scheduler menggunakan data ini untuk slot baru

### Checklist Fase 3B Selesai
- [ ] Analytics terpull otomatis H+24 dan H+7
- [ ] Badge evaluasi muncul di dashboard
- [ ] Diagnosis Hermes tampil dengan confidence score
- [ ] Generate judul/thumbnail alternatif berfungsi dari dashboard
- [ ] timeslot_performance terisi setelah 2-4 minggu data

---

## KAPAN TIER BERIKUTNYA DIMULAI?

### Gate dari Tier 1 ke Tier 2
Semua kondisi berikut harus terpenuhi:
- [ ] Sistem sudah upload video nyata ke channel nyata selama **2 minggu berturut-turut** tanpa error kritis
- [ ] Tidak ada `FAILED_PERMANENT` yang belum diinvestigasi
- [ ] Dashboard berfungsi dan bisa digunakan oleh istri/operator
- [ ] Backup harian berjalan dan sudah di-verify restore-nya
- [ ] Token tidak pernah expired atau revoked tanpa terdeteksi

### Gate dari Tier 2 ke Tier 3
- [ ] Sistem berjalan stabil selama **1 bulan** setelah Tier 2
- [ ] timeslot_performance sudah punya data cukup (confidence > 0.5 untuk beberapa slot)
- [ ] Evaluasi H+24 sudah membantu perbaikan CTR minimal 1 channel
- [ ] Channel sudah ada yang menghasilkan revenue

### Gate dari Tier 3 ke Tier 4
- [ ] 20+ channel aktif sekaligus
- [ ] Quota YouTube terbukti jadi bottleneck (bukan hanya prediksi)

---

## STRUKTUR FOLDER FINAL

```
hermes/
├── app/
│   ├── api/
│   │   ├── routes/
│   │   │   ├── auth.py          # OAuth flow endpoints
│   │   │   ├── queue.py         # Queue monitor API
│   │   │   ├── channels.py      # Channel management API
│   │   │   ├── evaluations.py   # Evaluasi API
│   │   │   └── health.py        # /health, /ready, /metrics
│   │   └── dependencies.py      # FastAPI dependencies
│   ├── services/
│   │   ├── channel_service.py
│   │   ├── credential_service.py
│   │   ├── upload_service.py
│   │   ├── metadata_service.py  # Hermes metadata generation
│   │   ├── thumbnail_service.py
│   │   ├── scheduler_service.py # Smart Prime Time
│   │   ├── analytics_service.py
│   │   └── evaluator_service.py # Hermes evaluator
│   ├── repositories/
│   │   ├── channel_repo.py
│   │   ├── queue_repo.py
│   │   ├── analytics_repo.py
│   │   └── config_repo.py
│   ├── gateways/
│   │   ├── youtube_gateway.py   # YouTube Data API adapter
│   │   ├── analytics_gateway.py # YouTube Analytics adapter
│   │   └── openrouter_gateway.py # OpenRouter adapter
│   ├── workers/
│   │   ├── celery_app.py        # Celery instance
│   │   ├── upload_tasks.py
│   │   ├── metadata_tasks.py
│   │   ├── thumbnail_tasks.py
│   │   ├── crawler_tasks.py
│   │   └── analytics_tasks.py
│   ├── models/
│   │   ├── channel.py
│   │   ├── upload_queue.py
│   │   ├── analytics.py
│   │   └── ...
│   ├── schemas/
│   │   ├── metadata.py          # Pydantic untuk AI output
│   │   ├── channel.py
│   │   └── ...
│   ├── templates/               # Jinja2 HTML templates
│   │   ├── base.html
│   │   ├── queue.html
│   │   ├── evaluations.html
│   │   └── channels.html
│   ├── core/
│   │   ├── config.py            # Load dari env + system_config
│   │   ├── logging.py           # structlog setup
│   │   ├── encryption.py        # Fernet envelope encryption
│   │   ├── circuit_breaker.py
│   │   └── exceptions.py        # Custom exception hierarchy
│   └── main.py                  # FastAPI app factory
├── migrations/
│   ├── env.py
│   ├── versions/
│   │   └── 001_initial_schema.py
│   └── alembic.ini
├── tests/
│   ├── unit/
│   │   ├── test_metadata_service.py
│   │   ├── test_evaluator_service.py
│   │   └── test_scheduler_service.py
│   ├── integration/
│   │   ├── test_queue_repo.py
│   │   └── test_upload_flow.py
│   └── conftest.py
├── scripts/
│   ├── manual_upload.py         # Script untuk Fase 1A
│   ├── oauth_setup.py           # OAuth flow helper
│   └── backup_db.sh
├── docker/
│   ├── Dockerfile
│   └── docker-compose.override.yml
├── docs/
│   ├── MASTER_BLUEPRINT_V3.md   # Dokumen ini
│   └── BUILD_ORDER.md           # Dokumen ini
├── .env.example
├── .gitignore
├── docker-compose.yml
└── requirements.txt
```

---

## KONVENSI KODE (WAJIB DIIKUTI)

### Naming
- File: `snake_case.py`
- Class: `PascalCase`
- Fungsi/variable: `snake_case`
- Konstanta: dari `system_config`, bukan hardcode

### Layer Rules
- **Controller (routes/):** Hanya HTTP concern. Tidak ada business logic.
- **Service:** Business logic. Tidak ada SQL langsung. Tidak ada HTTP code.
- **Repository:** Hanya query DB. Tidak ada business logic.
- **Gateway:** External API only. Circuit breaker di sini.

### Logging Wajib
```python
import structlog
log = structlog.get_logger()

# Di setiap fungsi yang punya side effect:
log.info("upload_started", channel_id=channel_id, queue_id=queue_id, agent="worker")
log.error("upload_failed", channel_id=channel_id, error_type=type(e).__name__, error_message=str(e))
```

### Exception Hierarchy
```python
class HermesError(Exception): pass
class DomainError(HermesError): pass      # Business rule violation
class InfrastructureError(HermesError): pass  # DB, Redis, File system
class ExternalAPIError(HermesError): pass     # YouTube, OpenRouter
```

### Terlarang
```python
# TERLARANG - tidak boleh ada di codebase production:
except Exception:
    pass                    # Silent failure

time.sleep(60)             # Gunakan Celery countdown

os.system("rm -rf ...")    # Gunakan subprocess.run dengan check=True

"SELECT * FROM " + table   # SQL injection. Gunakan SQLAlchemy ORM

print("debug info")        # Gunakan structlog
```

---

## CHECKLIST DEPLOYMENT PERTAMA

Setelah Fase 3A selesai, sebelum digunakan untuk channel production:

- [ ] `alembic upgrade head` berjalan tanpa error
- [ ] `curl http://localhost/health` return 200
- [ ] `curl http://localhost/ready` return 200
- [ ] Dashboard bisa diload di browser
- [ ] Celery worker terconnect ke Redis (cek `docker compose logs celery_worker`)
- [ ] Celery Beat schedule aktif (cek `docker compose logs celery_beat`)
- [ ] Backup pertama berjalan: `bash scripts/backup_db.sh` berhasil
- [ ] File backup ada di `/NAS/Backups/db/`
- [ ] OAuth untuk 1 channel test berhasil
- [ ] 1 video test berhasil masuk queue, diproses, dan di-upload
- [ ] Video muncul di YouTube Studio sebagai scheduled

---

*Dokumen ini adalah panduan implementasi. Ikuti urutan. Jangan skip checklist. Sistem yang dibangun dengan hati-hati di awal akan bertahan 5 tahun.*
