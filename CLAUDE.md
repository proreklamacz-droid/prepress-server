# PrePress Server — CLAUDE.md

## Přehled projektu

Webová aplikace pro předtiskovou přípravu PDF souborů. Běží na serveru `ai-core` (Ubuntu 24.04, IP 192.168.0.174), přístupná přes Cloudflare tunnel. Součást ekosystému Království Tisku / ProReklama.

## Účel

- **Interní použití:** Imposice, přeskládání stránek, tiskové značky, preflight kontrola vlastních dat
- **Budoucí zákaznický portál:** Preflight kontrola tiskových dat pro B2B/B2C klienty (tiskárny, reklamky) — zatím NENÍ součástí tohoto projektu

## Architektura

```
prepress-server/
├── backend/          # FastAPI (Python 3.11+)
├── frontend/         # Next.js 14 (TypeScript)
├── workers/          # Redis + RQ (job queue)
├── data/
│   ├── uploads/      # Nahrané PDF soubory
│   ├── outputs/      # Zpracované výstupy
│   └── db/           # SQLite databáze
└── docker-compose.yml
```

## Technický stack

| Vrstva | Technologie |
|--------|-------------|
| Backend | FastAPI (Python 3.11) |
| Frontend | Next.js 14, TypeScript, Tailwind CSS |
| PDF manipulace | pikepdf, PyMuPDF (fitz) |
| PDF kreslení/značky | ReportLab |
| Preflight | pikepdf + PyMuPDF + Ghostscript CLI |
| Job queue | Redis + RQ |
| Databáze | SQLite (SQLAlchemy) |
| LLM reporter | Groq API (llama-3.3-70b-versatile) + lokální Ollama fallback |
| Notifikace | Telegram Bot API |
| Kontejnerizace | Docker + docker-compose |
| Port | 8686 (frontend), 8687 (backend API) |

## Infrastruktura

- **Server:** ai-core, Ubuntu 24.04, NVIDIA RTX 5060 Ti 16GB, CUDA
- **RPi5:** 192.168.0.x — lehčí joby, vždy dostupný (sdílí docker stack s n8n, NocoDB atd.)
- **NAS:** Zyxel 192.168.0.80 — zálohy
- **Cloudflare tunnel:** subdoména `prepress.kralovstvitisku.cz`
- **GitHub:** `proreklamacz-droid/prepress-server`

## Datový model (SQLAlchemy)

```python
# Job — hlavní entita
class Job(Base):
    id: str (UUID)
    created_at: datetime
    updated_at: datetime
    source_filename: str
    source_path: str
    source_size_bytes: int
    source_hash: str (SHA256)
    client_type: str  # "internal" / "b2b" / "b2c" — pro budoucí portál
    client_id: str | None  # nullable — pro budoucí napojení
    status: str  # "queued" / "processing" / "done" / "error" / "needs_attention"
    processed_on: str  # "rpi" / "ai-core"
    processing_time_ms: int | None
    notes: str | None

# PreflightResult — výsledek kontroly
class PreflightResult(Base):
    id: str (UUID)
    job_id: str (FK → Job)
    
    # Fonty
    fonts_ok: bool
    fonts_issues: JSON  # [{name, page, issue_type}]
    
    # Rozlišení
    resolution_ok: bool
    resolution_issues: JSON  # [{page, dpi, location}]
    resolution_min_dpi: int | None
    
    # Barvy
    colorspace: str  # "cmyk" / "rgb" / "mixed"
    colorspace_issues: JSON
    
    # Průhlednosti
    transparency_issues: JSON  # [{page, type}]
    
    # Overprint
    overprint_issues: JSON
    
    # Ink coverage
    ink_coverage_max: float | None  # % — pro Xerox limit ~300%
    ink_coverage_issues: JSON
    
    # Hairlines
    hairlines_found: bool
    hairlines_issues: JSON
    
    # Spot barvy
    spot_colors: JSON  # [{name, page, converted}]
    
    # Vrstvy
    layers_issues: JSON
    
    # DTF specifika
    dtf_white_layer: bool | None  # None = nekontrolováno
    dtf_transparent_bg: bool | None
    dtf_gamut_issues: JSON | None
    
    # LLM report
    llm_report_cs: str | None  # Lidsky srozumitelný popis v češtině
    
    # Celkové hodnocení
    severity: str  # "ok" / "warning" / "error"

# ImpositionConfig — nastavení imposice
class ImpositionConfig(Base):
    id: str (UUID)
    job_id: str (FK → Job)
    
    # Typ
    imposition_type: str  # "grid" / "booklet_saddle" / "booklet_perfect" / "cut_stack"
    
    # Arch
    sheet_format: str  # "SRA3" / "A3" / "B2" / "custom"
    sheet_width_mm: float
    sheet_height_mm: float
    
    # Layout
    rows: int
    cols: int
    gap_h_mm: float  # horizontální mezera
    gap_v_mm: float  # vertikální mezera
    margin_top_mm: float
    margin_right_mm: float
    margin_bottom_mm: float
    margin_left_mm: float
    
    # Stránky
    scale: float  # 1.0 = 100%
    rotation: int  # 0 / 90 / 180 / 270
    
    # Značky
    marks_crop: bool
    marks_fold: bool
    marks_info: bool  # název souboru, číslo archu, datum
    marks_registration: bool
    
    # Výstup
    output_path: str | None

# RepairLog — záznamy automatických oprav
class RepairLog(Base):
    id: str (UUID)
    job_id: str (FK → Job)
    action: str  # "rgb_to_cmyk" / "flatten_transparency" / "add_bleed" / "dtf_add_white"
    description_cs: str
    before_value: str | None
    after_value: str | None
    created_at: datetime
    success: bool
```

