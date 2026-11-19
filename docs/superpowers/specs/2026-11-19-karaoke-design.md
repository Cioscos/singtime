# Karaoke a tracciato — design

Data: 2026-11-19
Stato: in attesa di approvazione

## 1. Intento

Un gioco di canto per uso personale. Non è un karaoke classico con il testo
che scorre: sullo schermo arrivano delle barre che indicano la nota da
raggiungere con la voce, e più a lungo il giocatore resta sulla barra con
l'intonazione giusta, più punti prende. Il riferimento dichiarato è Guitar
Hero, applicato alla voce.

Il punto forte è la **pre-elaborazione automatica**: dato un file audio o un
URL di YouTube, l'app isola la voce dal brano e ne ricava il tracciato da
cantare, senza che nessuno lo disegni a mano. Qualsiasi canzone diventa
giocabile.

Chi lo usa: una persona sola, a casa, sul proprio PC.

## 2. Obiettivi, non-obiettivi, anti-obiettivi

### Obiettivi

- Aggiungere un brano da file audio o da URL di YouTube e ritrovarselo
  giocabile dopo un'elaborazione automatica, fatta una volta sola.
- Un tracciato **cantabile**: barre pulite che assomigliano alla melodia,
  non una copia tremolante della voce originale.
- Giocare il brano con riscontro immediato sull'intonazione (sono sopra,
  sotto o sulla nota) e un punteggio che premia il tempo passato sulla barra.
- Testo riga per riga sullo schermo durante il gioco.
- Tutto in locale: nessun account, nessun server online.

### Non-obiettivi (fuori dalla prima versione)

- Due o più giocatori, in contemporanea o a turni.
- Modifica manuale delle note del tracciato.
- Cambio di tonalità del brano.
- Classifiche online, condivisione dei brani.
- Mostrare il video di YouTube: si usa solo l'audio.
- Impacchettamento come programma installabile (finestra propria, icona).
- Sillabe agganciate alle singole barre.

### Anti-obiettivi (lo renderebbero un fallimento anche se "funziona")

- Un tracciato che copia vibrato, glissati e respiri fino a diventare
  impossibile da seguire, oppure così semplificato da non assomigliare più
  alla canzone.
- Un ritardo tra voce e riscontro sullo schermo tale da far sembrare il
  punteggio ingiusto.
- Dover sistemare a mano ogni brano prima di poterlo giocare.

## 3. Vincoli

- Macchina di destinazione: Windows 11, NVIDIA RTX 4080, un solo utente.
  Non serve supportare altre piattaforme né macchine senza GPU (su CPU deve
  comunque funzionare, più lentamente e con un avviso).
- Già installati: Python 3.14 (di sistema, da non toccare), Node, ffmpeg,
  uv, git. Manca yt-dlp, che va aggiunto come dipendenza del progetto.
- YouTube si scarica con **yt-dlp** (deciso dall'utente).
- Si gioca **con le cuffie**. Con le casse il microfono riprenderebbe la
  musica e il rilevamento della voce si confonderebbe. L'app lo dichiara
  nella taratura iniziale; non prova a compensarlo.
- Uniche chiamate verso l'esterno: YouTube (download), LRCLIB (ricerca del
  testo, con artista, titolo e durata del brano), download dei pesi dei
  modelli al primo uso.

## 4. Approcci considerati

La scelta riguardava la forma dell'app.

| Approccio | Pro | Contro |
|---|---|---|
| **1. App web locale** (Python + browser) | Python è obbligato per l'analisi; il browser dà già microfono, audio sincronizzato e grafica fluida; iterazione rapida sull'aspetto | Qualche millisecondo di ritardo in più sul microfono, assorbito dalla taratura |
| 2. App desktop (Tauri + Python) | Sembra un programma vero | Impacchettamento e gestione del processo Python senza benefici per un utente solo |
| 3. Tutto Python (pygame) | Un solo linguaggio, ritardo microfono minimo | Libreria, avanzamento e testo faticosi e meno curati |

Scartati subito: motori di gioco (Godot, Unity), perché la grafica è 2D
semplice e collegarli all'analisi in Python complica soltanto.

**Scelto dall'utente: 1.** La 2 resta possibile in futuro senza riscrivere,
perché l'interfaccia è la stessa.

## 5. Architettura

