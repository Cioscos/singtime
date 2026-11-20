# Testo di LRCLIB allineato alla voce — disegno breve

Provato su quattro brani e approvato all'ascolto il 2026-11-20.
Estende `2026-11-19-fonte-del-testo-design.md`.

## Perché

La trascrizione con Whisper doveva dare «tempi precisi, parole a volte sbagliate». Sul cantato
non è così: su «Jump» il filtro dei silenzi (fatto per il parlato) scartava un terzo del canto,
frasi intere mancavano e alcune righe si accendevano 3 secondi prima. Whisper è un modello per
il parlato; modelli di trascrizione per il canto che lo battano non ne abbiamo trovati.

Quello che funziona sul canto è separare le due domande: **quali parole** (le ha già scritte
qualcuno, su LRCLIB, magari per un'altra versione del brano) e **quando** (si ricava da questa
registrazione).

## Cosa cambia

Una fonte del testo in più, «LRCLIB allineato alla voce» (`aligned`), sia come scelta in
**Modifica brano → Dati e fonte del testo** sia come passo della scelta automatica:

| Voce | Comportamento |
|---|---|
| Automatica | LRCLIB se combacia con la voce (come prima); se i tempi non combaciano, o LRCLIB ha solo un'altra versione, le sue parole allineate alla voce; se non c'è testo, o se ne ritrova meno di metà, trascrizione |
| LRCLIB | come prima |
| LRCLIB allineato alla voce | le parole di LRCLIB (versione più vicina per durata, anche solo testo semplice) sui tempi di questa registrazione; senza testo resta vuoto e dice perché |
| Trascrizione dalla voce | le parole di Whisper, senza filtro dei silenzi; i tempi rifiniti dall'allineatore (vedi sotto) |
| Nessun testo | come prima |

