# YOURLS Diff

[Il file README è disponibile anche in inglese](README.md).

![Patch Build](https://github.com/gioxx/YOURLS-diff/actions/workflows/patch.yml/badge.svg)

**YOURLS Diff** è uno script Python che semplifica l'aggiornamento di un'installazione YOURLS via FTP creando un archivio ZIP contenente solo i file nuovi o modificati tra due tag di rilascio.

Se vuoi approfittare delle patch create automaticamente da questo script e da questo repository (tramite [questa GitHub Action](.github/workflows/patch.yml)), puoi consultare la sezione [Releases](https://github.com/gioxx/YOURLS-diff/releases). Il pacchetto più recente sarà sempre disponibile tramite il [Latest tag](https://github.com/gioxx/YOURLS-diff/releases/latest). Lo script viene eseguito ogni giorno a mezzanotte.

## Caratteristiche

- Scarica automaticamente i due archivi ZIP (`old` e `new`) dal repository GitHub di YOURLS.  
- Confronta i file e identifica quelli **nuovi**, **modificati** e **rimossi**.  
- Genera un pacchetto ZIP contenente solo i file modificati.  
- Produce un file manifest esterno (`.txt`) con l'elenco dei file modificati.  
- Genera un file `.removed.txt` se sono stati eliminati file nella nuova versione.  
- Crea uno script di deploy Bash (`.sh`) per aggiornare l'istanza YOURLS tramite rsync e SSH.  
- Supporta la verifica del certificato SSL con possibilità di disabilitarla.  
- (Opzionale) Genera uno script compatibile con WinSCP (`.winscp.txt`) per utenti Windows che vogliono scaricare ed eliminare file via SFTP.

## Requisiti

- Python **3.6+**  
- Librerie Python indicate in `requirements.txt`

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

Lo script principale si chiama `YOURLS-diff_CreatePackage.py` e accetta le seguenti opzioni:

| Opzione           | Descrizione                                                                                       | Esempio                              |
|-------------------|----------------------------------------------------------------------------------------------------|--------------------------------------|
| `--old`           | **(obbligatorio)** Tag della versione di partenza (es: `1.8.10`).                                  | `--old 1.8.10`                       |
| `--new`           | Tag della versione di destinazione. Se omesso, viene usato `latest`.                              | `--new 1.9.0`                        |
| `--output`        | Nome del file ZIP in uscita. Default: `YOURLS-update-OLD-to-NEW.zip`.                             | `--output diff.zip`                 |
| `--no-verify`     | Disattiva la verifica SSL (non consigliato).                                                      | `--no-verify`                       |
| `--summary`       | Genera un file `.summary.txt` con il riepilogo delle modifiche.                                   | `--summary`                         |
| `--only-removed`  | Genera solo il file `.removed.txt` (se ci sono file eliminati).<br>Genera anche lo script di rimozione remoto (`.sh`). | `--only-removed` |
| `--winscp`        | Genera uno script `.winscp.txt` per scaricare ed eliminare i file rimossi (richiede `--only-removed`). Utile per utenti Windows. | `--winscp` |

### Esempi

- **Aggiornare dalla 1.8.10 all'ultima versione disponibile**:
  ```bash
  python YOURLS-diff_CreatePackage.py --old 1.8.10
  ```

- **Aggiornare dalla 1.8.10 alla 1.9.0 con nome ZIP personalizzato**:
  ```bash
  python YOURLS-diff_CreatePackage.py --old 1.8.10 --new 1.9.0 --output update.zip
  ```

- **Generare solo la lista dei file rimossi e lo script di rimozione**:
  ```bash
  python YOURLS-diff_CreatePackage.py --old 1.8.10 --only-removed
  ```

- **Includere anche lo script WinSCP per la cancellazione remota**:
  ```bash
  python YOURLS-diff_CreatePackage.py --old 1.8.10 --only-removed --winscp
  ```

- **Disabilitare la verifica del certificato SSL**:
  ```bash
  python YOURLS-diff_CreatePackage.py --old 1.8.10 --no-verify
  ```

## Opzioni di Deploy

Una volta generato il pacchetto, puoi effettuare il deploy sulla tua installazione YOURLS usando:

- `YOURLS-deploy-OLD-to-NEW.sh`: script Bash con rsync e ssh (per utenti Unix/Linux)
- `YOURLS-update-OLD-to-NEW.winscp.txt`: script batch per WinSCP (Windows, con `--winscp`)
- **Upload manuale via FTP**: Estrai il contenuto del file ZIP e caricalo manualmente utilizzando qualsiasi client FTP/SFTP (es: FileZilla, Cyberduck, WinSCP, Transmit).

Ogni metodo/script ti consente di:
- Caricare i file modificati o aggiunti (in modalità standard)
- Rimuovere i file non più presenti nella nuova versione (solo con script automatici)

## Struttura del repository

```text
├── YOURLS-diff_CreatePackage.py   # Script Python principale
├── requirements.txt               # Dipendenze Python
├── LICENSE                        # Licenza del progetto
├── README.md                      # Documentazione in inglese
└── README_IT.md                   # Documentazione in italiano
```

## Contribuire

Sono ben accetti Pull Request e segnalazioni di bug! Apri una issue per segnalazioni o proposte di nuove funzionalità.
