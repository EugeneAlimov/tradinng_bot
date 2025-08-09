
# Clean Crypto Bot (MVP)

A clean, MIT-licensed trading bot skeleton built with a clear architecture:
`core → domain → application → infrastructure → presentation`.

- Default symbol: `DOGE_EUR`
- Default mode: `paper`
- First run: `python main.py --mode paper --symbol DOGE_EUR`

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env
python main.py --validate
python main.py --mode paper --symbol DOGE_EUR
```

## Structure

```
src/
  core/
    domain/          # Value objects / entities
    ports/           # Ports (interfaces)
    errors/          # Exceptions
  domain/
    strategy/        # Strategies (MeanReversion baseline)
    risk/            # Risk service
    portfolio/       # Position service
  application/
    engine/          # Orchestrator / trading engine
  infrastructure/
    market/          # Paper market feed
    storage/         # File storage
    notify/          # Logger notifier
    exchange/        # (Stub) EXMO adapter placeholder
  presentation/
    cli/             # CLI app
```
