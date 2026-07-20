# Cloudflare Tunnel

Standalone-Anleitung für `sprichblitz.example.com` – wiederverwendbar
für andere Dienste am selben Tunnel auf demselben
Apple-Silicon-Mac.

## Warum eine separate Domain sinnvoll sein kann

Die Hostnamen in dieser Anleitung sind anonymisierte Beispiele. Wer eine
bestehende produktive Domain mit Mail-, MX-, SPF- oder DKIM-Einträgen bei einem
anderen DNS-Anbieter betreibt, muss diese Zone nicht eigens zu Cloudflare
migrieren. Eine separate Cloudflare-native Zone nur für Tunnel-Endpoints hält
das Risiko und den Cutover klein:

- Die bestehende Produktiv-/Mail-Domain bleibt beim bisherigen Anbieter.
- Die separate Tunnel-Zone wird direkt von Cloudflare verwaltet;
  `cloudflared tunnel route dns` setzt die benötigten CNAME-Einträge.

## Was wir machen (und was bewusst NICHT)

**Setup:**
- Cloudflare-Tunnel als Reverse-Proxy vom Cloudflare-Edge zu
  `localhost:8000` auf dem Backend-Mac.
- DNS für `example.com` direkt bei Cloudflare; CNAME `sprichblitz`
  zeigt auf `*.cfargotunnel.com`.
- Auth: **Bearer-Token pro Nutzer im Backend**. Die nativen Clients benötigen
  keine zusätzlichen Cloudflare-Zugangsdaten.

**Nicht im Setup:**
- Eine bestehende Produktiv-/Mail-Domain zu Cloudflare migrieren.
- Cloudflare Access oder ein interaktiver Cloudflare-Login in den nativen Clients.
- Eine konkrete Cloudflare-WAF-/Rate-Limit-Regel; sinnvolle Startwerte stehen
  weiter unten, hängen aber vom Tarif und der Nutzerzahl ab.

## Voraussetzungen

- Cloudflare-Account (kostenloses Free-Tier reicht).
- `example.com` (oder eine andere Cloudflare-Zone) ist im Cloudflare-
  Dashboard aktiv.
- `cloudflared`-Binary auf dem Backend-Mac.

## Schritt 1 – cloudflared installieren

```bash
brew install cloudflared
cloudflared --version
# cloudflared version 2025.x.x …
```

## Schritt 2 – bei Cloudflare anmelden

```bash
cloudflared tunnel login
```

Öffnet den Browser. Cloudflare zeigt die Liste der eigenen Zonen –
`example.com` auswählen. Dadurch landet ein Cert-Bundle in
`~/.cloudflared/cert.pem`, mit dem die folgenden Tunnel-Befehle
authentifiziert werden.

## Schritt 3 – Tunnel anlegen

```bash
cloudflared tunnel create sprichblitz
# → Created tunnel sprichblitz with id 12345678-aaaa-bbbb-cccc-…
# → Credentials file: /Users/<USERNAME>/.cloudflared/12345678-….json
```

Tunnel-ID merken oder gleich aus dem JSON-Dateinamen ableiten:

```bash
ls ~/.cloudflared/*.json
```

## Schritt 4 – Tunnel-Config

```bash
cat > ~/.cloudflared/config.yml <<'EOF'
tunnel: 12345678-aaaa-bbbb-cccc-…
credentials-file: /Users/<USERNAME>/.cloudflared/12345678-aaaa-bbbb-cccc-….json

ingress:
  - hostname: sprichblitz.example.com
    # 127.0.0.1 (nicht localhost): deterministischer Loopback-Peer fürs Backend.
    # Der Trusted-Ingress-Check unterscheidet Tunnel von LAN am rohen
    # TCP-Peer → keine v6/v4-Auflösungs-Ambiguität.
    service: http://127.0.0.1:8000

  # Catch-all – ohne diesen Eintrag startet cloudflared nicht.
  - service: http_status:404
EOF
```

Mehrere Hostnames sind möglich – z. B. später für ein zweites Projekt:

```yaml
ingress:
  - hostname: sprichblitz.example.com
    service: http://127.0.0.1:8000
  - hostname: another-service.example.com
    service: http://localhost:8001
  - service: http_status:404
```

## Schritt 5 – DNS-CNAME bei Cloudflare

Da `example.com` eine Cloudflare-Zone ist, setzt `cloudflared` den
CNAME automatisch:

