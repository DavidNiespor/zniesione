# Wdrożenie: serwer, Cloudflare, Portainer

Portal działa w kontenerze Dockera. Z internetu ruch przychodzi przez **Cloudflare Tunnel** (kontener `cloudflared`).
Serwer nie potrzebuje wtedy otwartych portów 80 ani 443, a certyfikat HTTPS zapewnia Cloudflare.

```
przeglądarka ──HTTPS──▶ Cloudflare ──tunel──▶ cloudflared ──http──▶ zniesione:8000 (gunicorn + SQLite w wolumenie /data)
```

## Co wybrać: Docker Compose czy Portainer?

| | Docker Compose (konsola) | Portainer (przeglądarka) |
|---|---|---|
| Kiedy | nie masz Portainera albo wolisz kilka poleceń w SSH | Portainer już działa albo wolisz klikać |
| Obraz | budowany na serwerze z repozytorium | pobierany z GitHub Container Registry (budowany przez CI) |
| Aktualizacja | `git pull` i jedno polecenie | „Update the stack” z ponownym pobraniem obrazu |

Oba sposoby uruchamiają ten sam obraz i ten sam tunel. Jeśli nie masz jeszcze Portainera, zalecam Docker Compose:
mniej elementów, a Portainera da się doinstalować później i zobaczy te same kontenery.

## 1. Cloudflare (wspólne dla obu sposobów)

1. Dodaj domenę do Cloudflare (Add a site, plan Free wystarczy) i u rejestratora domeny zmień serwery nazw na te podane przez Cloudflare.
   Poczekaj, aż status domeny będzie „Active”.
2. Otwórz **Zero Trust → Networks → Tunnels → Create a tunnel**, wybierz **Cloudflared**, nazwij tunel (np. `zniesione`).
3. Na ekranie instalacji wybierz **Docker** i skopiuj długi token z polecenia (`... run --token eyJ...`): ciąg po `--token`
   to `TUNNEL_TOKEN`. Samego polecenia nie uruchamiaj, kontener `cloudflared` jest w pliku compose.
4. W zakładce **Public Hostname** dodaj adres portalu:
   - Subdomain: puste (albo np. `portal`), Domain: Twoja domena,
   - Service: Type **HTTP**, URL **`zniesione:8000`**.
5. W **SSL/TLS → Edge Certificates** włącz **Always Use HTTPS**. Ciasteczko logowania ma flagę `Secure`,
   więc portal działa tylko przez `https://`.
6. (Zalecane) **Security → WAF → Rate limiting rules**: reguła dla ścieżki `/api/auth/login`, np. 20 żądań na minutę z jednego IP.
   Aplikacja ma też własny limit (5 nieudanych prób na e-mail i 20 na adres IP w ciągu 10 min) i dzięki `REAL_IP_HEADER`
   widzi prawdziwy adres klienta, a nie adres Cloudflare.

**Sterowniki w kurnikach (WireGuard).** Tunel Cloudflare i proxy Cloudflare nie przenoszą WireGuard (UDP). Rekord dla
`wg.twojadomena.pl` (ustawienie „Adres serwera” w panelu administratora) dodaj jako typ **A** na publiczny adres IP serwera,
z wyłączonym proxy (**DNS only**, szara chmurka), i otwórz port **51820/UDP**. Sam serwer WireGuard nie jest częścią tego
repozytorium i trzeba go skonfigurować osobno, tak żeby kontener portalu widział podsieć sterowników (domyślnie `10.8.0.0/24`).

## 2a. Serwer z Docker Compose

Przykład dla Ubuntu 22.04 lub 24.04, polecenia jako użytkownik z `sudo`.

```sh
curl -fsSL https://get.docker.com | sudo sh                  # Docker z oficjalnego skryptu
sudo git clone https://github.com/DavidNiespor/zniesione.git /opt/zniesione
cd /opt/zniesione
sudo cp .env.example .env
python3 -c "import secrets;print(secrets.token_hex(32))"      # wynik wklej jako SECRET_KEY
sudo nano .env                                               # SECRET_KEY i TUNNEL_TOKEN
sudo docker compose --profile cloudflare up -d --build
sudo docker compose exec zniesione flask --app zniesione create-admin   # pierwsze konto administratora
```