```
┌──────────────────────── browser ────────────────────────┐
│  Libreria · Gioco · Risultato · Impostazioni            │
│  TypeScript, Canvas 2D, Web Audio, AudioWorklet (mic)   │
└───────────────▲─────────────────────────────────────────┘
                │ HTTP (API + file audio/tracciato) + avanzamento
┌───────────────┴──────────── Python ─────────────────────┐
│  API (FastAPI) · coda di elaborazione · libreria        │
│  Pipeline: acquisizione → separazione → altezza →       │
│            note → testo                                 │
└───────────────▲─────────────────────────────────────────┘
                │
        data/library/<id>/   (file su disco)
```

Due parti con confine netto:

- **Backend Python**: acquisisce i brani, esegue la pipeline, conserva la
  libreria, serve i file e l'interfaccia. Non sa nulla del gioco.
- **Frontend nel browser**: libreria, gioco, punteggio, impostazioni. Non
  fa analisi dei brani; riceve tracciato, testo e audio già pronti. Rileva
  dal vivo solo la voce del giocatore.

Si avvia con un comando e apre una scheda del browser. Browser di
riferimento: Chrome/Edge.

## 6. Pre-elaborazione

Cinque passi in sequenza. Ogni passo salva il proprio risultato su disco e
può essere rieseguito da solo: migliorare l'algoritmo delle note non deve
obbligare a rifare download e separazione.

| # | Passo | Ingresso → uscita | Strumento |
|---|---|---|---|
| 1 | Acquisizione | file o URL → audio originale + metadati | yt-dlp, ffmpeg |
| 2 | Separazione | audio → traccia voce + base strumentale | modello RoFormer (Mel-Band o BS); Demucs come riserva |
| 3 | Altezza | traccia voce → curva di altezza nel tempo, con indicazione "voce presente / assente" | SwiftF0 o FCPE (RMVPE, previsto all'inizio, non esiste come pacchetto installabile: vedi il piano) |
| 4 | Note | curva di altezza → elenco di barre | algoritmo nostro |
| 5 | Testo | metadati + traccia voce → righe sincronizzate | LRCLIB, poi Whisper |

### 6.1 Acquisizione

- File: qualsiasi formato che ffmpeg legge.
- URL: solo audio, migliore qualità disponibile. Un URL già presente in
  libreria non viene riscaricato: l'app lo segnala e apre il brano esistente.
- Metadati (titolo, artista, durata) ricavati da yt-dlp o dai tag del file.
  I titoli di YouTube sono sporchi ("Artista - Titolo (Official Video)"):
  si fa una pulizia ragionevole e titolo e artista restano modificabili
  dalla libreria.

### 6.2 Separazione e 6.3 Altezza

Modelli esatti da fissare in fase di piano con una prova su due o tre brani
dell'utente (vedi §11).

Tempo di elaborazione *(scelta mia)*: l'**obiettivo** è stare intorno al
minuto per un brano di 4 minuti sulla RTX 4080, a modelli già caricati,
escludendo il download e la trascrizione con Whisper (che parte solo quando
LRCLIB non trova il testo). È un obiettivo, non un limite rigido: se c'è da
scegliere, **la qualità della separazione viene prima della velocità**,
perché da lì dipende la qualità del tracciato. Due o tre minuti a brano
sono accettabili; l'elaborazione si fa una volta sola.

La curva di altezza ha una risoluzione temporale tra 10 e 16 ms, secondo
il modello scelto.

Limite noto e accettato: se nel brano ci sono cori o armonie, la traccia
voce li contiene e la curva segue la voce dominante. Può sbagliare in quei
punti.

### 6.4 Note: da voce a barre

È il cuore del gioco e la parte dove va messa la maggior parte del lavoro.
Nessuna libreria lo fa bene, quindi è un algoritmo scritto per questo
progetto.

Comportamento richiesto:

- **Il vibrato diventa una barra sola**, all'altezza centrale.
- **Un glissato tra due note** non genera una scaletta di barre minuscole:
  la transizione viene assegnata alle due note agli estremi.
- **Respiri, consonanti e rumori brevi** non generano barre.
- **Nessuna barra più corta di circa 100 ms**; pause molto brevi dentro la
  stessa nota vengono ricucite.
- Una nota tenuta resta una barra unica, anche lunga.
- L'altezza di ogni barra è quella realmente cantata dall'interprete (valore
  centrale del segmento, in semitoni con decimali). Non viene forzata sulla
  griglia dei semitoni: il riferimento è la voce originale, anche se il
  brano non è accordato a 440 Hz. *(scelta mia)*

Ogni barra ha: inizio, durata, altezza.

Tutte le soglie (durata minima, ampiezza del vibrato tollerata, pausa
ricucibile) stanno in un unico punto di configurazione, perché andranno
tarate a orecchio.

**Vista di verifica** *(scelta mia)*: una schermata di sviluppo che
sovrappone la curva di altezza grezza e le barre generate, con l'audio della
voce isolata. Serve a tarare l'algoritmo guardando e ascoltando. Senza,
la taratura è alla cieca.

### 6.5 Testo

Obiettivo sullo schermo: la riga corrente con le parole che si accendono a
tempo, e la riga successiva attenuata sotto.

1. Si cerca su **LRCLIB** un testo già sincronizzato riga per riga (artista,
   titolo, durata). Il testo è corretto perché scritto da persone.
2. Se non c'è, si **trascrive la traccia voce** con Whisper (modello
   multilingue, lingua rilevata in automatico: vedi §14), ottenendo parole
   con il loro tempo, raggruppate in righe.
