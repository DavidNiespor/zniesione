# Wdrożenie: pełny stack na serwerze lub w Portainerze

Wszystko, czego portal potrzebuje do działania, jest w jednym pliku [`docker-compose.yml`](../docker-compose.yml) w repozytorium:

| Kontener | Rola |
|---|---|
| `siec` | wspólna sieć portalu i WireGuard; wystawia porty i nazwę `portal` dla tunelu |
| `zniesione` | portal (gunicorn, silnik harmonogramów, baza SQLite w wolumenie `zniesione-data`) |
| `wireguard` | serwer VPN, przez który portal łączy się ze sterownikami w kurnikach (10.8.0.x) |
| `cloudflared` | tunel Cloudflare: HTTPS z internetu bez otwierania portów 80 i 443 |
| `dns` | ustawia w Cloudflare rekord `wg.twojadomena.pl` → IP serwera (bez proxy) i pilnuje go przy zmianie IP |
| `kopie` | codzienna kopia bazy do wolumenu `kopie`, przechowywana 14 dni |

```
przeglądarka ──HTTPS──▶ Cloudflare ──tunel──▶ cloudflared ──▶ portal:8000 ┐
                                                                         ├─ wspólna sieć (siec)
sterownik w kurniku ──WireGuard UDP 51820──▶ serwer ──▶ wireguard (wg0)  ┘   portal ──HTTP──▶ 10.8.0.x
```

Portal sam tworzy klucze WireGuard (serwera i każdego sterownika) oraz plik `wg0.conf`. Kontener `wireguard`
wczytuje nowe sterowniki w ciągu 15 sekund, bez restartu.

## Co wybrać: serwer z konsolą czy Portainer?

Oba sposoby uruchamiają ten sam plik `docker-compose.yml` z GitHuba.
- **Nie masz Portainera:** zwykły serwer z Docker Compose, kilka poleceń w SSH.
- **Masz Portainera albo wolisz klikać:** Portainer, metoda „Repository”, buduje obraz prosto z repozytorium.

## Wymagania

- Serwer z Linuksem (np. Ubuntu 22.04 lub 24.04) z jądrem 5.6 lub nowszym (WireGuard jest w jądrze), Docker z Compose v2.
- Domena dodana do Cloudflare (plan Free wystarczy).
- Publiczny adres IP serwera i otwarty port **51820/UDP** (dla sterowników).

## 1. Cloudflare

1. Dodaj domenę do Cloudflare i u rejestratora zmień serwery nazw na te podane przez Cloudflare. Poczekaj na status „Active”.
2. **Zero Trust → Networks → Tunnels → Create a tunnel → Cloudflared**, nazwa np. `zniesione`.
3. Na ekranie instalacji wybierz **Docker** i skopiuj token z polecenia (ciąg po `--token`). To jest `TUNNEL_TOKEN`.
   Samego polecenia nie uruchamiaj: `cloudflared` jest już w stacku.
4. W tunelu dodaj adres strony: **Published application routes** (w starszym panelu **Public Hostname**) → **Add**:
   Subdomain puste (albo `www`), Domain: Twoja domena, Path puste, Service URL **`http://portal:8000`**
   (w starszym panelu: Type **HTTP** i URL `portal:8000`). Nie `https://`: szyfrowanie zapewnia Cloudflare.
5. **SSL/TLS → Edge Certificates → Always Use HTTPS**: włącz. Logowanie działa tylko przez `https://`.
   Rekord DNS dla adresu strony Cloudflare tworzy sam przy zapisie tej trasy.
6. Rekord dla sterowników (`wg.twojadomena.pl`, WireGuard nie przechodzi przez proxy Cloudflare) ustawia kontener `dns`.
   Potrzebuje tokenu API: **My Profile → API Tokens → Create Token → szablon „Edit zone DNS”** → Zone Resources:
   *Include → Specific zone → Twoja domena* → **Continue → Create Token**. Skopiuj token jako `CF_API_TOKEN`,
   a `WG_HOST` ustaw na np. `wg.twojadomena.pl`.
   Bez tokenu dodaj rekord ręcznie: **DNS → Add record**, typ **A**, nazwa `wg`, adres = publiczny IP serwera,
   **Proxy: DNS only** (szara chmurka). Przy zmiennym IP trzeba go wtedy poprawiać samemu.
7. (Zalecane) **Security → WAF → Rate limiting rules**: np. 20 żądań na minutę na `/api/auth/login`.

## 2a. Serwer z Docker Compose

```sh
curl -fsSL https://get.docker.com | sudo sh
sudo git clone https://github.com/DavidNiespor/zniesione.git /opt/zniesione
cd /opt/zniesione
sudo cp .env.example .env
python3 -c "import secrets;print(secrets.token_hex(32))"     # wklej jako SECRET_KEY
sudo nano .env                                              # SECRET_KEY, TUNNEL_TOKEN, CF_API_TOKEN, WG_HOST
sudo docker compose up -d --build
sudo docker compose exec zniesione flask --app zniesione create-admin
```