Sprawdzenie: `sudo docker compose ps` (oba kontenery „running”, portal „healthy”), `curl http://127.0.0.1:8000/healthz`
zwraca `{"ok":true}`, a w Cloudflare tunel ma status „Healthy”. Potem otwórz `https://twojadomena.pl`.

Zapora: wystarczy SSH (`sudo ufw allow OpenSSH && sudo ufw enable`) oraz `sudo ufw allow 51820/udp`, jeśli działa WireGuard.
Port 8000 jest wystawiony tylko na `127.0.0.1`, z internetu jest niedostępny.

Aktualizacja:

```sh
cd /opt/zniesione && sudo git pull && sudo docker compose --profile cloudflare up -d --build
```

## 2b. Portainer

1. Obraz buduje GitHub Actions po każdym wypchnięciu do gałęzi `main` (zadanie `image` w `.github/workflows/ci.yml`)
   i publikuje go jako `ghcr.io/davidniespor/zniesione:latest`. Nowy pakiet na GitHubie jest prywatny. Masz dwie możliwości:
   - GitHub → profil → **Packages → zniesione → Package settings → Change visibility → Public**, albo
   - w Portainerze **Registries → Add registry → Custom**: `ghcr.io`, login GitHub i token (classic) z uprawnieniem `read:packages`.
2. **Stacks → Add stack**, nazwa `zniesione`, **Web editor**: wklej zawartość pliku `deploy/portainer-stack.yml`.
3. Niżej, w **Environment variables**, dodaj `SECRET_KEY` (losowy, 64 znaki szesnastkowe) i `TUNNEL_TOKEN`.
4. **Deploy the stack**.
5. Konto administratora: **Containers → zniesione-zniesione-1 → Console → Connect** (`/bin/sh`), potem
   `flask --app zniesione create-admin`.

Aktualizacja: **Stacks → zniesione → Editor → Update the stack** z włączonym **Re-pull image and redeploy**.

## Kopie zapasowe

Dane (konta, zamówienia, harmonogramy, artykuły bazy wiedzy) są w jednym pliku SQLite w wolumenie `zniesione-data`.
Kopia spójna także w trakcie pracy:

```sh
cd /opt/zniesione
sudo docker compose exec zniesione python -c "import sqlite3;sqlite3.connect('/data/zniesione.db').backup(sqlite3.connect('/data/kopia.db'))"
sudo docker compose cp zniesione:/data/kopia.db ./kopia-$(date +%F).db
```

Uruchamiaj to codziennie z crona i przechowuj kopie poza serwerem. Odtworzenie: zatrzymaj stack, podmień `/data/zniesione.db`, uruchom.
W Portainerze to samo polecenie `python -c ...` wpiszesz w konsoli kontenera.

## Najczęstsze problemy

| Objaw | Przyczyna i rozwiązanie |
|---|---|
| Cloudflare pokazuje błąd 502 | W Public Hostname adres usługi musi być `zniesione:8000` (typ HTTP), a oba kontenery muszą być w tym samym stacku. |
| Logowanie „nie trzyma” sesji | Portal otwarty przez `http://` albo bezpośrednio po IP. Używaj `https://` i domeny. |
| Godziny harmonogramów przesunięte | Zła strefa czasowa: zmienna `TZ` musi być `Europe/Warsaw` (obraz ma ją domyślnie). |
| Harmonogram od wschodu słońca się nie zapisuje | Rolnik nie podał położenia gospodarstwa: Więcej → Oferta → Położenie. |
| Sterownik „Brak połączenia” | Sterownik nie wysyła odczytów co najmniej co 5 min: sprawdź zasilanie, internet i WireGuard w kurniku. |
| Po aktualizacji stary wygląd | Odśwież stronę. Adresy plików zawierają wersję, więc cache Cloudflare nie podaje starych skryptów. |

Uruchamiaj jeden kontener portalu (jeden proces gunicorna). Silnik harmonogramów i limit logowania działają w pamięci
procesu, więc kilka kopii obok siebie wysyłałoby polecenia podwójnie.
