# 🚔 Autovelox & Tutor Italia — Home Assistant Integration

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2024.1%2B-blue)](https://www.home-assistant.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Integrazione per Home Assistant che scarica automaticamente i calendari settimanali degli **autovelox** e i tratti con **sistema Tutor** dalla Polizia di Stato, li geocodifica e li esporta su **Google My Maps**.

---

## Funzionalità

- 📥 **Download automatico** dei PDF della Polizia di Stato ogni settimana
- 🗺️ **Geocoding** delle strade (OpenStreetMap gratuito o Google Maps)
- 📍 **Export Google My Maps** con icone distinte per velox e tutor
- 📁 **Download KML** locale per importazione manuale
- 🔄 **Cache intelligente** su disco per minimizzare le chiamate API
- 📊 **Sensori HA** con conteggi e attributi dettagliati per regione
- ⏰ **Aggiornamento programmato** nel giorno/ora configurati

---

## Installazione via HACS

1. Apri HACS in Home Assistant
2. Vai su **Integrazioni** → menu `⋮` → **Repository personalizzati**
3. Aggiungi: `https://github.com/mcolaxx/ha-autovelox-tutor-ita`
4. Categoria: **Integrazione**
5. Clicca **Installa**
6. Riavvia Home Assistant
7. Vai su **Impostazioni → Dispositivi e servizi → Aggiungi integrazione**
8. Cerca **"Autovelox & Tutor Italia"**

---

## Configurazione

### Step 1 — Regioni e aggiornamento
Seleziona una o più regioni italiane da monitorare e il giorno/ora di aggiornamento settimanale.

### Step 2 — Geocoding
Scegli il provider per convertire i nomi delle strade in coordinate GPS:
- **OpenStreetMap** (consigliato): gratuito, nessuna chiave necessaria
- **Google Maps**: più preciso, richiede chiave API gratuita
- **Entrambi**: usa OSM come principale, Google come fallback

### Step 3 (opzionale) — Chiave API Google Maps
Se hai scelto Google o Entrambi, ottieni una chiave gratuita su [Google Cloud Console](https://console.cloud.google.com):
1. Crea un progetto
2. Abilita **Geocoding API**
3. Crea una chiave API (senza restrizioni per uso locale)

### Step 4 (opzionale) — Export Google My Maps
Abilita il salvataggio automatico dei punti sul tuo account Google My Maps. Richiede autorizzazione OAuth2 (il passo successivo guida l'utente).

---

## Entità create

| Entità | Tipo | Descrizione |
|--------|------|-------------|
| `sensor.velox_[regione]` | Sensore | N. velox attivi + lista con coordinate |
| `sensor.tutor_autostrade_italia` | Sensore | N. tratti tutor + lista per autostrada |
| `sensor.my_maps_[regione]` | Sensore | URL Google My Maps per la regione |
| `sensor.autovelox_tutor_riepilogo` | Sensore | Totale controlli + timestamp |

### Attributi sensore velox
```yaml
punti:
  - tipo_strada: "Autostrada"
    nome_strada: "A/14 Bologna-Taranto"
    provincia: "PU"
    latitudine: 43.91
    longitudine: 12.92
    valido_dal: "2026-06-08"
    valido_al: "2026-06-14"
```

### Attributi sensore tutor
```yaml
tratti_per_autostrada:
  A14:
    - autostrada: "A14"
      punto_inizio: "PESARO"
      punto_fine: "CATTOLICA"
      direzione: "DIR NORD"
      lat_inizio: 43.91
      lng_inizio: 12.90
```

---

## Servizi disponibili

### `autovelox_tutor.aggiorna`
Forza un aggiornamento immediato dei dati.
```yaml
service: autovelox_tutor.aggiorna
data:
  region: "marche"  # opzionale
```

### `autovelox_tutor.scarica_kml`
Genera un file KML salvato in `/config/www/autovelox_[regione].kml`.
Accessibile via `http://TUO-HA/local/autovelox_marche.kml`.
```yaml
service: autovelox_tutor.scarica_kml
data:
  region: "marche"
```

### `autovelox_tutor.esporta_mymaps`
Forza l'export su Google My Maps (richiede OAuth configurato).
```yaml
service: autovelox_tutor.esporta_mymaps
```

---

## Automazione esempio

```yaml
# Aggiorna ogni lunedì alle 6:00 (oltre all'automazione interna)
automation:
  - alias: "Aggiorna Velox Marche"
    trigger:
      - platform: time
        at: "06:30:00"
    condition:
      - condition: template
        value_template: "{{ now().weekday() == 0 }}"
    action:
      - service: autovelox_tutor.aggiorna
        data:
          region: marche
      - delay: "00:05:00"
      - service: autovelox_tutor.scarica_kml
        data:
          region: marche

# Notifica quando ci sono velox sulla tua regione
  - alias: "Notifica Velox Attivi"
    trigger:
      - platform: state
        entity_id: sensor.velox_marche
    condition:
      - condition: template
        value_template: "{{ states('sensor.velox_marche') | int > 0 }}"
    action:
      - service: notify.mobile_app
        data:
          title: "🚔 Autovelox Marche"
          message: >
            {{ states('sensor.velox_marche') }} velox attivi questa settimana.
```

---

## Importazione KML in Google My Maps

1. Vai su [maps.google.com](https://maps.google.com)
2. Menu hamburger → **I tuoi luoghi** → **Mappe** → **Crea mappa**
3. Clicca **Importa** nel layer
4. Carica il file `autovelox_[regione].kml`
5. I punti appaiono con icone distinte:
   - 🚔 Autovelox (icona rossa)
   - 📡 Tutor (icona blu)

---

## Sorgenti dati

- **Velox**: `https://www.poliziadistato.it/statics/34/[regione].pdf` — aggiornato settimanalmente
- **Tutor**: `https://www.poliziadistato.it/statics/19/elenco-tratti-controllati-con-il-tutor-[mese]-[anno].pdf` — aggiornato periodicamente
- Fonte ufficiale: [Polizia di Stato — Autovelox e Tutor](https://www.poliziadistato.it/articolo/autovelox-e-tutor-dove-sono)

---

## Note tecniche

- Il geocoding usa una cache persistente su disco (`/config/autovelox_geocode_cache.json`) per evitare chiamate API ripetute
- Le strade principali (SS16, A14, ecc.) hanno coordinate precaricate e non richiedono geocoding
- Nominatim (OSM) ha un rate limit di 1 richiesta/secondo: il primo avvio con molte regioni potrebbe richiedere qualche minuto
- La cache dati PDF viene invalidata dopo 8 giorni

---

## Licenza

MIT — vedi [LICENSE](LICENSE)

---

## Contributi

Pull request benvenute! Apri prima una issue per discutere le modifiche importanti.
