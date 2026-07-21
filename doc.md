# Conversione di `django-cookiecutter` in un template Copier

## Obiettivo

Convertire il template presente in `../django-cookiecutter` in questo repository,
preservando l'output generato e aggiungendo il supporto nativo di Copier agli
aggiornamenti dei progetti.

Il risultato dovrà permettere di:

- creare un progetto nuovo con `copier copy`;
- conservare le risposte in `.copier-answers.yml`;
- aggiornare in seguito un progetto con `copier update`;
- produrre, a parità di risposte, lo stesso progetto del template Cookiecutter;
- non sovrascrivere mai il file locale e segreto `<repo_name>/.env` durante un
  aggiornamento.

Questa procedura è basata sul contenuto reale di `../django-cookiecutter`
esaminato il 21 luglio 2026.

## 1. Preparare la struttura del repository

Usare una directory `template/` invece della directory esterna dinamica
`{{cookiecutter.repo_name}}`. Con Copier è il comando a scegliere la directory
di destinazione; mantenere anche quel livello produrrebbe una directory
duplicata.

La struttura prevista è:

```text
django-copier/
├── copier.yml
├── README.md
├── tasks/
│   ├── preflight.py
│   └── post_copy.py
├── tests/
└── template/
    ├── [[ _copier_conf.answers_file ]].jinja
    ├── .gitignore
    ├── Makefile.jinja
    ├── README.md.jinja
    ├── docker-compose.yml.jinja
    └── [[ repo_name ]]/
        ├── manage.py
        ├── core/
        ├── pages/
        └── ...
```

Passaggi:

1. Copiare dentro `template/` **il contenuto** di
   `../django-cookiecutter/{{cookiecutter.repo_name}}`, non la directory esterna.
2. Rinominare `gitignore` in `.gitignore`: con Copier non serve il workaround
   usato dal hook Cookiecutter.
3. Rinominare la directory Django interna
   `{{cookiecutter.repo_name}}` in `[[ repo_name ]]`.
4. Non copiare `cookiecutter.json`, `hooks/`, `.claude/` e i documenti interni
   specifici del vecchio template.
5. Eliminare dal sorgente ogni `__pycache__/` e `*.pyc`. Nel template attuale
   risultano presenti file compilati sotto `pages/__pycache__`; non devono far
   parte del nuovo template.

Impostare `_subdirectory: template` in `copier.yml`. In questo modo i metadati
del template, gli script e i test non vengono inclusi nei progetti generati.

## 2. Definire le domande in `copier.yml`

Trasferire le domande di `cookiecutter.json`, assegnando tipi espliciti. È
preferibile trasformare le tre opzioni `y`/`n` in booleani reali e le lingue in
una lista YAML:

| Risposta | Tipo Copier | Default | Note |
| --- | --- | --- | --- |
| `project_name` | `str` | `My New Project` | nome leggibile |
| `project_description` | `str` | `My New Project description` | descrizione README |
| `repo_name` | `str` | slug derivato da `project_name` | deve restare modificabile |
| `use_cabinet` | `bool` | `false` | sostituisce `n`/`y` |
| `use_sorl_thumbnail` | `bool` | `true` | sostituisce `y`/`n` |
| `use_translations` | `bool` | `false` | sostituisce `n`/`y` |
| `languages` | `yaml` | `[it, en]` | chiedere solo con traduzioni attive |
| `default_language` | `str` | `it` | chiedere solo con traduzioni attive |
| `timezone` | `str` | `Europe/Rome` | timezone Django e Docker |
| `author` | `str` | `otto` | namespace GitHub |
| `email` | `str` | `logs@otto.srl` | email applicativa |
| `db_user` | `str` | valore di `repo_name` | deve restare modificabile |

Schema iniziale consigliato:

```yaml
_min_copier_version: "9.3.0"
_subdirectory: template
_templates_suffix: .jinja

_envops:
  block_start_string: "[%%"
  block_end_string: "%%]"
  variable_start_string: "[["
  variable_end_string: "]]"
  comment_start_string: "[#"
  comment_end_string: "#]"
  keep_trailing_newline: true
  undefined: jinja2.StrictUndefined

project_name:
  type: str
  default: My New Project
  help: Nome leggibile del progetto

project_description:
  type: str
  default: My New Project description

repo_name:
  type: str
  default: "[[ project_name | lower | replace(' ', '-') ]]"
  help: Slug del repository e della directory applicativa

use_cabinet:
  type: bool
  default: false

use_sorl_thumbnail:
  type: bool
  default: true

use_translations:
  type: bool
  default: false

languages:
  type: yaml
  default: [it, en]
  when: "[[ use_translations ]]"

default_language:
  type: str
  default: it
  when: "[[ use_translations ]]"

timezone:
  type: str
  default: Europe/Rome

author:
  type: str
  default: otto

email:
  type: str
  default: logs@otto.srl

db_user:
  type: str
  default: "[[ repo_name ]]"
```

Aggiungere i validatori Copier equivalenti al vecchio `pre_gen_project.py`:

- `languages` deve contenere almeno due codici univoci;
- ogni codice deve rispettare
  `^[a-z]{2,3}(?:-[a-z0-9]+)*$`;
- `default_language` deve appartenere a `languages`;
- aggiungere anche una validazione dello slug `repo_name`, perché viene usato in
  nomi Docker, path e variabili GitHub.

Se si decide di lasciare `languages` come stringa CSV per la massima
compatibilità, mantenerne il default `it,en` e adattare soltanto il validatore.
La scelta non deve rimanere a metà: template, task e test devono usare tutti lo
stesso tipo.

## 3. Separare Jinja di Copier dai template Django

Il progetto contiene oltre cinquanta file con tag Django `{{ ... }}` e
`{% ... %}`. Usare gli stessi delimitatori per Copier renderebbe fragile ogni
template HTML. Per questo il precedente esempio usa `[[ ... ]]` e `[%% ... %%]`
per Copier e mantiene intatti i delimitatori Django.

Inoltre, lasciare `_templates_suffix: .jinja` evita di interpretare asset
binari, file `.mo`, font, immagini, CSS/JS vendorizzati e source map. È più
sicuro dell'equivalente Cookiecutter `_copy_without_render`.

Procedere così:

1. Individuare i file che contengono `cookiecutter.`:

   ```bash
   rg -l 'cookiecutter\.' ../django-cookiecutter/'{{cookiecutter.repo_name}}'
   ```

2. Aggiungere il suffisso `.jinja` soltanto a quei file. Nel repository attuale
   sono 33 e comprendono, tra gli altri, `Makefile`, i tre file Compose, i due
   Dockerfile, `entrypoint.production.sh`, `requirements/common.txt`, settings,
   admin, URL, test e alcuni template HTML.
3. Nei file `.jinja` sostituire:

   - `{{ cookiecutter.nome }}` con `[[ nome ]]`;
   - `{% if cookiecutter.opzione == 'y' %}` con `[%% if opzione %%]`;
   - il ramo `!= 'y'` con `not opzione`;
   - `cookiecutter.languages.split(',')` con `languages` se si adotta la lista;
   - tutti gli altri blocchi Cookiecutter con i delimitatori `[%% ... %%]`.

4. Rimuovere **tutte** le coppie `{% raw %}` / `{% endraw %}` presenti nei
   template Django. Erano necessarie solo perché Cookiecutter analizzava tutti i
   file; con i delimitatori distinti diventerebbero testo spurio nell'HTML
   generato.
5. Controllare che non rimanga alcun riferimento al vecchio contesto:

   ```bash
   rg 'cookiecutter\.|\{% raw %\}|\{% endraw %\}' template
   ```

Un file HTML che contiene sia tag Django sia condizioni del generatore, per
esempio `pages/templates/pages/grid/grid_item.html`, diventa
`grid_item.html.jinja`: i tag Django restano `{% ... %}`, mentre solo la scelta
Copier usa `[%% ... %%]`.

## 4. Gestire i componenti opzionali con `_exclude`

Non copiare tutto per poi cancellarlo nel post-task. Esprimere le esclusioni in
`copier.yml`, così Copier conosce quali file appartengono a ciascuna
configurazione e può gestirli durante `copier update`.

Riprodurre queste regole del vecchio `post_gen_project.py`:

- se `use_cabinet` è falso, escludere `[[ repo_name ]]/cabinet/`;
- se `use_translations` è falso, escludere:
  `pages/translation.py`, `cabinet/translation.py`, `tagall/translation.py` e
  `core/translation.py` sotto `[[ repo_name ]]/`;