3. Se non si ottiene nulla di utilizzabile, il brano si gioca **senza
   testo**. Non è un errore.

Tempo delle singole parole *(scelta mia)*: quando è disponibile (da
Whisper, o allineando il testo di LRCLIB alla traccia voce) le parole si
accendono al loro tempo reale. Quando c'è solo il tempo della riga,
l'accensione avanza in modo uniforme lungo la riga. La seconda forma è
sufficiente per la prima versione; la prima è un miglioramento.

**Versioni diverse dello stesso brano** *(scelta mia)*: la versione su
YouTube spesso non coincide con quella su cui è sincronizzato il testo di
LRCLIB (introduzione del video, versione dal vivo, versione estesa). Regola:
il testo di LRCLIB si accetta solo se la durata coincide con quella del
brano entro pochi secondi; altrimenti si passa a Whisper. Nessun
allineamento automatico tra testo e audio nella prima versione.

**Correzione a mano**: dalla libreria si può modificare il testo di ogni
riga e spostare **tutto il testo insieme** avanti o indietro nel tempo con
un unico valore per brano, per i casi in cui arriva in anticipo o in
ritardo. I tempi delle singole righe non si toccano. Si può anche rilanciare
la ricerca del testo dopo aver corretto artista e titolo.

### 6.6 Coda e avanzamento

- Un brano alla volta in elaborazione (una sola GPU); gli altri aspettano
  in coda.
- L'interfaccia mostra per ogni brano il passo in corso e l'avanzamento.
- Se un passo fallisce, il brano resta in libreria con l'errore visibile e
  un pulsante per riprovare dal passo fallito.
- I pesi dei modelli si scaricano al primo uso, con avanzamento visibile.

## 7. Libreria

Una cartella per brano in `data/library/<id>/` con: audio originale, base
strumentale, traccia voce, curva di altezza, barre, testo, metadati,
migliori punteggi. La posizione di `data/` è configurabile.

Dalla libreria si può: aggiungere (trascinando un file o incollando un URL),
vedere l'avanzamento, giocare, modificare titolo/artista/testo, eliminare.

## 8. Il gioco

### 8.1 Schermata

Scelta dall'utente tra tre mockup: **scorrimento orizzontale**.

```
 ▓▓▓▓▓░░░░░░░░░░░  avanzamento                         12.450
                                                      serie ×4
 acuto        │
              │                              ▬▬▬▬▬▬
   ▬▬▬  ▬▬    │▬▬▬▬▬▬▬     ▬▬▬         ▬▬
  ~~~~~~~~~~~~●               ▬▬▬
              │                   ▬▬▬▬▬▬
 grave        │        ← le note arrivano da destra
            adesso

           Canto piano sot|to la luna stasera
              e la notte mi risponde
```

- Il tempo scorre in orizzontale: le barre arrivano da destra verso una
  **linea "adesso" fissa**, a circa un terzo dello schermo da sinistra.
  Si vedono alcuni secondi di note in arrivo.
- L'altezza è in verticale: acuto in alto, grave in basso. L'intervallo
  verticale si adatta all'estensione del brano.
