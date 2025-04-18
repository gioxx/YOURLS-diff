# YOURLS Diff

[Il file Readme è disponibile anche in inglese](README.md).

**YOURLS Diff** è uno script Python che semplifica l'aggiornamento di un'installazione YOURLS tramite FTP, creando un pacchetto ZIP con solo i file nuovi o modificati tra due tag di release.

## Caratteristiche

- Scarica automaticamente i due archivi ZIP (`old` e `new`) dal repository GitHub di YOURLS.  
- Confronta i file e individua quelli **nuovi** o **modificati**.  
- Genera un pacchetto ZIP contenente solo i file differenziati.  
- Produce un file manifest esterno (`.txt`) con l'elenco dei file cambiati.  
- Supporta la verifica SSL con possibilità di disabilitarla tramite flag.

## Requisiti

- Python **3.6+**  
- Librerie Python elencate in `requirements.txt`:
  ```txt
  requests>=2.20.0
  urllib3>=1.25.0
  ```

## Installazione

1. Clona il repository:
   ```bash
   git clone https://github.com/gioxx/YOURLS-diff.git
   cd YOURLS-diff
   ```

2. Crea un ambiente virtuale (opzionale ma consigliato):
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate   # Linux/MacOS
   .\.venv\Scripts\activate  # Windows
   ```

3. Installa le dipendenze:
   ```bash
   pip install -r requirements.txt
   ```

## Utilizzo

Lo script principale si chiama `YOURLS-diff_CreatePackage.py` e accetta i seguenti parametri:

| Opzione        | Descrizione                                                                 | Esempio                               |
|----------------|-----------------------------------------------------------------------------|---------------------------------------|
| `--old`        | **(obbligatorio)** Tag della release di partenza (es. `1.8.10`).            | `--old 1.8.10`                        |
| `--new`        | Tag della release di destinazione. Se omesso, viene usato `latest`.          | `--new 1.9.0`                         |
| `--output`     | Nome del file ZIP di output. Default: `YOURLS-update-OLD-to-NEW.zip`.       | `--output diff.zip`                   |
| `--no-verify`  | Disabilita la verifica del certificato SSL. _Non_ raccomandato.             | `--no-verify`                         |

### Esempi di esecuzione

- **Aggiornare da 1.8.10 all'ultima release**:
  ```bash
  python YOURLS-diff_CreatePackage.py --old 1.8.10
  ```
  Genera:
  - `YOURLS-update-1.8.10-to-<latest>.zip`  
  - `YOURLS-update-1.8.10-to-<latest>.txt` (manifest)

- **Aggiornare da 1.8.10 a 1.9.0 e nome personalizzato**:
  ```bash
  python YOURLS-diff_CreatePackage.py --old 1.8.10 --new 1.9.0 --output update.zip
  ```

- **Disabilitare la verifica SSL**:
  ```bash
  python YOURLS-diff_CreatePackage.py --old 1.8.10 --no-verify
  ```

## Struttura del repository

```text
├── YOURLS-diff_CreatePackage.py   # Script Python principale
├── requirements.txt              # Dipendenze Python
└── README.md                     # Questa documentazione
```

## Contribuire

Pull request e segnalazioni di issue sono benvenute! Per favore apri una nuova issue per bug o feature request.