- il path `cabinet/translation.py` può essere elencato anche quando l'intera app
  è già esclusa.

Le voci di `_exclude` accettano pattern in stile `.gitignore` e possono essere
renderizzate. Usare per il ramo inattivo un pattern sentinella che non può
coincidere con file reali, invece di produrre una stringa vuota. Esempio
concettuale:

```yaml
_exclude:
  - "[[ repo_name ~ '/cabinet' if not use_cabinet else '.copier-never-match' ]]"
  - "[[ repo_name ~ '/pages/translation.py' if not use_translations else '.copier-never-match' ]]"
  - "[[ repo_name ~ '/cabinet/translation.py' if not use_translations else '.copier-never-match' ]]"
  - "[[ repo_name ~ '/tagall/translation.py' if not use_translations else '.copier-never-match' ]]"
  - "[[ repo_name ~ '/core/translation.py' if not use_translations else '.copier-never-match' ]]"
```

Verificare esplicitamente nei test il passaggio `false -> true` e `true ->
false` delle opzioni durante un aggiornamento: è il caso in cui file rimossi,
file locali modificati e nuovi file del template possono produrre conflitti.

## 5. Registrare le risposte per gli aggiornamenti

Creare in `template/` il file letteralmente chiamato
`[[ _copier_conf.answers_file ]].jinja` con questo contenuto:

```jinja
# Questo file è gestito da Copier; non modificarlo manualmente.
[[ _copier_answers | to_nice_yaml -]]
```

Il risultato generato sarà `.copier-answers.yml`. Deve essere versionato nei
progetti creati: contiene origine, revisione del template e risposte, ma non
deve contenere password o `SECRET_KEY`.

## 6. Convertire gli hook

### Controllo delle porte

Spostare la logica di `hooks/pre_gen_project.py` in `tasks/preflight.py`,
mantenendo il controllo delle porte locali 1025, 5434, 5678, 8000, 8001 e 8025.
Il task deve essere eseguito solo durante `copy`, prima della creazione di
`.env`.

Copier esegue i task dopo il rendering, ma se la destinazione è stata creata dal
comando e un task fallisce, la elimina per default. Il comportamento osservato
dall'utente resta quindi atomico. Documentare che il controllo può essere
saltato con `--skip-tasks` solo consapevolmente.

### Creazione di `.env`

Spostare la funzione `create_local_env()` in `tasks/post_copy.py` e conservarne
queste proprietà:

- usare `secrets.token_urlsafe()` per password e chiave Django;
- scrivere `[[ repo_name ]]/.env` con encoding UTF-8;
- quotare e validare i valori come fa oggi `dotenv_value()`;
- impostare i permessi `0600`;
- non stampare mai i segreti;
- fallire se `.env` esiste già, invece di sovrascriverlo accidentalmente;
- eseguire il task solo durante `copy`, mai durante `update`.

Configurazione indicativa, usando liste di argomenti invece di una shell:

```yaml
_tasks:
  - command:
      - "[[ _copier_python ]]"
      - "[[ _copier_conf.src_path ]]/tasks/preflight.py"
    when: "[[ _copier_operation == 'copy' ]]"
  - command:
      - "[[ _copier_python ]]"
      - "[[ _copier_conf.src_path ]]/tasks/post_copy.py"
      - "[[ repo_name ]]"
      - "[[ db_user ]]"
    when: "[[ _copier_operation == 'copy' ]]"
```

Gli script richiamati tramite `_copier_conf.src_path` restano nel repository del
template e non vengono copiati nel progetto. La presenza di task rende il
template “unsafe” per Copier: il comando di generazione dovrà usare `--trust`
dopo aver verificato la provenienza del template.

Non trasferire nel task la cancellazione di `cabinet` o dei file di traduzione:
questa parte è già modellata con `_exclude`. Non trasferire neppure il rename di
`gitignore`, che non è più necessario.

## 7. Aggiornare documentazione e comandi

Nel README del template sostituire l'installazione e l'uso di Cookiecutter con
Copier. Durante lo sviluppo locale:

```bash
copier copy --trust --vcs-ref HEAD . /tmp/progetto-copier
```

Da repository pubblicato e taggato:

```bash
copier copy --trust <URL_DJANGO_COPIER> my-project
cd my-project
git add .
git commit -m "Create project from django-copier"
```

Per aggiornare un progetto generato, partire sempre da un working tree pulito:

```bash
cd my-project
git status --short
copier update --trust
```

Non usare `copier recopy` come normale procedura di aggiornamento: rigenera dal
template ignorando la storia a tre vie che `copier update` usa per preservare le
modifiche del progetto.

Anche il README generato va controllato: le istruzioni per `.env` possono
spiegare il file, ma non devono più chiedere di crearlo manualmente, perché lo
fa `post_copy.py`.

## 8. Verificare la parità con Cookiecutter

Creare test automatici che generino in directory temporanee sia il vecchio sia
il nuovo template. Usare almeno questa matrice:

| Caso | cabinet | sorl-thumbnail | traduzioni | lingue |
| --- | ---: | ---: | ---: | --- |
| default | no | sì | no | — |
| minimale | no | no | no | — |
| cabinet | sì | sì | no | — |
| multilingua | no | sì | sì | `it,en` |
| completo | sì | sì | sì | `it,en,fr` |

Per ogni caso:

1. generare entrambi i progetti con gli stessi valori logici;
2. confrontare l'albero dei file;
3. confrontare byte per byte i file non variabili;
4. per `.env`, verificare nomi delle chiavi, quoting, permessi `0600` e assenza
   dei segreti nell'output, non i valori casuali;
5. ignorare nel confronto soltanto `.copier-answers.yml`, che è intenzionalmente
   nuovo;
6. verificare che non rimangano `cookiecutter.`, delimitatori Copier, wrapper
   `raw`, directory `__pycache__` o file `.pyc` nell'output;
7. eseguire almeno `docker compose config` e i test Django del progetto
   generato; se possibile eseguire anche `make bootstrap` in CI dedicata.

Aggiungere poi test specifici di aggiornamento:

1. generare da un tag iniziale, inizializzare Git e committare;
2. modificare un file tipicamente personalizzato dal progetto;
3. aggiornare a un tag successivo con `copier update --trust`;
4. verificare che la modifica locale sia preservata o che venga segnalato un
   conflitto esplicito;
5. verificare che `.env` e i relativi permessi non cambino;
6. verificare attivazione e disattivazione di cabinet, sorl e traduzioni.

## 9. Versionare e pubblicare il template

Copier usa i tag Git PEP 440 per determinare la versione stabile più recente.
Dopo che la matrice di test è verde:

1. committare la prima versione completa del template;
2. creare un tag stabile, per esempio `v1.0.0`;
3. non spostare mai un tag già usato per generare progetti;
4. per ogni modifica incompatibile alle risposte o ai path, aggiungere una voce
   `_migrations` in `copier.yml` e un test di aggiornamento tra i due tag;
5. usare tag successivi (`v1.0.1`, `v1.1.0`, ecc.) per distribuire gli
   aggiornamenti.

I progetti già creati con Cookiecutter non possiedono la base storica e il file
risposte richiesti da Copier. Non aggiungere manualmente un
`.copier-answers.yml` fingendo che siano stati generati da Copier. Per adottare
Copier su un progetto esistente serve una procedura separata: generare una base
Copier equivalente, confrontarla con il progetto, integrare le differenze e
stabilire un commit/tag di adozione verificato.

## Criteri di completamento

La conversione è conclusa quando:

- `cookiecutter.json` e gli hook Cookiecutter non sono più necessari;
- nessun file contiene riferimenti a `cookiecutter.*` o wrapper Jinja `raw` del
  vecchio template;
- tutte le configurazioni della matrice generano un progetto valido;
- l'output è equivalente a quello Cookiecutter, salvo
  `.copier-answers.yml` e le modifiche intenzionalmente documentate;
- `.env` viene creato una sola volta, con segreti robusti e permessi `0600`;
- un aggiornamento tra due tag preserva modifiche locali e `.env`;
- README e CI usano i comandi Copier;
- il primo tag stabile è pubblicato.

## Riferimenti

- [Configurazione di un template Copier](https://copier.readthedocs.io/en/stable/configuring/)
- [Generazione di un progetto](https://copier.readthedocs.io/en/stable/generating/)
- [Aggiornamento di un progetto](https://copier.readthedocs.io/en/stable/updating/)