- La voce del giocatore è un **pallino sulla linea "adesso"** che lascia
  una **scia** verso sinistra: si vede subito se si è sopra o sotto.
- Le barre già passate mostrano quali tratti sono stati presi e quali no.
- In alto: avanzamento del brano, punteggio, serie.
- In basso: riga di testo corrente con le parole che si accendono, riga
  successiva attenuata.

Dettagli presenti nel mockup scelto:

- Barre in arrivo: colore pieno uniforme (blu nel mockup).
- Barra in corso: contorno evidenziato, con la parte già presa riempita
  in verde che avanza da sinistra.
- Barre passate: i tratti presi restano verdi, i tratti mancati diventano
  grigi spenti. Una stessa barra può avere entrambi.
- Pallino e scia della voce: giallo, la scia è una linea continua che
  segue l'altezza cantata.
- Testo: parole già cantate in verde, parola in corso bianca, parole
  ancora da cantare grigie.

Una copia del mockup è in
`docs/superpowers/specs/assets/2026-11-19-schermata-gioco.html` (opzione A;
si apre direttamente nel browser). Colori esatti e dettagli grafici oltre
questa struttura sono lasciati a chi costruisce.

### 8.2 Audio

- Si sente la **base strumentale** più la **voce originale come guida**, a
  volume regolabile da zero al massimo.
- Le due tracce partono sincronizzate. Il tempo del gioco si ricava
  dall'orologio dell'audio, non dai fotogrammi: barre, testo e punteggio
  restano agganciati alla musica anche se la grafica rallenta.
- Pausa, ripresa, ricomincia, esci.

### 8.3 Voce del giocatore

- Microfono via browser, con i filtri automatici (cancellazione dell'eco,
  riduzione del rumore, guadagno automatico) **disattivati**: altrimenti
  alterano la voce cantata.
- Rilevamento dell'altezza in tempo reale con il metodo McLeod, in un
  AudioWorklet, con una lettura ogni 10–20 ms circa.
- Soglie di volume e di chiarezza per ignorare silenzio e rumore: quando
  non si canta, il pallino sparisce.
- Scelta del microfono nelle impostazioni.

### 8.4 Ottave

Cantare la nota giusta un'ottava sopra o sotto **vale come giusta**. Senza
questo, un brano con voce femminile sarebbe ingiocabile per una voce
maschile e viceversa. Sullo schermo il pallino viene riportato all'ottava
più vicina alla barra, così resta leggibile.

### 8.5 Taratura del ritardo

Una procedura guidata iniziale, da meno di un minuto, che misura il ritardo
tra audio e microfono. Il valore viene salvato e resta regolabile a mano
dalle impostazioni. Il metodo di misura è lasciato a chi costruisce.

### 8.6 Punteggio

Deciso dall'utente: **più tempo sulla barra, più punti**.

Proposte mie, costruite su quella regola:

- Per ogni istante in cui c'è una barra: se la voce (riportata di ottava)
  è entro la tolleranza, quell'istante è "preso". I punti crescono in
  proporzione al tempo preso.
- **Difficoltà** = tolleranza: Facile ±2 semitoni, Normale ±1, Difficile ±0,5.
- **Serie**: una barra conta come riuscita se è stata presa per la maggior
  parte della sua durata; barre riuscite di fila alzano un moltiplicatore
  fino a ×4, che si azzera alla prima mancata.
- Cantare dove non ci sono barre non toglie punti.
- **Risultato** a fine brano: punteggio, percentuale di tempo preso, stelle
  da 0 a 5 basate sulla percentuale, record personale per brano e difficoltà.

I valori esatti (punti al secondo, soglia di "barra riuscita", fasce delle
stelle) sono lasciati a chi costruisce.

## 9. Schermate

- **Libreria**: elenco dei brani con stato; aggiunta da file o URL;
  avanzamento; modifica di titolo, artista e testo; eliminazione.
- **Gioco**: §8.
- **Risultato**: §8.6.
- **Impostazioni**: microfono, taratura, volume della guida, difficoltà.
- **Vista di verifica** (sviluppo): §6.4.

## 10. Errori da gestire

