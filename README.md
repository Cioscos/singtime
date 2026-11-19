# Karaoke a tracciato

Un gioco di canto: le note da cantare arrivano come barre verso una linea, e più
a lungo resti sulla barra con la voce, più punti fai. Il tracciato si ricava da
solo da qualsiasi brano, da un file audio o da un link di YouTube.

Tutto gira in locale sul tuo PC.

## Cosa serve

- Windows con [uv](https://docs.astral.sh/uv/), [Node.js](https://nodejs.org/) e [ffmpeg](https://ffmpeg.org/) nel PATH
- una scheda NVIDIA (consigliata: senza, l'elaborazione funziona ma è molto più lenta)
- cuffie e un microfono

## Prima installazione

```powershell
uv sync
npm --prefix frontend install
npm --prefix frontend run build
```

`uv sync` crea un ambiente Python 3.12 dedicato al progetto, senza toccare quello di sistema.

## Avvio

```powershell
uv run karaoke
```

Si apre una scheda del browser (Chrome o Edge) su `http://127.0.0.1:8765/`.
Per fermarlo: Ctrl+C nel terminale.

La prima volta che elabori un brano vengono scaricati i modelli (qualche gigabyte in tutto).

## Come si usa

1. **Aggiungi un brano**: incolla un link di YouTube oppure trascina un file audio. L'elaborazione
   richiede da mezzo minuto a un paio di minuti e si fa una volta sola per brano.
2. **Tara il ritardo** (Impostazioni → Tara): indossa le cuffie, avvicina una cuffia al microfono
   e premi Avvia. Serve a giudicare la tua voce nel momento giusto. Rifallo se cambi cuffie o microfono.
3. **Gioca**: canta seguendo le barre. Il pallino giallo è la tua voce; cantare un'ottava sopra o
   sotto vale lo stesso. Spazio mette in pausa.

**Usa le cuffie.** Con le casse il microfono sente la musica e il rilevamento della voce si confonde.

Dalla libreria puoi anche correggere titolo, artista e testo di un brano (**Modifica**) e guardare
come è stato costruito il tracciato (**Verifica**).

## Dove stanno i dati

Tutto in `data/` dentro la cartella del progetto:

- `data/library/<brano>/` — audio, base, voce isolata, tracciato, testo e record di ogni brano
- `data/models/` — i modelli scaricati
- `data/settings.json`, `data/note_params.json` — impostazioni e soglie del tracciato

Per usare un'altra cartella imposta la variabile d'ambiente `KARAOKE_DATA_DIR`.

## Tarare il tracciato

La schermata **Verifica** di un brano mostra la voce rilevata (puntini) e le barre generate,
con l'audio della voce isolata. I cursori cambiano le soglie dell'algoritmo e l'anteprima si
aggiorna subito. "Applica a questo brano" salva il tracciato di quel brano; "Salva come
predefiniti" vale per i brani elaborati in seguito.

Per confrontare i modelli candidati (separazione della voce e rilevamento dell'altezza) su
alcuni brani:

```powershell
uv run python -m karaoke.trial "https://www.youtube.com/watch?v=..." "https://..."
uv run python -m karaoke.trial --clean    # elimina le varianti create dalla prova
```

Ogni variante compare in libreria come un brano a sé, con il nome del modello tra parentesi quadre.
Non lanciare la prova mentre il server sta elaborando un brano: i due processi usano la stessa
cartella di lavoro per la separazione e si disturberebbero.
I modelli predefiniti si scelgono in `backend/karaoke/config.py`.

## Sviluppo

```powershell
uv run pytest                          # test del backend (-m "not slow" per saltare quelli con i modelli)
npm --prefix frontend test -- --run    # test del frontend
npm --prefix frontend run dev          # interfaccia in sviluppo, con il server Python avviato a parte
```

Design e piano di lavoro sono in `docs/superpowers/`.