Zapora: `sudo ufw allow OpenSSH && sudo ufw allow 51820/udp && sudo ufw enable`. Portów 80 i 443 nie otwieraj.
Stack nie zajmuje portu 8000 na serwerze, więc nie koliduje z Portainerem ani innymi usługami.

Aktualizacja: `cd /opt/zniesione && sudo git pull && sudo docker compose up -d --build`

## 2b. Portainer

1. **Stacks → Add stack**, nazwa `zniesione`, metoda **Repository**:
   - Repository URL: `https://github.com/DavidNiespor/zniesione`, Reference: `refs/heads/main`,
   - Compose path: `docker-compose.yml`,
   - repozytorium prywatne: włącz **Authentication** (login GitHub i token z dostępem do repozytorium).
2. **Environment variables**: dodaj `SECRET_KEY`, `TUNNEL_TOKEN`, `CF_API_TOKEN` i `WG_HOST` (opcjonalnie `WG_PORT`, `KEEP_DAYS`, `TZ`), jak w `.env.example`.
3. **Deploy the stack**. Pierwsze uruchomienie buduje obraz portalu, to trwa około minuty.
4. Konto administratora: **Containers → zniesione-zniesione-1 → Console → Connect** (`/bin/sh`),
   potem `flask --app zniesione create-admin`.

Aktualizacja: **Stacks → zniesione → Pull and redeploy** (można też włączyć „Automatic updates” z GitHuba).

## 3. Po uruchomieniu

1. Sprawdź stan: `docker compose ps` (serwer) albo lista kontenerów w Portainerze. Portal ma być „healthy”,
   w logach `wireguard` widać „WireGuard działa”, a w Cloudflare tunel ma status „Healthy”.
2. Zaloguj się jako administrator na `https://twojadomena.pl`.
3. W logach kontenera `dns` powinno być `wg.twojadomena.pl -> <IP>: created` (albo `unchanged`). Adres i port WireGuard
   portal bierze ze zmiennych `WG_HOST` i `WG_PORT`, więc w **Administrator → Konfiguracja** nie trzeba ich wpisywać.
4. Dla każdego sterownika: konfiguracja ESPHome (przycisk w panelu) i **Dane techniczne → Pobierz secrets.yaml**
   (klucze WireGuard, uzupełnij Wi-Fi). Wgraj oba pliki do sterownika w ESPHome.

## Kopie zapasowe

Kontener `kopie` zapisuje kopię bazy raz na dobę do wolumenu `kopie` i usuwa kopie starsze niż `KEEP_DAYS` dni.
W bazie są też klucze WireGuard, więc kopie przechowuj bezpiecznie. Skopiowanie najnowszych kopii na swój komputer lub dysk:

```sh
cd /opt/zniesione && sudo docker compose cp kopie:/backup ./kopie-$(date +%F)
```

Odtworzenie: `docker compose stop zniesione`, skopiuj wybrany plik jako `/data/zniesione.db`
(`docker compose cp ./plik.db zniesione:/data/zniesione.db`), potem `docker compose start zniesione`.

## Najczęstsze problemy

| Objaw | Przyczyna i rozwiązanie |
|---|---|
| „Bind for 0.0.0.0:… port is already allocated” | Port jest zajęty przez inną usługę. Stack wystawia tylko `WG_PORT` (domyślnie 51820/UDP): jeśli i ten jest zajęty, ustaw inny `WG_PORT` i ten sam port w Konfiguracji admina. |
| Cloudflare: błąd 502 | Adres usługi w tunelu musi być `http://portal:8000` (nie `https://`, nie `localhost`). |
| Logowanie nie trzyma sesji | Portal otwarty przez `http://` lub po IP. Używaj `https://` i domeny. |
| Sterownik „Brak połączenia” | Rekord `wg` z wyłączonym proxy, otwarty port UDP, poprawny adres i port w Konfiguracji, wgrany secrets.yaml. Podgląd tunelu: `docker compose exec wireguard wg show`. |
| Logi `dns`: „Token nie ma dostępu do strefy” albo „Invalid token” | Token musi mieć szablon „Edit zone DNS” dla Twojej domeny, a `WG_HOST` musi być w tej domenie. |
| `wireguard` restartuje się | Brak WireGuard w jądrze (`sudo modprobe wireguard`) albo brak `cap_add: NET_ADMIN`. |
| Po restarcie kontenera `siec` portal nie działa | `docker compose up -d` odtwarza całość; `siec` i tak restartuje się tylko przy aktualizacji Dockera. |
| Godziny harmonogramów przesunięte | Zmienna `TZ` musi być `Europe/Warsaw` (domyślnie tak jest). |
| Zmiana podsieci w Konfiguracji | Uruchom ponownie kontener `wireguard` (nowy adres serwera). Zmieniaj ją tylko przed dodaniem sterowników. |

Uruchamiaj jedną kopię portalu: silnik harmonogramów i limit logowania działają w pamięci procesu.