- Il testo allineato ha i tempi parola per parola, come quello trascritto.
- Le righe che in questa registrazione non ci sono (intro, code, strofe di un'altra versione) si
  tolgono; la nota del brano dice quante.
- La nota dice anche perché in automatico si è allineato («non combacia con la voce», «un'altra
  versione»).
- Se l'allineamento scelto a mano si rompe, o LRCLIB non risponde, è un errore visibile che lascia
  il testo che c'era; in automatico si ripiega sulla trascrizione.

## Come funziona (`pipeline/align.py`)

L'allineamento forzato «puro» di tutto il testo su tutta la voce non regge: appena testo e
registrazione divergono (voci sovrapposte, una ripetizione in più) scivola di un ritornello
intero e non si riprende. Quindi:

1. **Whisper senza filtro dei silenzi** trascrive la voce: serve solo a sapere all'incirca dove
   cade ogni riga. Le parole che sente dove non ci sono note, o di durata zero, si scartano.
2. **Ancore**: la più lunga sottosequenza comune tra parole scritte e parole sentite, tenendo
   solo i tratti di almeno tre parole di fila. Una riga è ancorata se ne è stata sentita metà.
3. **Allineatore forzato** (MMS_FA di torchaudio, già tra le dipendenze; modello da 1,2 GB in
   `data/models/aligner`): ogni riga ancorata in una finestra stretta attorno a dove l'ha
   sentita Whisper; le righe non ancorate, a gruppi, nello spazio tra due ancore. Un jolly tra
   le righe assorbe la voce che il testo non racconta.
4. **Ritocchi**, dove si sa che l'allineatore sbaglia: la prima parola rimasta agganciata alla
   coda della riga prima; le parole tenute a lungo, che mette verso la fine (lì vale l'attacco
   sentito da Whisper, se in quel punto si canta); le righe che non ha riconosciuto per niente
   (voci sovrapposte: valgono i tempi di Whisper); le cifre, che non sa leggere.
5. **Scarti**: una riga che nessuno ha sentito e che cade dove non si canta, o che l'allineatore
   non ha riconosciuto e poteva mettere lontano, o schiacciata in uno spazio troppo corto, in
   questa registrazione non c'è: meglio nessuna riga che una riga a caso.

Le soglie stanno in `config.py` (`ALIGN_*`) e sono tarate sui quattro brani della prova.

## Cosa si è misurato

Attacchi di riga contro il testo sincronizzato a mano su LRCLIB, tolto lo scarto mediano:

| Brano | Righe tenute | Esito |
|---|---|---|
| Jump (testo di una versione più corta di 9 s) | 56 su 73 | 45 entro 0,5 s; tolte intro e coda che qui non ci sono |
| Lose Yourself (rap, stessa versione) | 93 su 93 | 89 entro 0,5 s (scarto mediano 0,6 s) |
| Home (testo di una versione più lunga di 89 s) | 43 su 43 | coerente sezione per sezione; riferimento non confrontabile |
| Sonne (tedesco) | 32 su 40 | strofe e ritornelli a posto; il ponte, coperto dal coro, non si ritrova |

Whisper non dà lo stesso risultato a ogni giro: tra due esecuzioni qualche riga si sposta di
qualche decimo (una, su «Jump», di un secondo).

## Anche la trascrizione (`lyrics.transcribe`)

Per i brani che LRCLIB non ha resta la trascrizione, e aveva gli stessi difetti. Ora:

1. Whisper trascrive **senza filtro dei silenzi** e **senza contesto precedente**: con il
   contesto, sul canto, a volte gira a vuoto o salta strofe, e ogni giro dà un esito diverso.
2. Si tolgono le parole inventate: quelle dove non ci sono note e le ripetizioni a durata zero.
3. Le righe si formano come prima (`lines_from_words`), poi i tempi li rifinisce lo stesso
   allineatore, usando la trascrizione come testo (`place_lines`). Se l'allineatore non si può
   caricare, restano i tempi di Whisper.

Misurato sui quattro brani contro le versioni allineate (per «Sonne», corretta a mano), prima → dopo:

| Brano | Parole ritrovate | Parole giuste | Attacchi di riga entro 0,5 s |
|---|---|---|---|
| Jump | 72% → 84% | 89% → 96% | 71% → 83% |
| Lose Yourself | 32% → 91% | 86% → 91% | 96% → 100% |
| Sonne | 63% → 76% | 83% → 80% | 73% → 64% |
| Home | 92% → 94% | 90% → 92% | 95% → 90% |

- La trascrizione di prima su «Lose Yourself» dava 32% in due giri su tre e 91% nel terzo;
  quella nuova ha dato numeri identici in tre giri.
- Il riferimento viene dallo stesso allineatore, quindi sui tempi favorisce il «dopo». Contro
  gli attacchi segnati a mano su LRCLIB: «Jump» 16 righe su 24 → 27 su 33; «Lose Yourself»
  26 su 27 → 60 su 64.
- Su «Sonne» gli attacchi di riga non migliorano (16 righe su 22 → 14 su 22): nei ritornelli
  Whisper fonde o salta le ripetizioni in entrambe le versioni.
- Provate e scartate: dare a Whisper solo i tratti con note (instabile), accorciare a soglia
  le parole allungate (migliora poco).

## Limiti noti

- Le righe coperte da cori o effetti, che né Whisper né l'allineatore riconoscono, si perdono.
- Una parola gridata a inizio riga che Whisper non sente («Zwei, hier kommt die Sonne») fa
  accendere la riga un paio di secondi dopo.
- I testi in alfabeti non latini non si allineano (servirebbe traslitterarli): in automatico si
  finisce sulla trascrizione.
- Le soglie non sono ancora state provate su brani mai visti.

## Fuori da questo lavoro

Allineare sempre, anche quando LRCLIB combacia (darebbe i tempi per parola a tutti i brani, al
prezzo di mezzo minuto in più a brano); allineare un testo incollato a mano; scegliere tra le
versioni di LRCLIB.
