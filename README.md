# PrePress Server

Webová aplikace pro předtiskovou přípravu PDF souborů. Součást ekosystému Království Tisku.

## Spuštění

```bash
cp .env.example .env
# Doplň GROQ_API_KEY a případně TELEGRAM_*
docker compose up -d
```

- Frontend: http://localhost:8686
- Backend API: http://localhost:8687
- Docs: http://localhost:8687/docs

## Funkce

- Nahrávání a analýza PDF souborů
- Preflight kontrola (fonty, rozlišení, barevný model, průhlednosti, inkový pokryv, hairlines, spot barvy)
- LLM report v češtině (Groq / llama-3.3-70b)
- Imposice (připraveno, zatím stub)
- Smart Repair (připraveno, zatím stub)

## Stack

| Vrstva | Tech |
|--------|------|
| Backend | FastAPI + SQLAlchemy + SQLite |
| Frontend | Next.js 14 + TypeScript + Tailwind |
| PDF | PyMuPDF (fitz) + pikepdf + Ghostscript |
| Queue | Redis + RQ |
| LLM | Groq API (llama-3.3-70b-versatile) |