```bash
cloudflared tunnel route dns sprichblitz sprichblitz.example.com
# → Added CNAME sprichblitz.example.com which will route to this tunnel.
```

DNS-Propagation ist quasi sofort (Cloudflare-eigene Zone).

Test:

```bash
dig sprichblitz.example.com CNAME +short
# → 12345678-aaaa-bbbb-cccc-….cfargotunnel.com.
dig sprichblitz.example.com +short
# → 104.21.x.x  (Cloudflare-Edge)
```

## Schritt 6 – Tunnel im Vordergrund testen

```bash
cloudflared tunnel run sprichblitz
# Logs zeigen "Registered tunnel connection" auf 2-4 Cloudflare-PoPs.
```

Im zweiten Terminal:

```bash
curl https://sprichblitz.example.com/health
# → {"status":"ok",…}

TOKEN=$(grep '^BACKEND_AUTH_TOKEN=' ~/Projects/sprichblitz/backend/.env | cut -d= -f2)
curl -H "Authorization: Bearer $TOKEN" https://sprichblitz.example.com/config | jq '.modes | length'
# → Anzahl der konfigurierten Modi (mit der mitgelieferten Config: 6).
#   Hauptsache > 0 und kein 401 – die genaue Zahl haengt an deiner Config.
```

`Ctrl-C` beendet den Vordergrund-Tunnel.

## Schritt 7 – als Service installieren

So läuft der Tunnel beim Login automatisch und nach Reboots wieder hoch:

```bash
sudo cloudflared service install
```

Macht im Hintergrund:
- Legt `/Library/LaunchDaemons/com.cloudflare.cloudflared.plist` an.
- Liest die Config aus `~/.cloudflared/config.yml`.
- Startet als Root mit den Tunnel-Credentials.

Status prüfen:

```bash
sudo launchctl list | grep cloudflared
# com.cloudflare.cloudflared <PID>  0
```

Logs:

```bash
log show --predicate 'process == "cloudflared"' --last 30m
```

Stoppen / deinstallieren:

```bash
sudo cloudflared service uninstall
```

## Update von cloudflared

```bash
brew upgrade cloudflared
sudo launchctl kickstart -k system/com.cloudflare.cloudflared
```

## Rate-Limiting gehört an den Edge (empfohlen)

Das Backend hat einen **per-User-Token-Bucket** (nach erfolgreicher Auth). Was es
**nicht** hat, ist eine Drossel gegen unauthentifizierte Fluten / fehlgeschlagene
Auth-Versuche – und die kann es auf dem Tunnel-Pfad auch gar nicht sinnvoll
haben: cloudflared reicht die Requests über **Loopback** ans Origin, der TCP-Peer
ist also immer `127.0.0.1`. Eine IP-basierte Drossel am Origin würde alle
Tunnel-Clients in denselben Topf werfen (die echte Client-IP wird bewusst nicht
rekonstruiert/geloggt, siehe `TrustedIngressMiddleware`). Die Bearer-Token sind
mit ~384 Bit brute-force-sicher; es geht also um **Flood-/DoS-Schutz**, nicht um
Passwort-Raten.

**Deshalb: eine Rate-Limiting-Regel am Cloudflare-Edge** (WAF → Rate limiting
rules), z. B.:

- Pfad-Scope auf die teuren/sensiblen Endpunkte: `/full`, `/transcribe`,
  `/process`, `/console/session` (und optional `/config`).
- Ein pragmatischer Startwert: **~60 Requests / 1 min pro Client-IP**, Aktion
  „Block". Keine interaktive „Managed Challenge" auf den API-Pfaden: native
  API-Clients können sie nicht bedienen. Cloudflare sieht die echte Client-IP
  am Edge, das Origin nicht.
- Optional zusätzlich eine strengere Regel nur auf 401/403-Antworten (fängt
  Auth-Brute-Force ab, ohne legitime Nutzung zu treffen).

**Ohne Cloudflare** (Self-Hosting hinter einem eigenen Reverse-Proxy): dieselbe
Drossel in nginx (`limit_req`) / Caddy (`rate_limit`) davorsetzen – der
Origin-Token-Bucket deckt nur den authentifizierten Pfad ab. Siehe auch
`docs/operations.md` → „Geparkte Härtung".

## Troubleshooting

### A) `curl https://sprichblitz.example.com/health` → `Could not resolve host`

DNS-Cache. Warten oder `dscacheutil -flushcache; sudo killall -HUP mDNSResponder`.