| Situazione | Comportamento |
|---|---|
| URL non valido o video non disponibile | Messaggio chiaro, niente brano in libreria |
| Brano senza voce (strumentale) | Avviso "nessuna voce trovata", brano non giocabile |
| Testo non trovato | Si gioca senza testo |
| Permesso microfono negato | Il gioco non parte e spiega come concederlo |
| GPU non disponibile | Elaborazione su CPU con avviso che sarà lenta |
| Passo della pipeline fallito | Errore visibile sul brano, riprova dal passo fallito |

## 11. Verifica

- **Algoritmo delle note**: test automatici su curve di altezza sintetiche
  (vibrato → una barra, glissato → due barre, rumore breve → nessuna barra,
  nota tenuta con pausa breve → una barra).
- **Punteggio e ottave**: logica isolata dalla grafica, con test automatici.
- **Pipeline**: una prova d'insieme su un breve spezzone audio.
- **Scelta dei modelli**: all'inizio del lavoro, una prova su due o tre
  brani dell'utente che confronti i candidati per separazione e altezza
  guardando il risultato nella vista di verifica.
- **Gioco**: verificato a mano, giocando.

### Chi ascolta

L'utente è disponibile per i controlli a orecchio e fa parte del ciclo di
lavoro. Il piano deve quindi prevedere, presto, una pipeline minima più la
vista di verifica, e un punto di controllo con l'utente **prima** di
rifinire l'algoritmo delle note. Brani di prova: vedi §14.

## 12. Stack

| Parte | Scelta | Di chi |
|---|---|---|
| Download YouTube | yt-dlp | utente |
| Forma dell'app | web locale: Python + browser | utente (approccio 1) |
| Backend | Python 3.12 gestito da uv (il 3.14 di sistema è troppo recente per alcune librerie audio), FastAPI | mia |
| Separazione | RoFormer, riserva Demucs | mia, da confermare con la prova |
| Altezza del brano | SwiftF0 o FCPE | mia, da confermare con la prova |
| Testo | LRCLIB, poi Whisper | mia |
| Frontend | TypeScript, Vite, Canvas 2D, Web Audio | mia |
| Voce dal vivo | metodo McLeod in AudioWorklet | mia |
| Libreria | file su disco, una cartella per brano | mia |

## 13. Lasciato a chi costruisce

- Modelli esatti e loro parametri, dopo la prova di §11.
- Valori delle soglie dell'algoritmo delle note.
- Framework dell'interfaccia (preferenza per qualcosa di leggero) e stile
  grafico oltre la struttura di §8.1.
- Formato dei file audio serviti al browser.
- Indice della libreria (database o lettura delle cartelle).
- Trasporto dell'avanzamento verso l'interfaccia.
- Metodo della taratura del ritardo.
- Valori esatti del punteggio.
- Dove salvare le impostazioni.

## 14. Cosa è stato confermato e cosa no

Confermato dall'utente durante la conversazione: giocatore singolo, tutto
in locale, yt-dlp, testo riga per riga, schermata a scorrimento
orizzontale, app web locale, base più voce guida a volume regolabile,
ottave equivalenti, tre livelli di difficoltà basati sulla precisione,
uso delle cuffie, taratura iniziale, niente video, esclusioni di §2.

Scelte mie, da considerare valide salvo obiezione alla lettura di questo
documento: altezza delle barre non forzata sui semitoni (§6.4), vista di
verifica (§6.4), tempo delle parole e regola sulle versioni diverse (§6.5),
spostamento globale del testo (§6.5), obiettivo sui tempi di elaborazione
(§6.2), serie e stelle (§8.6), valori di tolleranza delle difficoltà
(§8.6), stack di §12 dove indicato.

### Brani di prova (indicati dall'utente)

| Caso | URL |
|---|---|
| Facile: voce chiara | https://www.youtube.com/watch?v=DZHs-SRJbzU |
| Cori e seconde voci | https://www.youtube.com/watch?v=StZcUAPRRac |
| Veloce | https://www.youtube.com/watch?v=xFYQQPAOz7Y |

Sono il banco di prova per la scelta dei modelli (§11) e per la taratura
dell'algoritmo delle note (§6.4). Il brano con i cori è quello su cui
valutare il limite noto di §6.3.

### Lingua

L'utente canta soprattutto in inglese, ma non solo. La trascrizione deve
quindi usare un modello multilingue con riconoscimento automatico della
lingua, non un modello solo inglese. La lingua rilevata si salva nei
metadati del brano e resta correggibile dalla libreria, perché sul cantato
il riconoscimento automatico può sbagliare.
