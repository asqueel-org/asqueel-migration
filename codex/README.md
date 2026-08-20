# Raccomandazioni Codex

Ultima revisione: 2026-08-20

Questa cartella raccoglie valutazioni e raccomandazioni tecniche sul repository.
Le indicazioni sono ordinate per priorità e possono essere trasformate in issue o
attività di roadmap.

## Issue GitHub aperte

- [#1 — Semantica affidabile di diff/check e rimozioni](https://github.com/genropy/genro-sqlmigration/issues/1)
- [#2 — Allineamento di roadmap e documentazione](https://github.com/genropy/genro-sqlmigration/issues/2)
- [#3 — CI e matrice dei test riproducibili](https://github.com/genropy/genro-sqlmigration/issues/3)
- [#4 — Integrità di packaging e release](https://github.com/genropy/genro-sqlmigration/issues/4)
- [#5 — Contratto pubblico di typing e mypy](https://github.com/genropy/genro-sqlmigration/issues/5)
- [#6 — Sicurezza dell'editor e gestione credenziali](https://github.com/genropy/genro-sqlmigration/issues/6)
- [#7 — Migrazioni transazionali e risultati strutturati](https://github.com/genropy/genro-sqlmigration/issues/7)

## Valutazione sintetica

Il progetto ha fondamenta solide e un'architettura chiara, ma è ancora in fase
Alpha. La priorità non è aggiungere nuove funzionalità: è rendere affidabili la
pipeline, le migrazioni distruttive e i controlli di qualità.

Valutazione indicativa: **7/10**.

## P0 — Pipeline CI

- [x] Correggere le dipendenze della suite di test. Il workflow installa
  `.[dev]`, ma diversi moduli di test importano direttamente `psycopg`,
  `pymysql` e `pymssql`.
- [x] Separare chiaramente i test unitari dai test d'integrazione per PostgreSQL,
  MySQL e MSSQL, usando marker dichiarati e job dedicati.
- [x] Eseguire Ruff e mypy nella CI, oltre a pytest.
- [x] Aggiungere Python 3.13 alla matrice oppure rimuovere temporaneamente il
  relativo classifier dal pacchetto.
- [x] Definire una soglia minima di coverage, distinta tra core e adapter che
  richiedono database esterni.

## P1 — Correttezza delle migrazioni

- [x] Documentare che `check` verifica la compatibilità additiva: il database
  può ospitare l'applicazione senza ulteriori migrazioni, ma non deve essere
  strutturalmente identico al modello.
- [x] Correggere gli eventi `change` esterni ad `attributes`, che oggi possono
  causare un `ValueError` (caso osservato: `root.entity_name` differente).
- [x] Conservare intenzionalmente gli oggetti presenti soltanto nel database:
  nessun DROP implicito e nessun rename inferito da remove più add.
- [ ] Aggiungere un'opzione di esecuzione atomica per i database che supportano
  DDL transazionale. L'autocommit attuale può lasciare migrazioni parzialmente
  applicate.
- [ ] Produrre un report strutturato delle operazioni ignorate o non supportate,
  non soltanto una stringa SQL eventualmente vuota.

## P1 — Sicurezza operativa

- [ ] Documentare che l'endpoint REST `apply` esegue DDL e deve essere protetto
  da autenticazione, autorizzazione e restrizioni di rete.
- [ ] Evitare il passaggio di password in parametri che possano finire in URL o
  log HTTP; preferire body o secret injection.
- [ ] Validare o quotare centralmente tutti gli identificatori SQL provenienti
  dal modello, inclusi nomi di schema, tabella, colonna e constraint.
- [ ] Conservare dry-run e operazioni distruttive come scelte esplicite e
  separate.

## P2 — Qualità e typing

- [ ] Risolvere gli errori mypy prima di dichiarare pienamente supportato
  `Typing :: Typed`.
- [ ] Aggiungere stub o configurazioni mirate per `dictdiffer`, `jsonschema`,
  PyMySQL, pymssql e genro-asgi.
- [ ] Aumentare gradualmente `disallow_untyped_defs`, iniziando dai moduli del
  contratto, diff ed executor.
- [ ] Ridurre la dimensione di `command_builder.py`, separando handler di add,
  change e remove oppure introducendo eventi tipizzati.
- [ ] Valutare nel medio periodo la sostituzione di `dictdiffer` con un walker
  strutturale specifico del contratto.

## P2 — Packaging e release

- [ ] Correggere l'extra `all`: oggi non include MySQL, MSSQL, validation e app.
- [ ] Avere una sola sorgente della versione, evitando la duplicazione tra
  `pyproject.toml` e `__init__.py`.
- [ ] Aggiungere un controllo automatico di coerenza tra tag Git e versione del
  pacchetto prima della pubblicazione.
- [ ] Inserire un changelog e una checklist di release.
- [ ] Verificare installazione e import del wheel in un ambiente pulito prima di
  pubblicarlo.

## P2 — Documentazione e manutenzione

- [ ] Aggiornare la roadmap: diversi milestone descritti come futuri risultano
  già implementati.
- [ ] Documentare una matrice completa delle capacità per dialetto, distinguendo
  lettura, creazione, modifica e rimozione.
- [ ] Aggiungere una pagina dedicata ai limiti noti e alle garanzie di sicurezza.
- [ ] Chiarire quali test sono unitari, quali richiedono un database locale e
  quali richiedono Docker.
- [ ] Rimuovere o ignorare il file locale vuoto `PATTERNS_DISABLED`.

## Controlli eseguiti il 2026-08-20

- Ruff: superato.
- Build di sdist e wheel: superata senza isolamento; schemi JSON e XSD inclusi.
- Test eseguibili nell'ambiente locale senza MSSQL: 191 superati, 95 saltati.
- Coverage osservata: 61%, influenzata dai test d'integrazione saltati.
- mypy: 14 errori.
- Documentazione Sphinx: generata; il controllo `-W` locale si è fermato perché
  l'inventario intersphinx esterno non era raggiungibile.

## Ordine di lavoro consigliato

1. Rendere verde e riproducibile la CI.
2. Correggere il significato di `check` e completare o dichiarare le rimozioni.
3. Introdurre esecuzione atomica e report strutturati.
4. Chiudere typing e coverage del core.
5. Allineare packaging, roadmap e documentazione prima della Beta.
