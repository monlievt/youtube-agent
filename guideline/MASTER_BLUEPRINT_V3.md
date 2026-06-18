# MASTER BLUEPRINT V3
## Hermes YouTube Automation System
**Versi:** 3.0 — FINAL (Tidak ada perubahan arsitektur setelah dokumen ini)
**Status:** Disetujui — Siap Implementasi
**Tanggal:** Juni 2025
**Maintainer:** 1 orang, 5 tahun horizon

> **Aturan Emas Dokumen Ini**
> Dokumen ini adalah sumber kebenaran tunggal. Jika ada pertanyaan "kenapa pakai X?", jawabannya ada di sini. Jika tidak ada di sini, keputusannya belum dibuat dan harus didiskusikan sebelum kode ditulis.

---

## DAFTAR ISI

1. [Konteks & Batasan](#1-konteks--batasan)
2. [Keputusan Arsitektur Final](#2-keputusan-arsitektur-final)
3. [Infrastruktur & Topologi](#3-infrastruktur--topologi)
4. [Tech Stack Final](#4-tech-stack-final)
5. [Tier System](#5-tier-system)
6. [Skema Database Final](#6-skema-database-final)
7. [State Machine](#7-state-machine)
8. [Alur Kerja End-to-End](#8-alur-kerja-end-to-end)
9. [Sistem Evaluasi Post-Publish](#9-sistem-evaluasi-post-publish)
10. [Konstitusi Agent](#10-konstitusi-agent)
11. [Keamanan](#11-keamanan)
12. [Observability](#12-observability)
13. [Failure Playbook](#13-failure-playbook)
14. [Backup & Recovery](#14-backup--recovery)
15. [Yang Dihapus & Alasannya](#15-yang-dihapus--alasannya)

---

## 1. KONTEKS & BATASAN

### Profil Sistem
- **Operator:** 1 orang (non-engineer penuh waktu)
- **Skala:** 10–30 channel musik, berbeda genre
- **Produksi:** Batch tidak rutin — kadang 10 video sekaligus, kadang tidak ada
- **Environment:** On-premise, jaringan lokal, hardware yang sudah ada
- **Horizon:** 5 tahun maintainability

### Prinsip Desain (Tidak Boleh Dilanggar)
1. **Simplicity over cleverness** — jika butuh penjelasan lebih dari 5 menit, terlalu kompleks
2. **Human decides, AI recommends** — AI tidak pernah eksekusi tindakan publik tanpa approval
3. **Recoverability over perfection** — sistem boleh gagal, asal bisa dipulihkan oleh 1 orang
4. **Observable or it doesn't exist** — jika tidak bisa dimonitor, tidak boleh ada di production
5. **Boring technology** — pakai stack yang sudah terbukti, bukan yang terbaru

### Bahaya Terbesar
Membangun sistem enterprise untuk kebutuhan personal. Setiap fitur harus melewati pertanyaan: **"Apakah ini perlu untuk 30 channel musik dikelola 1 orang?"**

---

## 2. KEPUTUSAN ARSITEKTUR FINAL

Tabel ini adalah keputusan yang **tidak boleh didiskusikan ulang** kecuali ada kejadian luar biasa.

| Aspek | Keputusan | Alasan |
|---|---|---|
| **Database** | MySQL 8+ di semua environment | SKIP LOCKED, mature, Docker dev mudah |
| **Migration** | Alembic — wajib hari pertama | Tidak ada manual ALTER TABLE selamanya |
| **Task Queue** | Celery + Redis | Satu ekosistem, Beat untuk schedule |
| **Scheduler** | Celery Beat saja | APScheduler dihapus — triple scheduler = chaos |
| **Dashboard** | FastAPI + Jinja2 | Maintainable, testable, explicit routes |
| **Thumbnail** | Pillow + FFmpeg, template PNG | No Vision AI — deterministik, murah, cukup |
| **AI/LLM** | OpenRouter (model gratis) | Satu key, banyak model, fallback chain |
| **Upload flow** | Private → Thumbnail → Scheduled | Atomik, aman, bisa recovery |
| **Locking** | SELECT FOR UPDATE SKIP LOCKED | Atomik, tidak ada race condition |
| **GCP Project** | Mulai 1, scale jika terbukti perlu | 5 project dari awal = operational nightmare |
| **Credential** | Tabel terpisah + envelope encryption | Isolasi keamanan dari data operasional |
| **Soft delete** | Wajib semua tabel operasional | Data 5 tahun tidak boleh hilang karena 1 bug |
| **Logging** | structlog JSON | No Prometheus/Grafana di Tier 1 |
| **Tracklist** | Sidecar file JSON/CSV | Jangan parse dari nama file — tidak reliable |
| **SQLite** | Dihapus | Schema drift antar environment |
| **Streamlit** | Dihapus | Tidak maintainable setelah 6 bulan |
| **Vision AI** | Dihapus | 5% hasil sama dengan 1% kompleksitas template |
| **APScheduler** | Dihapus | Celery Beat sudah cukup |

---

## 3. INFRASTRUKTUR & TOPOLOGI

```
+------------------------------------------------------------------+
|                   PROXMOX VE (SERVER FISIK)                      |
|                                                                  |
|  +------------------------+    +------------------------------+  |
|  |  OPENMEDIAVAULT VM     |    |    UBUNTU SERVER VM          |  |
|  |                        |    |                              |  |
|  |  /NAS/Video_Ready/     |    |  +------------------------+  |  |
|  |    +- channel_lofi/    |    |  | Local Staging          |  |  |
|  |    +- channel_phonk/   |    |  | /var/staging/[channel] |  |  |
|  |    +- channel_jazz/    |    |  +----------+-------------+  |  |
|  |                        |    |             |                |  |
|  |  /NAS/Archive/         |    |  +----------v-------------+  |  |
|  |  /NAS/Backups/         |    |  | Docker Compose         |  |  |
|  |  /NAS/Thumbnails/      |    |  |                        |  |  |
|  +----------+-------------+    |  | FastAPI (API + UI)     |  |  |
|             | NFS/SMB          |  | Celery Worker          |  |  |
|             +------------------+  | Celery Beat            |  |  |
|                                |  | Redis                  |  |  |
|                                |  | MySQL 8+ (volume)      |  |  |
|                                |  +------------------------+  |  |
|                                +------------------------------+  |
+------------------------------------------------------------------+
                                        |
                        +---------------v---------------+
                        |          INTERNET             |
                        | YouTube Data API v3           |
                        | YouTube Analytics API         |
                        | OpenRouter API                |
                        +-------------------------------+
```

### Penjelasan Topologi

**Local Staging (`/var/staging/`)** adalah buffer kritis. File tidak diproses langsung dari NFS.
Alur: Copy NFS → Staging lokal → Proses → Archive NFS → Hapus staging.
Melindungi dari NFS disconnect saat proses sedang berjalan.

**MySQL volume** menggunakan Docker named volume yang di-mount ke `/var/lib/mysql`. Data persisten meski container restart.

**NFS mount** ke `/mnt/omv-videos/` untuk read. Archive ke `/NAS/Archive/`. File heartbeat check: `/mnt/omv-videos/.nfs_check`.

---

## 4. TECH STACK FINAL

| Layer | Teknologi | Versi | Catatan |
|---|---|---|---|
| Language | Python | 3.11+ | Type hints wajib |
| Backend API | FastAPI | Latest stable | Async, testable |
| Task Queue | Celery | 5.x | Worker + Beat |
| Message Broker | Redis | 7.x | Queue + cache |
| Database | MySQL | 8.0+ | Semua environment |
| ORM | SQLAlchemy | 2.x | Async support |
| Migration | Alembic | Latest | Wajib sejak hari pertama |
| Validation | Pydantic | v2 | Semua AI output wajib validasi |
| AI/LLM | OpenRouter API | — | Via HTTP, bukan SDK khusus |
| Video | FFmpeg | Latest | Frame extraction |
| Image | Pillow | Latest | Template overlay |
| YouTube | google-api-python-client | Latest | Wrapped dalam adapter |
| Logging | structlog | Latest | JSON output |
| Testing | pytest | Latest | + testcontainers |
| Container | Docker + Compose | Latest stable | Dev = prod parity |

### Fallback Chain OpenRouter (Eksplisit, Tidak Boleh Implicit)
```
Primary:     meta-llama/llama-3.3-70b-instruct:free
Fallback:    mistralai/mistral-7b-instruct:free
Last resort: google/gemma-2-9b-it:free
```
Trigger fallback: 3x error 429 atau 5xx dalam 60 detik pada model saat ini.

---

## 5. TIER SYSTEM

Sistem dibangun dalam tier. **Tier berikutnya tidak dimulai sebelum tier sebelumnya stabil di production selama minimal 2 minggu.**

### Tier 1 — WAJIB (Sistem Inti)
Target: Sistem bisa upload video nyata ke channel nyata secara otomatis.

**Core Infrastructure:**
- FastAPI + Celery + Redis + MySQL + Alembic + Docker Compose
- Structured logging (structlog JSON)
- Health check `/health` dan `/ready`
- Backup otomatis harian

**Database Tier 1:**
- channels, channel_credentials, upload_queue
- file_checksums, video_tags, upload_attempts
- metadata_history, upload_state_history
- system_config, system_audit_log, gcp_quota_tracker

**Reliability:**
- SHA-256 duplicate guard
- SELECT FOR UPDATE SKIP LOCKED
- Retry dengan exponential backoff (max 3x, dikonfigurasi di system_config)
- Idempotency key per upload attempt
- Upload atomik: Private → Thumbnail → Scheduled
- Soft delete semua tabel operasional

**AI (Tier 1):**
- OpenRouter integrasi
- Pydantic validation wajib untuk semua output AI
- Circuit breaker sederhana (5 error → wait 5 menit)

**Thumbnail (Tier 1):**
- FFmpeg frame extraction (frame pada 30% durasi)
- Pillow template PNG overlay
- Output: 1280x720 JPG < 2MB

**Dashboard (Tier 1):**
- Queue monitor (status semua video per channel)
- Manual override metadata (judul, deskripsi)
- Channel management (onboarding, trust level)
- Error/Failed tab dengan opsi re-queue

### Tier 2 — Setelah Tier 1 Stabil 2 Minggu
Target: Sistem belajar dan memberi rekomendasi berbasis data.

Tambahkan:
- Smart Prime Time Engine (timeslot_performance)
- Thumbnail style tracking (thumbnail_styles)
- H+24 dan H+7 evaluation otomatis
- Performance score dan diagnosis Hermes
- Hermes recommendations di dashboard
- video_evaluations, evaluation_options
- timeslot_performance, thumbnail_styles, video_tracklist
- analytics_logs

### Tier 3 — Setelah Channel Menghasilkan Revenue
Target: Observability lebih dalam, sistem lebih bulletproof.

Tambahkan:
- Prometheus metrics endpoint `/metrics`
- Alerting via email/webhook
- Worker heartbeat monitoring
- Dead letter queue dengan dashboard alert
- Grafana (opsional)

### Tier 4 — Jika Skala Mencapai 30 Channel Aktif
Target: Enterprise-grade jika memang perlu.

Tambahkan:
- Envelope encryption penuh dengan key rotation automation
- Cohort analytics yang valid secara statistik
- Feature flags
- Multi-GCP project routing (hanya jika quota terbukti jadi bottleneck)

---

## 6. SKEMA DATABASE FINAL

### Prinsip Universal (Berlaku untuk Semua Tabel)
- Semua tabel operasional: `id`, `created_at`, `updated_at`, `deleted_at`
- Soft delete: `WHERE deleted_at IS NULL` di semua query default
- Bahasa Inggris konsisten untuk semua identifier
- FK wajib, `ON DELETE RESTRICT` default
- Index pada semua FK dan query pattern utama

---

### `channels`
```sql
CREATE TABLE channels (
    id                  INT PRIMARY KEY AUTO_INCREMENT,
    channel_name        VARCHAR(100) NOT NULL,
    youtube_channel_id  VARCHAR(50),
    genre               VARCHAR(50) NOT NULL,
    gcp_project_id      VARCHAR(50) DEFAULT 'project_default',
    trust_level         ENUM('NEW','TRUSTED') DEFAULT 'NEW',
    is_active           BOOLEAN DEFAULT TRUE,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    deleted_at          DATETIME NULL,
    UNIQUE KEY uq_channel_name (channel_name)
);
```

### `channel_credentials`
```sql
-- Terpisah dari channels untuk isolasi keamanan
-- Semua nilai dienkripsi di aplikasi sebelum disimpan
CREATE TABLE channel_credentials (
    id                      INT PRIMARY KEY AUTO_INCREMENT,
    channel_id              INT NOT NULL,
    encrypted_client_id     TEXT NOT NULL,
    encrypted_client_secret TEXT NOT NULL,
    encrypted_refresh_token TEXT NOT NULL,
    key_version             INT DEFAULT 1,
    last_refreshed          DATETIME,
    auth_status             ENUM('VALID','NEEDS_REAUTH','REVOKED') DEFAULT 'VALID',
    created_at              DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at              DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    deleted_at              DATETIME NULL,
    FOREIGN KEY (channel_id) REFERENCES channels(id) ON DELETE RESTRICT,
    UNIQUE KEY uq_channel_credential (channel_id)
);
```

### `file_checksums`
```sql
CREATE TABLE file_checksums (
    id          INT PRIMARY KEY AUTO_INCREMENT,
    channel_id  INT NOT NULL,
    sha256      CHAR(64) NOT NULL,
    filename    VARCHAR(255) NOT NULL,
    file_size   BIGINT,
    detected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (channel_id) REFERENCES channels(id),
    UNIQUE KEY uq_channel_sha256 (channel_id, sha256),
    INDEX idx_sha256 (sha256)
);
```

### `upload_queue`
```sql
CREATE TABLE upload_queue (
    id                  INT PRIMARY KEY AUTO_INCREMENT,
    channel_id          INT NOT NULL,
    file_checksum_id    INT NOT NULL,

    -- File paths (relatif dari staging root)
    staging_path        VARCHAR(500) NOT NULL,
    thumbnail_path      VARCHAR(500),

    -- Metadata AI-generated
    title_generated     VARCHAR(100),
    description_generated TEXT,

    -- Metadata final (dipakai saat upload — AI atau Human)
    title_final         VARCHAR(100),
    description_final   TEXT,
    is_human_override   BOOLEAN DEFAULT FALSE,

    -- Status & scheduling
    status ENUM(
        'PENDING',
        'METADATA_READY',
        'AWAITING_APPROVAL',
        'SCHEDULED',
        'UPLOADING',
        'PRIVATE_UPLOADED',
        'THUMBNAIL_ATTACHED',
        'SCHEDULED_PUBLIC',
        'DONE',
        'THUMBNAIL_FAILED',
        'FAILED_PERMANENT',
        'PAUSED',
        'PAUSED_EXTERNAL',
        'QUOTA_EXHAUSTED',
        'NEEDS_REAUTH'
    ) DEFAULT 'PENDING',
    previous_status     VARCHAR(50),
    scheduled_time      DATETIME,
    actual_publish_hour TINYINT,
    actual_publish_dow  TINYINT,

    -- Hasil upload
    youtube_video_id    VARCHAR(50),
    error_message       TEXT,
    retry_count         INT DEFAULT 0,
    next_retry_at       DATETIME,

    -- Worker lock
    locked_at           DATETIME,
    worker_id           VARCHAR(100),

    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    deleted_at          DATETIME NULL,

    FOREIGN KEY (channel_id) REFERENCES channels(id),
    FOREIGN KEY (file_checksum_id) REFERENCES file_checksums(id),
    UNIQUE KEY uq_channel_file (channel_id, file_checksum_id),
    INDEX idx_status_scheduled (status, scheduled_time),
    INDEX idx_channel_status (channel_id, status, scheduled_time)
);
```

### `video_tags`
```sql
-- Tags normalized, bukan flat string VARCHAR
CREATE TABLE video_tags (
    id          INT PRIMARY KEY AUTO_INCREMENT,
    queue_id    INT NOT NULL,
    tag         VARCHAR(30) NOT NULL,
    position    TINYINT NOT NULL,
    source      ENUM('AI','HUMAN') DEFAULT 'AI',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (queue_id) REFERENCES upload_queue(id),
    INDEX idx_queue_tags (queue_id)
);
```

### `upload_attempts`
```sql
-- Tracking per attempt untuk idempotency
CREATE TABLE upload_attempts (
    id                  INT PRIMARY KEY AUTO_INCREMENT,
    queue_id            INT NOT NULL,
    idempotency_key     CHAR(36) NOT NULL,
    attempt_number      TINYINT NOT NULL,
    attempt_type        ENUM('VIDEO','THUMBNAIL','SCHEDULE') NOT NULL,
    youtube_video_id    VARCHAR(50),
    http_status         INT,
    response_summary    TEXT,
    started_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at        DATETIME,
    success             BOOLEAN DEFAULT FALSE,
    FOREIGN KEY (queue_id) REFERENCES upload_queue(id),
    UNIQUE KEY uq_idempotency (idempotency_key),
    INDEX idx_queue_attempts (queue_id, attempt_type)
);
```

### `metadata_history`
```sql
CREATE TABLE metadata_history (
    id              INT PRIMARY KEY AUTO_INCREMENT,
    queue_id        INT NOT NULL,
    field_name      ENUM('title','description','tags','thumbnail','status') NOT NULL,
    old_value       TEXT,
    new_value       TEXT,
    changed_by      ENUM('AI','HUMAN','SYSTEM') NOT NULL,
    change_reason   VARCHAR(255),
    changed_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (queue_id) REFERENCES upload_queue(id),
    INDEX idx_queue_history (queue_id, field_name)
);
```

### `upload_state_history`
```sql
-- Menjawab "kenapa video ini nyangkut di state X?"
CREATE TABLE upload_state_history (
    id          INT PRIMARY KEY AUTO_INCREMENT,
    queue_id    INT NOT NULL,
    from_state  VARCHAR(50),
    to_state    VARCHAR(50) NOT NULL,
    reason      VARCHAR(255),
    actor       VARCHAR(100),
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (queue_id) REFERENCES upload_queue(id),
    INDEX idx_queue_state (queue_id, created_at)
);
```

### `system_config`
```sql
-- Tidak ada magic number di kode. Semua di sini.
CREATE TABLE system_config (
    config_key      VARCHAR(100) PRIMARY KEY,
    config_value    VARCHAR(500) NOT NULL,
    config_type     ENUM('INT','FLOAT','STRING','BOOL') NOT NULL,
    description     TEXT,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

INSERT INTO system_config VALUES
('max_retry_count',          '3',    'INT',    'Maksimal retry sebelum FAILED_PERMANENT', NOW()),
('openrouter_timeout_sec',   '30',   'INT',    'Timeout request ke OpenRouter (detik)', NOW()),
('default_publish_hour_utc', '15',   'INT',    'Jam publish default UTC (=22 WIB) jika belum ada timeslot data', NOW()),
('min_ctr_threshold',        '2.0',  'FLOAT',  'CTR minimum yang dianggap sehat (%)', NOW()),
('h24_views_threshold',      '100',  'INT',    'Views H+24 di bawah ini trigger evaluasi', NOW()),
('upload_timeout_minutes',   '30',   'INT',    'Timeout UPLOADING state sebelum dianggap stuck', NOW()),
('disk_warning_percent',     '80',   'INT',    'Disk usage % untuk warning', NOW()),
('disk_halt_percent',        '90',   'INT',    'Disk usage % untuk halt ingestion', NOW()),
('circuit_breaker_errors',   '5',    'INT',    'Jumlah error sebelum circuit breaker open', NOW()),
('circuit_breaker_wait_sec', '300',  'INT',    'Detik tunggu sebelum circuit breaker half-open', NOW()),
('approval_timeout_days',    '7',    'INT',    'Hari sebelum AWAITING_APPROVAL auto-cancel', NOW()),
('openrouter_primary',       'meta-llama/llama-3.3-70b-instruct:free', 'STRING', 'Model utama', NOW()),
('openrouter_fallback',      'mistralai/mistral-7b-instruct:free',     'STRING', 'Model fallback', NOW()),
('openrouter_last_resort',   'google/gemma-2-9b-it:free',              'STRING', 'Model last resort', NOW());
```

### `system_audit_log`
```sql
-- Immutable. Tidak ada UPDATE/DELETE.
CREATE TABLE system_audit_log (
    id              BIGINT PRIMARY KEY AUTO_INCREMENT,
    actor           VARCHAR(100) NOT NULL,
    action          VARCHAR(100) NOT NULL,
    resource_type   VARCHAR(50),
    resource_id     VARCHAR(50),
    details         JSON,
    ip_address      VARCHAR(45),
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_resource (resource_type, resource_id, created_at),
    INDEX idx_actor (actor, created_at)
);
```

### `gcp_quota_tracker`
```sql
CREATE TABLE gcp_quota_tracker (
    project_id      VARCHAR(50) PRIMARY KEY,
    project_name    VARCHAR(100),
    units_used_today INT DEFAULT 0,
    units_limit     INT DEFAULT 10000,
    version         INT DEFAULT 1,
    reset_date      DATE,
    last_updated    DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
```

### Tabel Tier 2 (ditambahkan setelah Tier 1 stabil)

```sql
-- analytics_logs
CREATE TABLE analytics_logs (
    id                  INT PRIMARY KEY AUTO_INCREMENT,
    youtube_video_id    VARCHAR(50) NOT NULL,
    channel_id          INT NOT NULL,
    log_type            ENUM('H24','H48','H7','H14','H28','H90') NOT NULL,
    views               INT DEFAULT 0,
    impressions         INT DEFAULT 0,
    ctr_percentage      FLOAT DEFAULT 0,
    avd_seconds         INT DEFAULT 0,
    likes               INT DEFAULT 0,
    pulled_at           DATETIME DEFAULT CURRENT_TIMESTAMP,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (channel_id) REFERENCES channels(id),
    INDEX idx_video_type (youtube_video_id, log_type),
    INDEX idx_channel_pulled (channel_id, pulled_at)
);

-- video_evaluations
CREATE TABLE video_evaluations (
    id                  INT PRIMARY KEY AUTO_INCREMENT,
    queue_id            INT NOT NULL,
    youtube_video_id    VARCHAR(50) NOT NULL,
    eval_stage          ENUM('H24','H48','H7','H14','H28','H90') NOT NULL,
    views               INT DEFAULT 0,
    impressions         INT DEFAULT 0,
    ctr_percentage      FLOAT DEFAULT 0,
    avd_seconds         INT DEFAULT 0,
    baseline_ctr        FLOAT,
    baseline_avd        FLOAT,
    performance_score   FLOAT,
    diagnosis_summary   TEXT,
    hermes_confidence   FLOAT,
    recommended_action  ENUM('KEEP','CHANGE_THUMBNAIL','CHANGE_TITLE',
                             'CHANGE_DESCRIPTION','CHANGE_MULTIPLE',
                             'CHECK_CONTENT','WAIT_MORE_DATA'),
    eval_status         ENUM('PENDING','ANALYZED','ACTION_REQUIRED',
                             'ACTION_TAKEN','CLOSED') DEFAULT 'PENDING',
    action_taken_at     DATETIME,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    deleted_at          DATETIME NULL,
    FOREIGN KEY (queue_id) REFERENCES upload_queue(id),
    INDEX idx_queue_stage (queue_id, eval_stage),
    INDEX idx_eval_status (eval_status, created_at)
);

-- evaluation_options (normalisasi dari JSON column)
CREATE TABLE evaluation_options (
    id              INT PRIMARY KEY AUTO_INCREMENT,
    evaluation_id   INT NOT NULL,
    option_type     ENUM('TITLE','DESCRIPTION','THUMBNAIL') NOT NULL,
    option_value    TEXT NOT NULL,
    is_selected     BOOLEAN DEFAULT FALSE,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (evaluation_id) REFERENCES video_evaluations(id),
    INDEX idx_eval_type (evaluation_id, option_type)
);

-- timeslot_performance
CREATE TABLE timeslot_performance (
    id              INT PRIMARY KEY AUTO_INCREMENT,
    channel_id      INT NOT NULL,
    hour_of_day     TINYINT NOT NULL,
    day_of_week     TINYINT NOT NULL,
    avg_views_48h   FLOAT DEFAULT 0,
    avg_ctr         FLOAT DEFAULT 0,
    avg_avd_seconds INT DEFAULT 0,
    sample_count    INT DEFAULT 0,
    confidence_score FLOAT DEFAULT 0,
    last_updated    DATETIME,
    FOREIGN KEY (channel_id) REFERENCES channels(id),
    UNIQUE KEY uq_channel_slot (channel_id, day_of_week, hour_of_day),
    INDEX idx_channel_confidence (channel_id, confidence_score)
);

-- thumbnail_styles
CREATE TABLE thumbnail_styles (
    id              INT PRIMARY KEY AUTO_INCREMENT,
    channel_id      INT NOT NULL,
    style_name      VARCHAR(100) NOT NULL,
    template_path   VARCHAR(500),
    avg_ctr         FLOAT DEFAULT 0,
    sample_count    INT DEFAULT 0,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    deleted_at      DATETIME NULL,
    FOREIGN KEY (channel_id) REFERENCES channels(id)
);

-- video_tracklist (diisi dari sidecar JSON/CSV, bukan parse nama file)
CREATE TABLE video_tracklist (
    id                  INT PRIMARY KEY AUTO_INCREMENT,
    queue_id            INT NOT NULL,
    track_position      TINYINT NOT NULL,
    track_name          VARCHAR(255) NOT NULL,
    start_time_seconds  INT NOT NULL,
    end_time_seconds    INT,
    FOREIGN KEY (queue_id) REFERENCES upload_queue(id),
    INDEX idx_queue_tracks (queue_id)
);
```

---

## 7. STATE MACHINE

### Upload Queue — Semua State & Transisi

```
[File Baru]
    |
    v
PENDING
    |
    | (metadata + thumbnail generated)
    v
METADATA_READY
    |
    +---[trust=NEW]---> AWAITING_APPROVAL --[human approve]--> SCHEDULED
    |                                                               |
    +---[trust=TRUSTED]-----------------------------------------> SCHEDULED
                                                                    |
                                                                    v
                                                                UPLOADING
                                                                    |
                                                         [video upload sukses]
                                                                    |
                                                                    v
                                                          PRIVATE_UPLOADED
                                                          |              |
                                               [thumbnail ok]   [thumbnail gagal]
                                                          |              |
                                                          v              v
                                                THUMBNAIL_ATTACHED  THUMBNAIL_FAILED
                                                          |              |
                                               [set publishAt]   [retry/manual]
                                                          |
                                                          v
                                                  SCHEDULED_PUBLIC
                                                          |
                                               [Google publish video]
                                                          |
                                                          v
                                                        DONE

ANY STATE --> PAUSED (human atau sistem)
PAUSED --> previous_status (resume)
ANY STATE --> FAILED_PERMANENT (retry habis)
ANY STATE --> PAUSED_EXTERNAL (dependency down)
ANY STATE --> QUOTA_EXHAUSTED
ANY STATE --> NEEDS_REAUTH
```

### Aturan Transisi Wajib
- Worker WAJIB cek `status == expected_state` sebelum transisi. Jika tidak cocok: abort, log warning.
- `DONE` dan `FAILED_PERMANENT` adalah terminal states — tidak ada transisi keluar kecuali buat record baru.
- Re-queue dari `FAILED_PERMANENT`: buat record BARU di `upload_queue` (referensikan ID lama di `metadata_history`).

### Timeout
- `UPLOADING` > 30 menit → Celery Beat detect → auto ke `FAILED_PERMANENT`
- `AWAITING_APPROVAL` > 7 hari → auto soft-delete

### Video Evaluation State Machine
```
PENDING --> DATA_PULLED --> ANALYZED
ANALYZED --[score < 60]--> ACTION_REQUIRED --> ACTION_TAKEN --> CLOSED
ANALYZED --[score >= 60]--> CLOSED
ACTION_TAKEN --> DATA_PULLED (evaluasi efek perubahan)
```

---

## 8. ALUR KERJA END-TO-END

### Tahap 1: Ingest (Celery Beat, setiap 1 jam)
```
1. Crawler scan /mnt/omv-videos/[channel]/ untuk file baru
2. Per file baru:
   a. Hitung SHA-256
   b. Cek file_checksums (channel_id + sha256) — jika ada: SKIP
   c. Copy ke /var/staging/[channel]/ (local disk, bukan NFS)
   d. Verify SHA-256 setelah copy (pastikan tidak korup)
   e. INSERT upload_queue (status: PENDING)
   f. INSERT file_checksums
3. Log setiap skip dan process ke system_audit_log
```

### Tahap 2: Metadata Generation (Worker, SKIP LOCKED)
```
1. SELECT FOR UPDATE SKIP LOCKED WHERE status='PENDING' LIMIT 1
2. Hermes Agent:
   a. Load prompt berdasarkan genre channel
   b. Generate: 1 judul + 1 deskripsi + list tags
3. Validasi Pydantic WAJIB:
   - title <= 100 chars
   - description <= 5000 chars
   - tags: <= 15 items, masing-masing <= 30 chars
4. Jika validasi gagal: retry generate (max 2x) lalu FAILED_PERMANENT
5. Simpan title_generated, description_generated ke upload_queue
6. INSERT video_tags (source: AI)
7. title_final = title_generated (default, bisa di-override human)
8. INSERT metadata_history (changed_by: AI)
9. trust_level=NEW  --> status: AWAITING_APPROVAL
   trust_level=TRUSTED --> status: METADATA_READY
```

### Tahap 3: Thumbnail Generation (Worker)
```
1. FFmpeg: ekstrak frame pada 30% durasi video dari staging_path
2. Load template PNG untuk channel (dari thumbnail_styles aktif)
   Jika belum ada template: gunakan default genre template
3. Pillow overlay:
   - title_final (word wrap jika perlu)
   - Branding/logo channel
4. Resize ke 1280x720
5. Save ke JPG, compress hingga < 2MB
6. Simpan ke /NAS/Thumbnails/[channel]/[queue_id].jpg
7. Update thumbnail_path di upload_queue
```

### Tahap 4: Scheduling (Worker)
```
Tier 1 (Cold Start / belum ada timeslot data):
   → Scatter ke 4 slot: 07:00, 12:00, 20:00, 22:00 WIB secara bergantian

Tier 2 (ada data timeslot, confidence >= 0.4):
   → Query timeslot_performance, pilih slot terbaik yang belum terpakai hari ini

→ Set scheduled_time di upload_queue
→ Status: SCHEDULED
```

### Tahap 5: Upload Execution (Worker, saat scheduled_time tiba)
```
1. SELECT FOR UPDATE SKIP LOCKED
   WHERE status='SCHEDULED' AND scheduled_time <= NOW()

2. Cek GCP quota via gcp_quota_tracker
   Jika units_used_today + 1650 > units_limit:
   → Status: QUOTA_EXHAUSTED, stop

3. Generate idempotency_key (UUID)

4. [UPLOAD VIDEO]
   INSERT upload_attempts (type: VIDEO, idempotency_key)
   Upload video dengan privacyStatus=private, publishAt=null
   Terima youtube_video_id
   UPDATE upload_attempts (success: true, youtube_video_id)
   UPDATE upload_queue (youtube_video_id)
   Status → PRIVATE_UPLOADED

5. [UPLOAD THUMBNAIL]
   INSERT upload_attempts (type: THUMBNAIL)
   Upload thumbnail_path menggunakan youtube_video_id
   UPDATE upload_attempts (success: true)
   Status → THUMBNAIL_ATTACHED

   Jika thumbnail gagal setelah max retry:
   Status → THUMBNAIL_FAILED
   Alert dashboard (video masih PRIVATE, bisa retry manual)

6. [SET SCHEDULE]
   INSERT upload_attempts (type: SCHEDULE)
   Update video: privacyStatus=scheduled, publishAt=scheduled_time
   UPDATE upload_attempts (success: true)
   Status → SCHEDULED_PUBLIC

7. [ARCHIVE]
   shutil.copy2 staging_path → /NAS/Archive/[channel]/
   Verify SHA-256 setelah copy
   Delete staging_path
   Status → DONE

8. Update gcp_quota_tracker (units_used_today += 1650)
```

### Tahap 6: Evaluasi Post-Publish (Tier 2, Celery Beat)
```
H+24: Pull analytics → diagnosis → jika views < h24_views_threshold: ACTION_REQUIRED
H+7:  Pull analytics → performance score → jika score < 60: ACTION_REQUIRED
H+28: Cek evergreen potential (opsional)
```

### Tahap 7: Learning (Tier 2, Background)
```
- Update timeslot_performance HANYA dari video yang tidak mengalami perubahan metadata
  (clean sample — metadata change membiaskan data)
- Cohort comparison: CTR video ini vs rata-rata CTR channel
  pada UMUR VIDEO YANG SAMA (bukan absolute CTR)
- Update thumbnail_styles avg_ctr dari cohort valid
```

---

## 9. SISTEM EVALUASI POST-PUBLISH

### Timeline

| Checkpoint | Kapan | Tindakan Sistem | User |
|---|---|---|---|
| H+24 | 24 jam setelah publish | Pull data, jalankan diagnosis | Wajib jika views < 100 |
| H+48 | 48 jam | Konfirmasi, cek efek perubahan | Opsional |
| H+7 | 7 hari | Evaluasi lengkap | Wajib jika score < 60 |
| H+14 | 14 hari | Ukur efek perubahan H+24/H+7 | Opsional |
| H+28 | 28 hari | Evaluasi bulanan, evergreen check | Opsional |
| H+90 | 90 hari | Refresh thumbnail lama | Opsional |

### Framework Diagnosis (4 Langkah Berurutan)

```
LANGKAH 1: views < threshold (default 100)?
  TIDAK → Performa awal oke, monitor ke H+7
  YA → lanjut ke langkah 2

LANGKAH 2: impressions < 500?
  YA → YouTube tidak push video ini
       Masalah: deskripsi/tag/kategori tidak relevan
       Action: CHANGE_DESCRIPTION
  TIDAK → lanjut ke langkah 3

LANGKAH 3: CTR < 2%?
  YA → Thumbnail/judul tidak menarik klik
       Action: CHANGE_THUMBNAIL atau CHANGE_TITLE
  TIDAK → lanjut ke langkah 4

LANGKAH 4: AVD < 20% durasi video?
  YA → Orang klik tapi langsung keluar
       Masalah: konten/urutan musik awal tidak cocok
       Action: CHECK_CONTENT
  TIDAK → Masalah timing/algoritma
           Action: WAIT_MORE_DATA
```

### Aturan Confidence Hermes

| Confidence | Tindakan |
|---|---|
| >= 0.85 | Rekomendasi kuat, tampilkan dengan tombol aksi |
| 0.70 – 0.84 | Rekomendasi moderat, tampilkan dengan catatan |
| < 0.70 | Wajib tampilkan: "DATA TIDAK CUKUP — tidak ada rekomendasi valid" |

### Catatan Penting: Channel < 1.000 Subscriber
- Retention curve per detik tidak tersedia dari API
- AVD hanya angka rata-rata, tidak bisa identifikasi titik drop spesifik
- Feature flag `retention_detail_available` diset berdasarkan kemampuan API response — bukan hardcode angka

### Validitas Statistik
- CTR secara natural turun seiring waktu (impressions naik, CTR turun)
- Perbandingan valid: CTR video ini di H+24 vs rata-rata CTR video channel lain DI H+24
- Bukan: CTR H+24 vs CTR H+48 (apples to oranges)

---

## 10. KONSTITUSI AGENT

### 10 Aturan (Tidak Boleh Dilanggar)

**RULE-001: Human Authority is Absolute**
AI hanya REKOMENDASI, tidak pernah EKSEKUSI tindakan publik tanpa approval.
Terlarang: AI mengubah private → public, menghapus file/token/analytics.

**RULE-002: Explicit Over Implicit**
Semua konfigurasi di `system_config` atau file terversioning. Tidak ada default tersembunyi.
Terlarang: Fallback behavior tidak terdokumentasi, smart default tanpa log.

**RULE-003: Idempotency is Mandatory**
Setiap fungsi dengan side effect harus idempoten atau punya idempotency key.
Terlarang: Fungsi yang berjalan 2x dengan hasil berbeda.

**RULE-004: No Destructive Action Without Audit**
Setiap perubahan destruktif harus ada di `system_audit_log`. Soft delete wajib.
Terlarang: DELETE langsung pada tabel operasional.

**RULE-005: Security by Default**
Credential enkripsi at rest. Setiap akses credential di-log. Container non-root.
Terlarang: Plaintext secret di kode, log, atau DB.

**RULE-006: Observability is Non-Negotiable**
Structured logging JSON untuk semua event. Health check endpoint. Tidak ada silent failure.
Terlarang: `print()` sebagai logging, exception di-swallow.

**RULE-007: Simplicity Over Cleverness**
Teknologi boring yang terbukti. Jika butuh penjelasan > 5 menit, terlalu kompleks.
Terlarang: Microservices untuk sistem 1 orang, AI untuk masalah yang bisa diselesaikan if/else.

**RULE-008: Recoverability Over Automation**
Setiap proses otomatis punya manual override. State machine punya transisi recovery.
Terlarang: State yang tidak bisa diubah manual dari dashboard.

**RULE-009: Data Integrity is Sacred**
Transaction boundary jelas. FK constraints aktif. Schema change hanya via Alembic.
Terlarang: Direct SQL dari controller, schema drift.

**RULE-010: AI is a Tool, Not a Decision Maker**
AI output wajib confidence score. Confidence < 0.7: nyatakan "DATA TIDAK CUKUP".
Terlarang: AI memutuskan upload, reschedule, atau ganti thumbnail tanpa approval.

---

### Batas Wewenang Per Agent

| Agent | Boleh | Tidak Boleh |
|---|---|---|
| **Hermes** | Analisis, diagnosis, generate opsi, confidence score | Eksekusi upload, hapus data, overwrite final metadata, akses credential |
| **Worker** | Eksekusi task, transisi state, file operation dengan audit | Putuskan apakah video di-upload, generate metadata |
| **Scheduler** | Trigger periodic task via Celery Beat | Business logic, eksekusi langsung |
| **Analytics** | Pull data YouTube, simpan ke analytics_logs | Diagnosis, keputusan tindakan |

### Output Wajib Hermes

```json
{
  "confidence": 0.82,
  "reasoning": "CTR 1.1% vs rata-rata channel 3.2%. Impressions tinggi (1240).",
  "evidence": ["impressions: 1240", "ctr: 1.1%", "channel_avg_ctr: 3.2%"],
  "primary_recommendation": "CHANGE_THUMBNAIL",
  "risks": ["False positive karena variasi normal"],
  "data_sufficiency": "SUFFICIENT"
}
```

---

## 11. KEAMANAN

### Envelope Encryption
```
Master Key (env var, tidak pernah masuk DB atau kode)
    |
    | mengenkripsi
    v
Data Key (per channel, disimpan terenkripsi di channel_credentials)
    |
    | mengenkripsi
    v
Credential (client_secret, refresh_token)
```

Rotasi: Data Key bisa dirotasi per channel tanpa menyentuh Master Key.

### Rules
- `.env` permission: `chmod 600`, masuk `.gitignore`, tidak pernah di-commit
- Tidak ada `ENV secret_value` di Dockerfile
- Container berjalan sebagai `USER 1000:1000`
- DB port bind ke `127.0.0.1` saja, tidak di-expose ke network luar
- Dashboard hanya accessible via LAN (tidak di-expose internet tanpa VPN)
- Setiap akses ke `channel_credentials` wajib INSERT ke `system_audit_log`

### Token Revocation Handling
```
YouTube API return 401 invalid_grant
    → UPDATE channel_credentials SET auth_status='REVOKED'
    → UPDATE channels SET is_active=FALSE (pause channel)
    → Alert dashboard
    → User re-run OAuth flow via /auth/youtube/{channel_id}
```

---

## 12. OBSERVABILITY

### Logging (Tier 1 — Wajib)

Library: `structlog`, output JSON ke stdout, Docker log driver menangkap.

Field wajib:
```
timestamp, level, event, correlation_id, agent, function
```

Field opsional (sertakan jika relevan):
```
channel_id, queue_id, youtube_video_id, duration_seconds
```

Level guide:
- `DEBUG`: development only
- `INFO`: business event (upload_started, upload_done, evaluation_triggered)
- `WARNING`: retry, degradation, quota 80%
- `ERROR`: failure tercatch, wajib ada error_type dan error_message
- `CRITICAL`: system halt, DB down

### Health Check (Tier 1 — Wajib)
```
GET /health   → liveness (return 200 jika proses hidup)
GET /ready    → readiness (cek DB: SELECT 1, Redis: PING, NFS: path exists)
```

### Alerting Minimal (Tier 1)
Cron script setiap 5 menit:
```bash
curl -sf http://localhost/ready || \
  mail -s "HERMES SYSTEM DOWN" admin@local < /dev/null
```

### Metrics & Grafana (Tier 3 — Opsional)
Prometheus endpoint `/metrics` ditambahkan di Tier 3.
Metric prioritas: queue_depth per status, upload_errors_total, disk_usage_percent.

---

## 13. FAILURE PLAYBOOK

### F-001: Redis Mati
Detection: Worker log `ConnectionError`. `/ready` return non-200.
Recovery: `docker compose restart redis` → verify `/ready` kembali green.

### F-002: Celery Worker Mati
Detection: Queue depth naik. Dashboard task stagnant.
Recovery: `docker compose restart celery_worker` → monitor queue drain.

### F-003: Database Mati
Detection: API return 503. `/ready` gagal.
Recovery: `docker compose restart db` → verify `SELECT 1`. Jika korup: restore backup.

### F-004: OpenRouter Rate Limit / Down
Detection: Circuit breaker open. Task status `PAUSED_EXTERNAL`.
Recovery: Tunggu cooldown 5 menit → resume dari dashboard. Atau ganti API key di `.env`.

### F-005: YouTube Quota Habis
Detection: API 403 `quotaExceeded`. Task status `QUOTA_EXHAUSTED`.
Recovery: Tunggu reset (tengah malam Pacific Time ≈ 14:00-15:00 WIB). Tidak ada shortcut.

### F-006: Refresh Token Revoked
Detection: API 401 `invalid_grant`. Channel status `NEEDS_REAUTH`.
Recovery: Re-run OAuth flow di dashboard → `/auth/youtube/{channel_id}`.

### F-007: Worker Crash Saat Upload (UPLOADING > 30 menit)
Detection: Celery Beat detect timeout → trigger reconciliation task.
Recovery:
- Cek `upload_attempts` untuk `youtube_video_id`
- Cek YouTube Studio: apakah video sudah ada?
- Jika ada: update DB ke `PRIVATE_UPLOADED`, lanjut thumbnail
- Jika tidak ada: reset ke `SCHEDULED`

### F-008: NFS Disconnect
Detection: `OSError: Stale file handle` saat copy. Staging gagal.
Recovery: `mount -a` di Ubuntu VM → verify `ls /mnt/omv-videos/`.

### F-009: Disk Penuh
Detection: Disk usage > 90%. `OSError: No space left`.
Recovery: Hapus log lama > 90 hari → `docker compose logs --since 90d` prune.

### F-010: Duplicate Upload
Detection: Dua video identik di YouTube. SHA-256 guard harusnya mencegah ini.
Recovery: Hapus duplikat di YouTube Studio. Investigasi bypass checksum.

---

## 14. BACKUP & RECOVERY

### Jadwal Backup
```
Daily (02:00 WIB):
  mysqldump hermes | gzip > /NAS/Backups/db/YYYY-MM-DD.sql.gz
  Retention: 30 hari

Weekly (Minggu 03:00 WIB):
  Export channel_credentials (terenkripsi)
  Backup .env (terenkripsi dengan GPG)
  Retention: 12 minggu

Monthly:
  Restore test di VM/environment terpisah
  Verify COUNT(*) tabel utama
  Verify credential bisa didekripsi
  Verify SHA-256 file checksums
```

### Restore Database
```bash
# Stop services yang nulis ke DB
docker compose stop celery_worker celery_beat

# Optional: backup current state
docker compose exec db mysqldump -u root -p hermes > /tmp/pre_restore.sql

# Restore
gunzip < /NAS/Backups/db/YYYY-MM-DD.sql.gz | \
  docker compose exec -T db mysql -u root -p hermes

# Verify schema version
docker compose run --rm api alembic current

# Restart
docker compose up -d

# Smoke test
curl http://localhost/health && curl http://localhost/ready
```

### Total System Loss Recovery
```
1. Rebuild VM Ubuntu dari Proxmox template
2. Install Docker + Docker Compose
3. Clone repository
4. Copy .env dari backup terenkripsi (decrypt dengan GPG)
5. docker compose up -d (MySQL, Redis, API, Worker)
6. alembic upgrade head
7. Restore DB dari backup
8. mount NFS: mount -a
9. Test OAuth 1 channel: GET /auth/youtube/test/{channel_id}
10. Jika token invalid: re-auth flow per channel
11. Smoke test lengkap
```

---

## 15. YANG DIHAPUS & ALASANNYA

| Yang Dihapus | Alasan |
|---|---|
| Vision AI untuk thumbnail | 5% hasil sama dengan 1% kompleksitas. Template Pillow cukup untuk channel musik |
| APScheduler | Celery Beat sudah cukup. Triple scheduler = conflicting triggers, chaos |
| Streamlit | Tidak maintainable setelah 6 bulan. FastAPI+Jinja2 lebih solid dan testable |
| SQLite | Schema drift antar environment. MySQL 8+ di semua env = konsistensi |
| Generate 3 opsi sebagai default | Boros token OpenRouter, decision fatigue. Default 1 opsi; alternatif hanya saat evaluasi buruk |
| Upload langsung public/scheduled | Tidak aman. Private → Thumbnail → Scheduled adalah satu-satunya flow yang bisa di-recovery |
| Parse tracklist dari nama file | Tidak reliable. Wajib sidecar JSON/CSV atau input manual |
| Prometheus/Grafana di Tier 1 | Overkill untuk 1 orang di awal. structlog + health check sudah cukup |
| Multi-GCP project dari awal | Operational nightmare untuk 1 orang. Mulai 1 project, scale jika terbukti perlu |
| Magic numbers di kode | Semua constant di system_config table — bisa diubah tanpa deploy ulang |
| JSON columns untuk data queryable | Normalisasi ke evaluation_options dan video_tags |
| Credential di tabel channels | Isolasi ke channel_credentials dengan enkripsi terpisah |
| Hardcode threshold 1000 subscriber | Feature flag berdasarkan kemampuan API response — lebih akurat |
| Raw CTR comparison H+24 vs H+48 | Tidak valid statistik. Wajib cohort comparison pada umur video yang sama |

---

*Dokumen ini final. Perubahan arsitektur hanya boleh dilakukan jika ada kejadian yang membuktikan keputusan ini salah, dan harus dicatat alasannya sebelum perubahan dilakukan.*