## API endpoints (FastAPI)

```
POST   /api/jobs/upload          # Nahrání PDF
GET    /api/jobs                 # Seznam jobů
GET    /api/jobs/{id}            # Detail jobu
DELETE /api/jobs/{id}            # Smazání jobu

POST   /api/jobs/{id}/preflight  # Spustit preflight
GET    /api/jobs/{id}/preflight  # Výsledek preflight

POST   /api/jobs/{id}/impose     # Spustit imposici
GET    /api/jobs/{id}/impose     # Stav imposice

POST   /api/jobs/{id}/repair     # Spustit Smart Repair
GET    /api/jobs/{id}/repair     # Log oprav

GET    /api/jobs/{id}/preview    # Náhled stránek (PNG)
GET    /api/jobs/{id}/download   # Stáhnout výstupní PDF

GET    /api/health               # Health check
```

## Preflight kontroly (pořadí implementace)

1. **Fonty** — embedded, subset, křivky (PyMuPDF)
2. **Rozlišení** — min DPI bitmap obrázků (PyMuPDF)
3. **Barevný model** — CMYK vs RGB vs Mixed (pikepdf)
4. **Průhlednosti** — detekce (pikepdf)
5. **Overprint** — detekce problematického overprintu (pikepdf)
6. **Ink coverage** — max TAC výpočet (Ghostscript)
7. **Hairlines** — linky < 0.25pt (PyMuPDF)
8. **Spot barvy** — detekce Pantone/custom (pikepdf)
9. **Vrstvy** — nezploštěné vrstvy (pikepdf)
10. **DTF — bílá vrstva** — White/spot white detekce (pikepdf)
11. **DTF — průhledné pozadí** — alpha channel kontrola (PyMuPDF)

## LLM Reporter

- **Primární:** Groq API (`llama-3.3-70b-versatile`)
- **Fallback:** Ollama lokální model (na ai-core)
- **Jazyk výstupu:** Čeština
- **Tón:** Přátelský, praktický, srozumitelný i laikovi
- **Formát:** Strukturovaný text s konkrétními radami jak chybu opravit
- Env: `GROQ_API_KEY` v `.env`

## Proměnné prostředí (.env)

```env
DATABASE_URL=sqlite:///./data/db/prepress.db
REDIS_URL=redis://redis:6379
GROQ_API_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
UPLOAD_DIR=./data/uploads
OUTPUT_DIR=./data/outputs
MAX_UPLOAD_SIZE_MB=500
GHOSTSCRIPT_PATH=/usr/bin/gs
```

## Konvence

- Python: PEP8, type hints všude, async/await pro I/O
- TypeScript: strict mode
- Názvy souborů výstupů: `{job_id}_imposed.pdf`, `{job_id}_repaired.pdf`
- Logy: strukturované JSON logy přes Python `logging`
- Chyby: vždy vrátit smysluplnou chybovou zprávu v češtině i angličtině

## Budoucí rozšíření (zatím neimplementovat)

- Zákaznický portál (B2B/B2C) — samostatná fáze
- Napojení na fakturační systém (`proreklamacz-droid/fakturace`)
- Hot folders (sledované složky)
- Napojení na n8n workflow
- Platební brána pro zákaznické opravy

## Poznámky

- Projekt je součástí širšího ekosystému: fakturace, YT Digest, claude-context
- Symlink `~/claude-context/prepress-server/` → tento CLAUDE.md po vytvoření přidat
- Po vytvoření přidat do `ai-registry`

---

## Stav vývoje

### ✅ Sprint 1 — HOTOVO (19. 5. 2026)
- Docker stack: FastAPI backend (8687) + Next.js frontend (8686) + Redis + RQ worker
- Upload PDF + základní analýza (stránky, rozměry, PDF verze)
- Preflight engine: fonty, rozlišení/DPI, barevný model (CMYK/RGB)
- LLM report v češtině přes Groq (llama-3.3-70b-versatile)
- Náhled první stránky (PNG)
- Job queue (3 fronty: high/normal/low)
- Tmavý frontend, dashboard, detail jobu
- Běží na RPi5 (192.168.0.122:8686)
- GitHub: proreklamacz-droid/prepress-server

### ✅ Sprint 2 — HOTOVO (19. 5. 2026)
1. **Správa souborů** — mazání v UI (confirm dialog v hlavičce jobu)
2. **Auto cleanup** — APScheduler (každou noc 3:00), POST /api/jobs/cleanup, GET /api/jobs/stats
3. **Storage widget** — na dashboardu: disk usage, status breakdown, ruční cleanup
4. **Imposice** — plný engine: grid, booklet saddle stitch, cut&stack + tiskové značky + náhled archu
5. **Tab UI** — job detail: tabbed panel Preflight / Imposice / Smart Repair

### 🔜 Sprint 3 — TODO
- Dokončení preflight engine (overprint, hairlines, spot barvy, vrstvy, ink coverage, DTF)
- Smart Repair (RGB→CMYK, flatten transparency, add bleed, DTF bílá vrstva)
- Telegram notifikace

### Známé opravy provedené při Sprintu 1
- next.config.ts → next.config.mjs (starší Next.js nepodporuje .ts)
- npm ci → npm install (chybějící package-lock.json)
- Odstraněn volume mount ./frontend:/app (přepisoval build)
- Přidána složka frontend/public/
- Opraveno doc.pdf_version() → doc.metadata.get("format")
