# Fronius Modbus Dump

Dieses Hilfstool liest Modbus-TCP-Registerbereiche vom Fronius direkt aus und schreibt sie in eine CSV-Datei.
Danach kann ein zweiter Dump mit geänderten Fronius-Einstellungen erstellt und per CSV-Diff verglichen werden.

Das Tool benötigt keine zusätzlichen Python-Pakete.

## Datei

`tools/fronius_modbus_dump.py`

## Was es macht

- liest `holding`- und/oder `input`-Register via Modbus TCP
- schreibt pro Adresse eine CSV-Zeile
- speichert sowohl `raw_address` als auch `register_number`
- kann zwei Dumps vergleichen und nur die Änderungen in eine neue CSV schreiben
- kann SunSpec-Modelle per `Model-ID` im Registerbereich suchen
- kann den gefundenen Model-Block direkt als CSV dumpen
- kann mit `baseline -> before -> after` Live-Rauschen herausfiltern

## Wichtiger Hinweis zu Fronius-Adressen

Fronius/SunSpec-Dokumentation zeigt oft Registernummern wie `40353`.
Im Modbus-Protokoll wird dafür meist die rohe Adresse `40352` gelesen.

Das Tool schreibt deshalb beide Spalten:

- `raw_address`
- `register_number = raw_address + 1`

## Beispiel: Vorher/Nachher-Vergleich

## Erst den echten Model-124-Block finden

Da Fronius/SunSpec-Register dynamisch angeordnet sein können, ist `40343` nicht auf jedem Gerät wirklich der Storage-Control-Block.

Suche deshalb zuerst nach `Model 124`:

```powershell
.venv\Scripts\python.exe tools\fronius_modbus_dump.py locate-model `
  --host 192.168.1.50 `
  --unit 1 `
  --kind holding `
  --start 40000 `
  --end 41050 `
  --model-id 124 `
  --model-len 24
```

Wenn ein Treffer kommt, kannst du direkt genau diesen Block dumpen:

```powershell
.venv\Scripts\python.exe tools\fronius_modbus_dump.py dump-model `
  --host 192.168.1.50 `
  --unit 1 `
  --kind holding `
  --start 40000 `
  --end 41050 `
  --model-id 124 `
  --model-len 24 `
  --output dumps\model124_before.csv
```

Falls mehrere Treffer erscheinen, nutze `--hit-index 1`, `--hit-index 2`, usw.

### 1. Ersten Dump ziehen

```powershell
python tools/fronius_modbus_dump.py dump `
  --host 192.168.1.50 `
  --port 502 `
  --unit 1 `
  --range holding:40000-41050 `
  --range input:40000-41050 `
  --include-errors `
  --output dumps\fronius_before.csv
```

### 2. Eine Fronius-Einstellung manuell ändern

Zum Beispiel:

- Batterieladung aus anderen Quellen ein/aus
- Minimaler Ladezustand ändern
- Begrenzung des Ladezustands umstellen

### 3. Zweiten Dump ziehen

```powershell
python tools/fronius_modbus_dump.py dump `
  --host 192.168.1.50 `
  --port 502 `
  --unit 1 `
  --range holding:40000-41050 `
  --range input:40000-41050 `
  --include-errors `
  --output dumps\fronius_after.csv
```

### 4. Dumps vergleichen

```powershell
python tools/fronius_modbus_dump.py diff `
  --before dumps\fronius_before.csv `
  --after dumps\fronius_after.csv `
  --output dumps\fronius_changed.csv
```

Danach enthält `dumps\fronius_changed.csv` nur die geänderten Zeilen.

## Rauschfilter mit drei Dumps

Wenn Live-Werte ständig mitschwimmen, ist ein einfacher `before/after`-Diff oft unbrauchbar.
Dann nutze drei Messungen:

1. `baseline` -> erster Dump ohne Änderung
2. `before` -> zweiter Dump ebenfalls ohne Änderung
3. `after` -> Dump nach genau einer echten Fronius-Änderung

Das Tool behält dann nur Register, die:

- in `baseline` und `before` gleich waren
- und erst in `after` anders wurden

### Beispiel

```powershell
.venv\Scripts\python.exe tools\fronius_modbus_dump.py dump-model `
  --host 192.168.1.50 `
  --unit 1 `
  --kind holding `
  --start 40000 `
  --end 41050 `
  --model-id 124 `
  --model-len 24 `
  --output dumps\baseline.csv
```

Ohne irgendetwas zu ändern:

```powershell
.venv\Scripts\python.exe tools\fronius_modbus_dump.py dump-model `
  --host 192.168.1.50 `
  --unit 1 `
  --kind holding `
  --start 40000 `
  --end 41050 `
  --model-id 124 `
  --model-len 24 `
  --output dumps\before.csv
```

Dann eine Fronius-Einstellung ändern und speichern:

```powershell
.venv\Scripts\python.exe tools\fronius_modbus_dump.py dump-model `
  --host 192.168.1.50 `
  --unit 1 `
  --kind holding `
  --start 40000 `
  --end 41050 `
  --model-id 124 `
  --model-len 24 `
  --output dumps\after.csv
```

Jetzt den gefilterten Diff bilden:

```powershell
.venv\Scripts\python.exe tools\fronius_modbus_dump.py stable-diff `
  --baseline dumps\baseline.csv `
  --before dumps\before.csv `
  --after dumps\after.csv `
  --output dumps\stable_changed.csv
```

Wenn `stable_changed.csv` leer bleibt, dann wurde die Einstellung sehr wahrscheinlich nicht in diesem Modellblock gespeichert.

## Sinnvolle Startbereiche

Für erste Tests sind diese Bereiche praktikabel:

- `holding:40000-41050`
- `input:40000-41050`

Wenn nötig, kann man später enger oder breiter scannen.

Für Batterie-Steuerung ist oft sinnvoll:

- zuerst `locate-model` mit `--model-id 124 --model-len 24`
- danach nur den echten Treffer mit `dump-model`

## CSV-Spalten

- `kind` -> `holding` oder `input`
- `raw_address` -> rohe Modbus-Adresse
- `register_number` -> sichtbare Registernummer aus vielen Dokus
- `value` -> 16-bit Registerwert
- `status` -> `ok` oder `error`
- `detail` -> Fehlertext bei nicht lesbaren Adressen

## Interpretation

Ein einzelnes Setting kann:

- genau ein Register ändern
- mehrere Register ändern
- nur Holding-Register ändern
- oder intern an ganz anderer Stelle landen als vermutet

Genau dafür ist der Vorher/Nachher-Diff gedacht.
