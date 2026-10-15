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

### ✅ Hotovo mimo sprint (19. 5. 2026)
- Prepress pipeline (GS): text→křivky, RGB→CMYK Fogra39/47, flatten průhledností, komprese
- Prepress se spouští před imposicí automaticky pokud byl spuštěn
- Předvolby imposice (presets): uložit/načíst/smazat pojmenované konfigurace
- Rozšířené ořezové značky: styl (čárky/rám), délka, odsazení, tloušťka, barva — výchozí vypnuto
- Zarovnání bloku na archu (h_align / v_align)
- Oprava mezer — přesné pozicování bez roztahování do buněk
- Nové typy imposice: Opakování (step_repeat), Koláž, Vyplnit arch, Rozřez duplex — auto-fit
- Grid: měřítko v %, live kalkulačka (výsledné rozložení, využití archu, varování)
- Grid: nikdy nepřekročí hranice archu — scale se dopočítá nebo rows/cols se omezí
- Endpoint POST /impose/calculate pro živý feedback bez generování PDF

### ✅ Kvalita exportu — HOTOVO (15. 10. 2026)
- **ICC Fogra39** se skutečně aplikuje: profil `data/icc/coated_FOGRA39.icc` (ECI ISOcoated_v2_eci.icc, není v gitu, je v `.gitignore`). Pipeline ho hledá v `/app/data/icc` (bind mount `./data`). GS potřebuje `--permit-file-read=<profil>`, jinak pod `-dSAFER` profil tiše nenačte.
  - Obnova profilu: stáhnout `https://www.eci.org/lib/exe/eci_offset_2009.zip`, z ní `ISOcoated_v2_eci.icc` uložit jako `data/icc/coated_FOGRA39.icc`.
  - Fogra47 profil zatím chybí (`uncoated_FOGRA47.icc`) — pipeline v tom případě hlásí varování a použije GS default.
- **Převzorkování fotek**: jen zmenšení nad 300 dpi (bicubic, threshold 1.0), nic se nezvětšuje. Konstanty `_TARGET_IMAGE_DPI`, `_DOWNSAMPLE_THRESHOLD` v `services/prepress_pipeline.py`; vypnutí přes `PrepressOptions.downsample_images`.
- **Striktní chyby pipeline** (`run_prepress_pipeline`): nenulový kód GS = selhání; GS řádek s „error“ i při kódu 0 = selhání („zdrojové PDF je pravděpodobně poškozené“); částečný výstup se maže. Po konverzi kontrola výstupu (otevře se, počet stran, rozměry stran ±2 pt). Vstup, který musel MuPDF opravit, = jen varování. Pravidlo „GS error = selhání“ lze zmírnit v `_gs_messages`.
- **Preflight**: rozlišení pod **200 dpi = varování**, pod 72 dpi = chyba (`services/preflight_engine.py`).
- **Provoz**: kontejnery backend/worker byly dřív vytvořené ručně (`docker run`) a bez bind mountu `./backend`. Od 15. 10. jsou vytvořené přes compose. Změna Pythonu = `docker restart prepress-server-backend-1 prepress-server-worker-1`; změna Dockerfile/requirements = `docker compose up -d --build backend worker` (v MCP sandboxu `docker compose` není, spouští Pavel na RPi5).

### ✅ Presety tiskových technologií + měření TAC — HOTOVO (15. 10. 2026)
- **Presety** v `backend/presets/technologies.json` (JSON, upravitelné bez změny kódu; po úpravě stačí restart backendu+workeru): `default`, `versant_280`, `dtf`, `roland`, `mutoh_uv`. Pole: `warn_dpi` (varování pod; pod 72 dpi vždy chyba), `max_tac` (null = bez limitu), `colorspace` (`cmyk` = RGB je varování, `any` = RGB v pořádku). Loader `services/technologies.py`, seznam `GET /api/technologies`.
- Rozhodnutí Pavla: spadávky se v preflightu neřeší, Riso mimo, 300 dpi všude (i fotoobrazy), výchozí = `default`. `default` = dosavadní chování (RGB = varování, bez limitu TAC). Hodnoty: Versant TAC 300 %, Roland/Mutoh TAC 300 %, DTF bez limitu.
- **Napojení:** `Job.technology` (výchozí `default`; sloupec doplňuje idempotentní `_migrate_sqlite()` při startu backendu, `create_all` sloupce nepřidává), `POST /api/jobs/{id}/preflight?technology=<klíč>` (neznámý klíč = 400, volba se uloží do jobu), `run_full_preflight(path, technology)`, frontend: select „Tisková technologie“ v záložce Preflight + řádek TAC.
- **Měření TAC** (`check_ink_coverage`): PyMuPDF CMYK raster stránky (max ~600 tis. px, ~0,1 s/stránka, bez numpy), bere se nejvyšší součet C+M+Y+K na pixel. Problém = `{page, tac, limit}` jen když preset má `max_tac`. U čistě RGB dokumentu se TAC neměří (None). Raster je zmenšený, tenké čáry s vysokým TAC můžou být podhodnocené.
- Test: syntetická PDF (reportlab) — TAC 400 % chyceno u Versant/Roland, čistá K=100 % → 100 %, RGB 300 dpi: default/Versant = varování, DTF/Roland/Mutoh = OK; end-to-end přes API + worker OK.
- **Nasazení:** backend+worker restartovány (bind mount). **Frontend je nutné přebuildit** (nemá bind mount): `docker compose up -d --build frontend` (spouští Pavel na RPi5). Typecheck frontendu neproběhl (v `frontend/` není lokální `typescript`), ověří ho až `next build`.

