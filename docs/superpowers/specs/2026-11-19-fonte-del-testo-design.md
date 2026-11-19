# Scelta della fonte del testo — disegno breve

Approvato il 2026-11-19.

## Perché

Il testo arriva da due fonti, scelte in automatico: LRCLIB (scritto da persone, tempi per riga,
a volte sbagliati) e la trascrizione della voce con Whisper (tempi precisi, parole a volte
sbagliate o mancanti). La scelta automatica non può sempre indovinare quale delle due sia
meglio per chi canta: deve poter decidere lui, brano per brano, dopo l'importazione.

## Cosa cambia

In **Modifica brano → Testo**, al posto del pulsante "Cerca di nuovo il testo", una scelta
"Fonte del testo" con un pulsante "Applica":

| Voce | Comportamento |
|---|---|
| Automatica (predefinita) | come oggi: LRCLIB se combacia con la voce, altrimenti trascrizione |
| LRCLIB | il testo di LRCLIB anche se il controllo contro la voce lo scarterebbe |
| Trascrizione dalla voce | Whisper, senza passare da LRCLIB |
| Nessun testo | toglie il testo: si gioca solo con le barre |

- La scelta si salva nel brano e vale per ogni ricerca successiva del testo.
- Con "LRCLIB", se il brano non c'è (o mancano artista e titolo) il testo resta vuoto e la
  schermata dice perché: non si passa di nascosto alla trascrizione.
- Con "Automatica", quando il testo di LRCLIB viene scartato la schermata dice il motivo,
  così si sa che c'è un'alternativa da provare.
- Applicare una fonte sostituisce le correzioni fatte a mano: si chiede conferma, come oggi.
- La tolleranza sulla durata (3 s) resta anche con "LRCLIB".

## Approcci considerati

1. **Scelta salvata nel brano (scelto).** Un campo in più nei dati del brano, letto dal passo
   del testo. Sopravvive alle rielaborazioni e si spiega da sola nella schermata.
2. **Parametro della sola richiesta "cerca di nuovo".** Meno dati, ma la scelta si perde alla
   prima rielaborazione e la schermata non può mostrare quale fonte è in uso per volontà di chi.
3. **Tenere entrambe le versioni e passare dall'una all'altra.** Comodo per confrontare, ma
   raddoppia i file del testo e le correzioni a mano andrebbero gestite per versione: troppo
   per il bisogno espresso.

## Fuori da questo lavoro

Scegliere tra le versioni presenti su LRCLIB; incollare un testo proprio.

## Lasciato a chi costruisce

Nomi dei campi, testi esatti dei messaggi, disposizione dei controlli nel pannello.
