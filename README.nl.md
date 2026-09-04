[![en](https://img.shields.io/badge/lang-en-red.svg)](README.md)
[![nl](https://img.shields.io/badge/lang-nl-orange.svg)](README.nl.md)

![Version](https://img.shields.io/github/v/release/remmob/timescale_database_reader 'Release') ![Downloads](https://img.shields.io/github/downloads/remmob/timescale_database_reader/total 'Downloads')

# Timescale Database Reader

Een Home Assistant-integratie die historische gegevens leest uit een TimescaleDB-database die gevuld wordt door de [LTSS-integratie](https://github.com/freol35241/ltss) of de [Scribe-integratie](https://github.com/jonathan-gatard/scribe), en die beschikbaar stelt via de Home Assistant WebSocket-API.

Deze integratie werkt **niet** met willekeurige TimescaleDB-databases; het schema moet overeenkomen met dat van LTSS of Scribe. Heb je een ander schema nodig, open dan een issue of draag zelf een reader bij.

Bijbehorende kaart: [timescale-plotly-card](https://github.com/remmob/timescale-plotly-card).

---

## Ondersteunde databases

| Bron | Hypertable | Toelichting |
|--------|-----------|-------|
| **LTSS** | `ltss` | Kolommen `time`, `entity_id`, `state`. Geen numerieke kolom. |
| **Scribe** | `states_raw` | Kolommen `time`, `metadata_id`, `state`, `value`, `attributes`. `entity_id` staat in de aparte tabel `entities`; de view `states` voegt die twee samen. |

> **Over het Scribe-schema:** huidige Scribe-versies schrijven `states_raw` met `metadata_id` als sleutel, niet met `entity_id`. `states` is een view over `states_raw` gejoind met `entities`. Alles wat snel moet zijn, leest beter een minutentabel dan die view.

### state vs value

Getallen en tekst staan in verschillende kolommen, en daar gaat het vaak mis:

| | Numerieke sensor | Tekstsensor (`on`/`off`, `Cooling in progress`, …) |
|---|---|---|
| `states_raw.value` | het getal (`23.24`) | `0` |
| `states_raw.state` | `NULL` | de tekst |
| `sensor_minute.value` | het getal (`23.24`) | `0` |
| `sensor_minute.state` | `'0'` | de tekst |

Bij een numerieke entiteit draagt alleen `value` de meetwaarde. In `sensor_minute` staat in de kolom `state` bovendien de letterlijke tekst `'0'` in plaats van `NULL`, omdat de vulprocedure `COALESCE(latest.state, '0')` gebruikt.

Alles wat deze gegevens gebruikt moet dus `value` lezen — of het veld `avg_state` uit het antwoord op de query, dat dit al oplost — en pas bij tekstentiteiten terugvallen op `state`. **Lees je eerst `state`, dan wordt elke numerieke reeks platgeslagen tot nul**, en omdat `'0'` een volstrekt geldig getal is gaat er nergens iets fout: je krijgt gewoon een grafiek vol nullen.

---

## Vereisten

| | |
|---|---|
| **TimescaleDB** | 2.13 of nieuwer. De SQL gebruikt `by_range()`, dat daarvoor niet bestaat |
| **PostgreSQL** | 14 of nieuwer |
| **Scribe of LTSS** | geïnstalleerd **en al aan het opnemen**, voordat je ook maar een van de SQL-bestanden draait |
| **Databaserol** | een rol die tabellen, views en jobs mag aanmaken in de doeldatabase |

## Volgorde van installeren

De stappen hangen van elkaar af; ze in de verkeerde volgorde doen is de meest
voorkomende manier om met lege grafieken te eindigen.

1. Installeer Scribe (of LTSS) en laat het een paar minuten opnemen, zodat er data in `states_raw` staat
2. Draai `SQL/scribe/01_sensor_minute_aggregate.sql` en vul het aggregaat daarna met terugwerkende kracht
3. Draai `SQL/scribe/02_sensor_minute_table.sql` en zaai `sensor_minute` daarna in
4. Installeer deze integratie en voeg een verbinding toe, met `table` op `sensor_minute`
5. Installeer de [kaart](https://github.com/remmob/timescale-plotly-card) en bouw een grafiek

Stap 4 controleert niet of de tabel bestaat — de verbindingstest doet alleen
`SELECT 1` — dus je kunt hem ervoor of erna invullen, maar er komt geen grafiek
voordat stap 2 en 3 klaar zijn.

## Installatie

### HACS (aanbevolen)

1. HACS → ⋮ → Aangepaste repositories (oudere HACS-versies: HACS → Integraties → ⋮)
2. URL: `https://github.com/remmob/timescale_database_reader`, categorie: Integration
3. Zoek op **Timescale Database Reader** en installeer
4. Herstart Home Assistant

### Handmatig

1. Kopieer `custom_components/timescale_database_reader` naar de map `custom_components` van je Home Assistant
2. Herstart Home Assistant

### Configuratie

**Instellingen → Apparaten en diensten → Integratie toevoegen → Timescale Database Reader**, en vul host, poort, gebruikersnaam, wachtwoord, databasenaam en de standaardtabel in.

| Veld | Voorbeeld | Betekenis |
|-------|---------|---------|
| `host` / `port` | `192.168.1.10` / `5432` | TimescaleDB-server |
| `database` | `statistics` | Databasenaam |
| `name` | `Statistics` | Weergavenaam; hier matcht `database:` in een kaart ook op |
| `table` | `sensor_minute` | Standaardtabel wanneer een query geen `table` meegeeft |
| `include_extra_columns` | `false` | Geef ook de overige kolommen van de bevraagde tabel terug. Staat standaard uit — zie [Extra kolommen](#extra-kolommen-opt-in) |

Heb je meerdere databases (bijvoorbeeld LTSS **én** Scribe), voeg dan per database een integratie-item toe.

> **Deze instellingen staan op twee plekken.** De integratie leest `{**entry.data, **entry.options}`, dus alles wat je via het *opties*-scherm zet wint van wat je bij het toevoegen hebt ingevuld. Lijkt een gewijzigde tabel geen effect te hebben, kijk dan op beide plekken — herconfigureren werkt `data` bij, de optiestroom schrijft naar `options`.

### Databaserollen en rechten

Is de rol die de SQL-objecten aanmaakt dezelfde als waarmee de integratie verbindt, dan hoef je niets te doen. Verschillen ze — wat zo gebeurd is wanneer een beheerder de SQL als `postgres` draait terwijl Scribe en de reader hun eigen rol gebruiken — dan valt de reader om met *permission denied*. Beide SQL-bestanden eindigen met een uitgecommentarieerd blok met grants; haal het commentaarteken weg en vul je eigen rol in:

```sql
GRANT USAGE ON SCHEMA public TO <reader_role>;
GRANT SELECT ON sensor_minute, sensor_minute_aggregate_entity, entities TO <reader_role>;
```

Wie eigenaar is van wat, zie je met:

```sql
SELECT tablename, tableowner FROM pg_tables WHERE schemaname = 'public'
UNION ALL
SELECT viewname, viewowner FROM pg_views WHERE schemaname = 'public' ORDER BY 1;
```

> **Een kaart aan een verbinding koppelen:** de optie `database:` van een kaart wordt hoofdletterongevoelig vergeleken met zowel de *databasenaam* als de *weergavenaam* van het item. `database: scribe` komt alleen uit bij een verbinding die letterlijk `scribe` heet; anders wordt de eerst geconfigureerde verbinding als terugval gebruikt. Noem het item naar wat je in je kaarten schrijft, dan voorkom je verrassingen.

---

## Aanbevolen: bouw de minutentabellen

Grafieken willen één waarde per entiteit per minuut, met de laatst bekende waarde doorgetrokken zodat lijnen en balken geen gaten hebben. Ruwe state-rijen kunnen dat niet leveren: Home Assistant schrijft alleen een rij als een waarde verandert.

Twee lagen doen dit. Installeer ze in volgorde.

### Stap 1 — het continue aggregaat van 1 minuut

`SQL/scribe/01_sensor_minute_aggregate.sql`

Maakt `sensor_minute_aggregate` (één rij per entiteit per minuut waarin iets veranderde) plus `sensor_minute_aggregate_entity`, een dunne view die `entities` er weer bij joint zodat queries verderop `entity_id` kunnen gebruiken. Het zet ook het bewaar- en compressiebeleid en een verversbeleid dat elke minuut draait.

Het aggregaat moet groeperen op `metadata_id`, omdat een continu aggregaat maar één hypertable mag lezen — het kan `entities` niet zelf joinen. Daar is die extra view voor.

Vul na het aanmaken de historie aan die je al hebt. Draai dit **buiten** een transactieblok:

```sql
CALL refresh_continuous_aggregate('sensor_minute_aggregate', NULL, NULL);
```

### Stap 2 — de voorgevulde tabel `sensor_minute`

`SQL/scribe/02_sensor_minute_table.sql`

Maakt de hypertable `sensor_minute` (`minute`, `entity_id`, `state`, `value`), de indexen, het beleid, de procedure `sensor_minute_refresh()` en een job die die elke minuut draait. Elke draai trekt voor elke entiteit voor elke minuut de laatst bekende waarde door.

Zaai de tabel eenmalig in voordat de job het kan overnemen — de procedure verlengt alleen een bestaande reeks en doet niets op een lege tabel. De uitgecommentarieerde `INSERT` onderaan het bestand doet dat.

> **Begin klein.** Het inzaaien schrijft één rij per entiteit per minuut: `entiteiten × dagen × 1440`. Met 443 entiteiten en 30 dagen is dat ruwweg **19 miljoen rijen in één transactie**, wat lang kan duren, de WAL laat opzwellen en ondertussen locks vasthoudt. Zaai eerst een paar dagen in, controleer of je grafieken kloppen, en verbreed het pas daarna. Het bestand bevat ook een lus per dag die per dag commit — gebruik die voor een lange backfill.

Controleer of de job draait:

```sql
SELECT job_id, proc_name, schedule_interval, next_start
FROM timescaledb_information.jobs
WHERE proc_name = 'every_minute_refresh';

SELECT last_run_status, last_run_started_at, total_failures
FROM timescaledb_information.job_stats
WHERE job_id = (SELECT job_id FROM timescaledb_information.jobs
                WHERE proc_name = 'every_minute_refresh');
```

### Welke tabel moet een kaart gebruiken?

| Tabel | Snelheid | Wanneer gebruiken |
|-------|-------|-------------|
| **`sensor_minute`** | snel, geïndexeerd op `(entity_id, minute DESC)` | **De standaardkeuze.** Elke grafiek, elk bereik. |
| `sensor_minute_aggregate_entity` | snel | Als je alleen de minuten wilt waarin echt iets veranderde, zonder de doorgetrokken opvulling. |
| `states_raw` / `ltss` | matig | Ruwe, niet-geaggregeerde historie. |
| `states` | traag | Vermijden voor grafieken; het is een view die bij elke leesactie joint. |
| `sensor_minute_scribe` | **erg traag** | Verouderde LOCF-view, opgevolgd door `sensor_minute`. Zie de waarschuwing hieronder. |

```yaml
type: custom:timescale-plotly-card
database: statistics
table: sensor_minute
sensor_id: sensor.temperature_woonkamer
```

> **⚠️ Vermijd `sensor_minute_scribe` (en `sensor_minute_ltss`).** Deze views bouwen een raster van elke minuut sinds de oudste bucket × elke entiteit en draaien per cel een gecorreleerde subquery tegen een andere view, dus er is geen bruikbare index. Voor kortgeleden toegevoegde entiteiten wordt het pathologisch: voor elke minuut vóór hun eerste meting moet de subquery de hele reeks aflopen om te bewijzen dat daar niets staat, dus een venster dat verder terugreikt dan de eerste meting van die entiteit loopt in een time-out (>120 s) terwijl een venster dat erna begint direct antwoordt. Eén zo'n entiteit is genoeg om de queries van andere kaarten op dezelfde pagina te laten vastlopen. De tabel `sensor_minute` bestaat precies om dit te vermijden. De oude bestanden staan ter referentie nog in `SQL/`.

### Schijfgebruik

De ruwe state-rijen zijn het volumineuze deel. Elke rij draagt de attributen van
de entiteit als JSON mee — icoon, weergavenaam, eenheid — bij elke schrijfactie
opnieuw en volledig. Op een echte installatie was dat 154 van de ongeveer 205
bytes payload per rij.

Compressie lost het grootste deel op. Gemeten op 443 entiteiten die ongeveer een
miljoen rijen per dag schrijven:

| | voor | na |
|---|---|---|
| Eén wekelijkse `states_raw`-chunk | 300 MB | 8,9 MB |
| Dertien oudere chunks | 383 MB | 16 MB |
| `sensor_minute` (LOCF-data comprimeert buitengewoon goed) | 10,9 GB | 22 MB |

**Zet `compress_after` ruim onder `drop_after`.** Zijn ze gelijk — allebei drie
maanden bijvoorbeeld — dan verwijdert het bewaarbeleid elke chunk precies op het
moment dat die in aanmerking komt voor compressie, dus er wordt nooit iets
gecomprimeerd en het beleid doet helemaal niets. De SQL hier gebruikt zeven dagen.

Controleer of het echt werkt:

```sql
SELECT hypertable_name,
       count(*) FILTER (WHERE is_compressed) AS compressed,
       count(*) AS chunks
FROM timescaledb_information.chunks GROUP BY 1;
```

Alleen de chunk waarin op dit moment geschreven wordt hoort ongecomprimeerd te
zijn. Is die chunk zelf groot, verklein dan `chunk_time_interval`: de actieve
chunk kan niet gecomprimeerd worden, dus het interval bepaalt de ondergrens van
je ongecomprimeerde werkvoorraad.

Compressie is een wijziging van het opslagformaat, geen samenvatting:
rijaantallen, waarden en tijdstempels blijven ongewijzigd, en
`decompress_chunk()` draait het terug.

### De minutentabel gelijk houden met de werkelijkheid

Het continue aggregaat loopt een minuut of twee achter op de echte tijd. Voegt de verversprocedure alleen maar rijen toe *na* `max(minute)`, dan houden die achterste rijen de waarde die ze toevallig hadden toen ze geschreven werden en worden ze nooit meer gecorrigeerd — de achterstand wordt dan permanent.

Je merkt het aan tellers. Een `utility_meter` met `cycle: hourly` reset precies op `:00`, maar in een achterlopende `sensor_minute` verschijnt die reset pas twee minuten later. Een grafiek die op het hele uur bucket, bemonstert elk uur dan een paar minuten te vroeg, waardoor elke balk te weinig rapporteert en de staart van elke periode in de volgende balk terechtkomt.

`sensor_minute_refresh()` verwerkt daarom een kort achterliggend venster opnieuw (standaard 5 minuten) in plaats van alleen aan te vullen, en doet een upsert op `(minute, entity_id)`. Geef een andere overlap mee als jouw opstelling dat nodig heeft:

```sql
CALL public.sensor_minute_refresh(INTERVAL '10 minutes');
```

Controleer de achterstand met:

```sql
SELECT max(minute) AS last_row,
       date_trunc('minute', now()) AS now_minute,
       date_trunc('minute', now()) - max(minute) AS lag
FROM sensor_minute;
```

---

## Bevragen via de WebSocket-API

Berichttype: `timescale/query`.

| Veld | Type | Verplicht | Omschrijving |
|-------|------|----------|-------------|
| `sensor_id` | string | **ja** | Entiteit-ID om te bevragen |
| `start` | ISO-tekst of Unix-tijdstempel | **ja** | Begin van het venster |
| `end` | ISO-tekst of Unix-tijdstempel | **ja** | Einde van het venster |
| `limit` | int | nee | Maximum aantal rijen (0 = geen limiet, max 10000). Wordt op de staart van het resultaat toegepast |
| `downsample` | int | nee | Bucketgrootte in seconden (0 = ruwe rijen) |
| `downsample_method` | `avg` \| `last` \| `sum` | nee | Aggregatie binnen een bucket. Standaard `last` voor minuut- en aggregaattabellen, anders `avg`. Gebruik `sum` voor rijen die per bucket al een hoeveelheid zijn — kosten of een aantal kWh per uur — zodat een query om dagbuckets die uren optelt in plaats van ze te middelen of de laatste te nemen |
| `table` | string | nee | Tabel of view om te lezen; valt terug op de tabel die bij het item is ingesteld |
| `database` | string | nee | Welke verbinding te gebruiken, gematcht op databasenaam of weergavenaam |
| `entry_id` | string | nee | Configuratie-item om te gebruiken; gaat voor op `database` |

Limieten die de integratie afdwingt: venster ≤ 365 dagen, `limit` ≤ 10000, resultaat ≤ 50000 rijen.

De reader kiest de tijdkolom zelf: `time`, anders `bucket`, anders `minute`. Heeft de tabel een kolom `value`, dan krijgt die de voorkeur, met een numerieke cast van `state` als terugval.

### Antwoord

Met `downsample > 0`:

| Veld | Omschrijving |
|-------|-------------|
| `bucket` | Begin van de bucket |
| `avg_state` | Geaggregeerde numerieke waarde (`avg()` of `last()`) — **gebruik deze** |
| `state` | Laatste ruwe teksttoestand in de bucket |
| `min_state` / `max_state` | Numeriek minimum en maximum binnen de bucket |

Met `downsample = 0`:

| Veld | Omschrijving |
|-------|-------------|
| `time` | Tijdstempel van de rij |
| `state` | Ruwe teksttoestand |
| `avg_state` | Opgeloste numerieke waarde — **gebruik deze** |

> Denk aan de scheiding tussen `state` en `value` hierboven: bij numerieke entiteiten is `state` de plaatshouder `'0'`. Lees altijd `avg_state`, en val alleen terug op `state` wanneer je teksttoestanden aan het vertalen bent.

### Extra kolommen (opt-in)

De verzameling velden hierboven ligt vast. Bevraag je een view met eigen kolommen — een label, een
eenheid, een opgemaakt tijdstip — dan vallen die weg, omdat de reader ze nooit heeft geselecteerd.

Zet **Include extra columns** aan op het configuratie-item en elke overige kolom van de bevraagde
tabel komt mee. Gereserveerde namen worden nooit dubbel geselecteerd: `entity_id`, `value`, `state`,
`time`, `bucket` en `minute` handelt de query zelf al af.

```sql
-- met downsample > 0 wordt elke extra kolom in last() verpakt zodat GROUP BY geldig blijft
SELECT time_bucket(:bucket, bucket) AS bucket,
       last(value, bucket)  AS avg_state,
       last(state, bucket)  AS state,
       min(value)           AS min_state,
       max(value)           AS max_state,
       last("label", bucket) AS "label",
       last("unit",  bucket) AS "unit"
FROM my_view
WHERE entity_id = :entity_id AND bucket BETWEEN :start AND :end
GROUP BY bucket
```

Punten om in gedachten te houden:

- **Staat standaard uit.** Met de optie uit is de gegenereerde SQL teken voor teken wat hij was, dus
  bestaande dashboards kunnen er niet door geraakt worden.
- **De instelling geldt per configuratie-item, niet per tabel.** Zet je hem aan, dan geeft *elke*
  tabel die via die verbinding bevraagd wordt zijn extra kolommen terug. Voor gewone state-tabellen
  verandert dat niets: een tabel waarvan de kolommen alleen `time`/`minute`, `entity_id`, `state` en
  `value` zijn, heeft geen overige kolommen.
- **Geen risico op injectie.** Kolomnamen komen uit `information_schema` via `_fetch_table_columns`,
  dus het zijn per definitie echte kolommen van die tabel. Ze worden bovendien gequote, zodat namen
  met hoofdletters of spaties veilig zijn.
- **Grafieken negeren onbekende sleutels.** Alleen een tabelweergave laat de extra kolommen zien.
  Let op dat `table_columns` in de timescale-plotly-card de kolommen *ordent* in plaats van ze te
  filteren: alles wat niet genoemd is, komt achteraan.

#### Toepassing: dagpieken als leesbare tabel

De vraag was eenvoudig genoeg: wat was het hoogste verbruik vandaag, wanneer was dat, en hoe lang
duurde het? Een piek van één seconde zegt niets, dus de duur telt net zo zwaar als de waarde.

Dat is allemaal een query, geen toestandsmachine — de ruwe states staan al in de database. Een
dagtabel houdt één rij per sensor per dag bij: de hoogste waarde, het moment waarop de piek
*begon*, het moment waarop de waarde zelf zijn top bereikte, en hoe lang hij binnen een kleine marge
van de piek bleef. Een view presenteert die rijen vervolgens per sensor, met de leesbare stukken als
eigen kolommen:

```sql
CREATE OR REPLACE VIEW sensor_extremes_single AS
SELECT (day::timestamp AT TIME ZONE 'Europe/Amsterdam') AS bucket,
       entity_id || '_max' AS entity_id,
       max_value           AS value,
       max_value::text     AS state,
       label                                                   AS sensor,
       round(max_value::numeric, 2) || ' ' || unit             AS waarde,
       to_char(max_start AT TIME ZONE 'Europe/Amsterdam',
               'HH24:MI:SS')                                   AS tijd,
       max_episode_s || ' s'                                   AS duur
FROM sensor_extremes_daily JOIN sensor_extremes_config USING (entity_id);
```

Twee details die je makkelijk verkeerd doet:

- **Cast de dag in de juiste tijdzone.** Een kale `day::timestamptz` op een server die op UTC draait
  komt uit op middernacht UTC, wat in een Nederlandse frontend als 02:00 verschijnt. `AT TIME ZONE`
  lost dat op en handelt de zomertijd meteen mee af.
- **Een waarde geldt tot de volgende meting.** Home Assistant schrijft alleen bij verandering, dus
  een duur is het gat tussen twee metingen (`lead(time)`), nooit een telling van rijen.

Met **Include extra columns** aan kan de kaart die kolommen rechtstreeks tonen:

```yaml
type: custom:timescale-plotly-card
database: scribe
table: sensor_extremes_single
show_chart: false
show_table: true
table_columns: [sensor, waarde, tijd, duur]
energy_time_ranges: [today, week, month, year, years, custom]
default_range: today
entities:
  - sensor_id: sensor.power_inuse_total_max
    name: Total power in use
  - sensor_id: sensor.dsmr_sensor_voltage_l1_max
    name: Voltage L1 highest
```

| sensor | waarde | tijd | duur |
|---|---|---|---|
| Gebruikt vermogen totaal | 4063 W | 17:45:57 | 6 s |
| Spanning L1 hoogste | 244.9 V | 10:30:56 | 183 s |
| Spanning L1 laagste | 232.5 V | 10:52:12 | 35 s |

De kaart voegt daar nog `series`, `bucket`, `avg_state`, `state`, `min_state` en `max_state` van
zichzelf aan toe, en `table_columns` filtert die niet weg. Zet de vier die je wilt hebben vooraan en
verberg de rest met card-mod:

```yaml
card_mod:
  style: |
    .ts-data-table td:nth-child(n+5),
    .ts-data-table th:nth-child(n+5) { display: none !important; }
    .ts-data-table td, .ts-data-table th { white-space: normal !important; }
```

Die laatste regel telt ook: de kaart zet `white-space: nowrap` op elke cel en `overflow-x: auto` op
de container, dus één lange cel is genoeg voor een horizontale schuifbalk.

### Voorbeeld

```python
import asyncio, json, websockets

async def query_timescale():
    uri = "ws://homeassistant.local:8123/api/websocket"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({"type": "auth", "access_token": "YOUR_LONG_LIVED_TOKEN"}))
        print(await ws.recv())

        await ws.send(json.dumps({
            "id": 1,
            "type": "timescale/query",
            "sensor_id": "sensor.temperature_woonkamer",
            "database": "statistics",
            "table": "sensor_minute",
            "start": "2026-01-01T00:00:00Z",
            "end": "2026-01-01T12:00:00Z",
            "downsample": 300,
            "downsample_method": "last",
        }))
        while True:
            msg = await ws.recv()
            print(msg)
            if '"result"' in msg or '"error"' in msg:
                break

asyncio.run(query_timescale())
```

---

## Meerdere databases

Voeg per database een integratie-item toe. Kaarten kiezen een verbinding per kaart of per reeks:

```yaml
type: custom:timescale-plotly-card
title: Living room climate
entities:
  - sensor_id: sensor.temperature_woonkamer
    database: statistics
    table: sensor_minute
  - sensor_id: sensor.amber_4h_average_ambient_temperature
    database: ltss
    table: ltss
```

Een `database` of `table` op reeksniveau gaat voor op die van de kaart. Zonder allebei worden de eerst geconfigureerde verbinding en de bijbehorende standaardtabel gebruikt.

---

## Problemen oplossen

**"No database connection available"** — er is geen configuratie-item geladen. Kijk op de integratiepagina of er een item is mislukt.

**Elke reeks staat plat op nul** — er wordt ergens `state` gelezen in plaats van `value`/`avg_state`. Zie [state vs value](#state-vs-value).

**Queries lopen in een time-out** — je zit vrijwel zeker op `sensor_minute_scribe` of `states`. Schakel over naar `table: sensor_minute`. Is dat ook traag, controleer dan of `sensor_minute_entity_idx` bestaat.

**Een net toegevoegde entiteit heeft geen historie** — `sensor_minute` begint pas op het punt waarop de entiteit voor het eerst in het aggregaat verscheen. Draai de backfill opnieuw na `CALL refresh_continuous_aggregate(...)`.

**Tellers lopen een paar minuten uit de pas** — zie [De minutentabel gelijk houden met de werkelijkheid](#de-minutentabel-gelijk-houden-met-de-werkelijkheid).

**Er komt helemaal niets terug** — de reader logt elke query op waarschuwingsniveau met het voorvoegsel `[WEBSOCKET]`. Kijk in het Home Assistant-log.

---

## Issues en bijdragen

Open een issue of pull request op [GitHub](https://github.com/remmob/timescale_database_reader).

---
©2026 Bommer Software | Auteur: Mischa Bommer

> **Let op:** deze integratie is werk in uitvoering. Functies en werking kunnen veranderen of nog onvolledig zijn.