### B) `dig` zeigt CNAME OK, aber `curl` → 530 / 1033

Tunnel läuft nicht. `sudo launchctl list | grep cloudflared` prüfen.
Wenn PID = `-`, läuft kein Daemon → `sudo cloudflared service install`
oder vorne `cloudflared tunnel run sprichblitz` zum Debuggen.

### C) `curl` → `502 Bad Gateway`

Tunnel läuft, aber Backend antwortet nicht auf `localhost:8000`.

```bash
curl http://localhost:8000/health
# Wenn das auch fehlschlägt: Backend down. make run-backend oder
# launchctl list | grep sprichblitz.
```

### D) `curl` → `403`/`401` von Backend (nicht von Cloudflare)

Token im Header fehlt oder stimmt nicht. Cloudflare-Edge reicht
Header durch; das Bearer-Token muss exakt `BACKEND_AUTH_TOKEN`
aus `backend/.env` matchen.

### E) Tunnel verliert Verbindung, kommt nicht zurück

`cloudflared` reagiert manchmal sensibel auf Netzwerk-Wechsel
(WLAN ↔ LAN). Service neu kicken:

```bash
sudo launchctl kickstart -k system/com.cloudflare.cloudflared
```

### F) Mehrere Hostnames ergänzen

`~/.cloudflared/config.yml` erweitern (siehe Schritt 4), dann pro
Hostname einen CNAME via `cloudflared tunnel route dns`, dann
`sudo launchctl kickstart -k system/com.cloudflare.cloudflared`.

### G) Tunnel löschen / neu anfangen

```bash
cloudflared tunnel cleanup sprichblitz   # entfernt alte Connections
cloudflared tunnel delete sprichblitz    # löscht Tunnel bei Cloudflare
rm ~/.cloudflared/<TUNNEL-ID>.json
```

Danach Schritt 3 ff. wiederholen.

## Cloudflare Access

Die mitgelieferten Android- und Windows-Clients verwenden bewusst **kein
Cloudflare Access** und senden keine Service-Token-Header. Für den normalen
Betrieb bleibt `auth.mode: token_only`: Cloudflare Tunnel stellt den sicheren
Transport bereit, der Backend-Bearer übernimmt Identifikation und Autorisierung.

Das Backend enthält weiterhin einen optionalen `token_plus_cf_access`-Modus für
eigene Integrationen. Er ist nicht mit den mitgelieferten nativen Clients zu
aktivieren, solange eine solche Integration nicht separat implementiert wird.

### Upgrade von älteren Service-Token-Clients

Frühere Clientstände konnten `CF-Access-Client-Id` und
`CF-Access-Client-Secret` mitsenden. Vor dem Update auf die bearer-only Clients
muss ein bestehender Host deshalb zuerst auf `auth.mode: token_only` umgestellt
und neu gestartet werden. Andernfalls lehnt das Backend die aktualisierten
Clients mit 403 ab. Beim ersten Start entfernen die neuen Clients die nicht mehr
verwendeten Cloudflare-Credentials aus dem System-Keystore; der Backend-Bearer
bleibt erhalten. Das Zurückwechseln auf den früheren Access-Modus erfordert
danach eine erneute manuelle Einrichtung mit einem älteren Client.

### Console-Nonce einschalten

Android und Windows setzen vor dem Öffnen der Web-Konsole einen kurzlebigen
`sb_boot`-Cookie und binden den Single-Use-Code über `X-Sb-Boot-Nonce` daran.
Frische Installationen haben deshalb in `config.example.yml` bereits
`auth.require_console_nonce: true`. Bei einem bestehenden Host diesen Wert erst
in der gitignorierten `config.yml`/`config.local.yml` aktivieren, nachdem beide
Clients aktualisiert und getestet sind. Der Backend-Bearer gelangt weiterhin nie
in die WebView.

## Wiederverwendung für andere Dienste

Der gleiche Tunnel kann mehrere Backends bedienen:

1. Neuen Service auf einem freien Port starten (`localhost:8001`).
2. `~/.cloudflared/config.yml` um einen `ingress`-Block erweitern.
3. CNAME setzen: `cloudflared tunnel route dns sprichblitz another-service.example.com`.
4. `sudo launchctl kickstart -k system/com.cloudflare.cloudflared`.

Kein neuer Tunnel pro Projekt nötig – ein Tunnel reicht für alle
Subdomains.