### ✅ Zpráva pro zákazníka + výstupní složka (outbox) — HOTOVO (15. 10. 2026, nic se neodesílá)
- **Princip:** fakta (nálezy + rady jak opravit) skládá vždy šablona z dat preflightu (`services/customer_message.py`, `build_findings`). LLM píše jen úvodní odstavec (2–3 věty); text z LLM projde jen když nepřidává čísla mimo nálezy, nemá markdown a nic neslibuje („připraveno k tisku", „bez jakýchkoli problémů") ani nepopírá nálezy (`_valid_intro`). Jinak se použije šablonový úvod — zpráva vznikne vždy.
- **Kaskáda úvodu:** Groq → Strata → šablona. Strata = `strata-batch` přes ollama-gate (`AI_CORE_OLLAMA_URL`, výchozí `http://192.168.0.174:11434`, `CUSTOMER_MSG_MODEL`, timeout 90 s); Strata je výchozí scéna na ai-core (načtená), volá se přes gate, který drží lease. Zdroj textu je v `message.json` jako `text_source` (groq | strata | template).
- **Tón (zatím):** vykání, podpis „Království tisku", technologie se v textu nezmiňuje (je jen v `message.json`). Závěrečná věta upozorňuje, že jde o automatickou kontrolu bez záruky úplnosti. Vzorové zprávy se budou ještě ladit (šablony textů v `build_findings` / `render_body`, `_VERDICT_TEXT`).
- **Outbox:** `/app/data/outbox/<job_id>/` (= host `data/outbox/`): `message.json`, `message.txt`, `.ready` (vzniká poslední; čte se jen složka s `.ready`; zápis atomický). `status: draft` — odesílání zatím neexistuje, endpointy pro agenta („neodeslané", „označit jako odeslané") přijdou až bude jasné, kdo zprávy odesílá. Mazání jobu (ruční, `/cleanup`, noční) maže i outbox složku — **až bude agent, upravit tak, aby neodeslané zprávy nemizely**.
- **Pozor na cestu:** kontejnery mají cwd `/app/backend`, relativní `./data/...` by skončilo v `backend/data` (v repu). Proto je `OUTBOX_DIR` absolutní.
- **Endpointy:** `GET /api/jobs/{id}/customer-message` (náhled, 404 dokud není), `POST /api/jobs/{id}/customer-message` (znovu složit z uloženého preflightu; 409 bez preflightu). Zpráva se tvoří automaticky na konci `task_run_preflight` (selhání nesmí shodit preflight).
- **Nález při testu:** Groq model `llama-3.3-70b-versatile` vrací **404 „model_not_found"** (k 15. 10. 2026). Kaskáda to přežije (spadne na Stratu), ale totéž postihuje i stávající interní `llm_reporter.generate_report` — ten chybu tiše spolkne a dává jen pravidlový text. Dostupné na Groq: `openai/gpt-oss-120b`, `openai/gpt-oss-20b`, `qwen/qwen3.8-27b`, `allam-2-7b`. Rozhodnutí o modelu čeká na Pavla (nechat Groq, nebo jít Strata-first).

### 🔜 Schváleno, ve frontě (15. 10. 2026)
- **Kontrolní náhled**: u DTF průhlednost s šachovnicí (PyMuPDF alpha), bílá vrstva zůstane bílá.
- **Detekce PDF/X** u příchozích souborů (jen informativně do preflightu/zprávy). PDF/X jako výstup zatím ne — vyplatí se jen pro externí tiskárny a muselo by být poslední krok po imposici.
- **Zkontrolovat `services/pdf_flattener.py`** (používá `routers/jobs.py` při uploadu) — má stejně shovívavé zacházení s chybami GS jako dřív prepress pipeline?

### 🔜 Sprint 3 — TODO
- **UI úpravy** (na příště — Pavel určí co přesně)
- **Brožura — posuny (creep/shingling)** — kompenzace posunu vnitřních listů
- **Hot folder** — sledovaná složka pro automatické zpracování:
  - Přetažení / nahrání PDF do `hot-in/` spustí automaticky: prepress pipeline → imposice (s výchozím presetem) → výstup do `hot-out/`
  - Konfigurace: která složka, který preset imposice, zda spouštět prepress
  - Notifikace výsledku (Telegram nebo log)
  - Implementace: watchdog (Python) jako samostatný Docker service nebo n8n workflow přes API
- **Frontend** — úpravy UI podle Pavlových přání
- **Brožura — posuny (creep/shingling)** — kompenzace posunu vnitřních listů podle tloušťky papíru a počtu listů; čím více listů, tím větší posun vnitřních stránek směrem ke středu
- Dokončení preflight engine (overprint, hairlines, spot barvy, vrstvy, DTF) — ink coverage/TAC hotovo
- Telegram notifikace

### Známé opravy provedené při Sprintu 1
- next.config.ts → next.config.mjs (starší Next.js nepodporuje .ts)
- npm ci → npm install (chybějící package-lock.json)
- Odstraněn volume mount ./frontend:/app (přepisoval build)
- Přidána složka frontend/public/
- Opraveno doc.pdf_version() → doc.metadata.get("format")
