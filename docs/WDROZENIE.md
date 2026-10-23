# Wdrożenie: pełny stack na serwerze lub w Portainerze

Wszystko, czego portal potrzebuje do działania, jest w jednym pliku [`docker-compose.yml`](../docker-compose.yml) w repozytorium:

| Kontener | Rola |
|---|---|
| `siec` | wspólna sieć portalu i WireGuard; wystawia port WireGuard i nazwę `portal` dla tunelu |
| `zniesione` | portal (gunicorn, silnik harmonogramów, baza SQLite w wolumenie `zniesione-data`) |
| `wireguard` | serwer VPN, przez który portal łączy się ze sterownikami w kurnikach (10.8.0.x) |
| `cloudflared` | tunel Cloudflare: strona i poczta w przeglądarce przez HTTPS, bez otwierania portów 80 i 443 |
| `dns` | ustawia w Cloudflare rekordy: `wg.` (WireGuard), `mail.`, MX, SPF, DKIM, DMARC; pilnuje ich przy zmianie IP |
| `poczta-start` | jednorazowo: skrzynka `admin@zniesione.pl`, aliasy `postmaster@` i `abuse@`, klucz DKIM |
| `certyfikat` | certyfikat TLS dla `mail.zniesione.pl` z Let's Encrypt (przez DNS Cloudflare), odnawiany sam |
| `poczta` | serwer poczty docker-mailserver: SMTP, IMAP, filtr spamu, DKIM, blokada zgadywania haseł |
| `webmail` | Roundcube: poczta w przeglądarce pod `poczta.zniesione.pl` |
| `kopie` | codzienna kopia bazy portalu do wolumenu `kopie`, przechowywana 14 dni |

```
przeglądarka ──HTTPS──▶ Cloudflare ──tunel──▶ cloudflared ──▶ portal:8000 (zniesione.pl)
                                                         └──▶ webmail:80  (poczta.zniesione.pl)
sterownik w kurniku ──WireGuard UDP 51820──▶ serwer ──▶ wireguard ◀── portal łączy się ze sterownikami (10.8.0.x)
inne serwery poczty ──SMTP 25──▶ serwer ──▶ poczta ◀── telefon i program pocztowy (IMAP 993, SMTP 465/587)
```

## Zanim zaczniesz: wymagania

- Serwer z Linuksem (np. Ubuntu 22.04 lub 24.04), jądro 5.6 lub nowsze, Docker z Compose v2, **co najmniej 2 GB RAM**
  (portal z pocztą i filtrem spamu zajmuje ok. 1–1,5 GB).
- **Stały publiczny adres IPv4** serwera.
- Domena `zniesione.pl` dodana do Cloudflare (plan Free wystarczy), status „Active”.
- **Port 25 otwarty w obie strony.** Wielu dostawców VPS i łączy domowych go blokuje; czasem odblokowują go na prośbę
  (zgłoszenie do supportu). Bez portu 25 poczta nie będzie przychodzić ani wychodzić do innych serwerów.
- **Rekord odwrotny (PTR, „reverse DNS”) adresu IP serwera = `mail.zniesione.pl`.** Ustawia się go w panelu dostawcy
  serwera (nie w Cloudflare). Bez niego Gmail, Onet, WP i inni odrzucą albo wrzucą pocztę do spamu.
- Porty do otwarcia w zaporze serwera (i ewentualnie w routerze): **25, 465, 587, 993 (TCP)** oraz **51820 (UDP)**.

## 1. Cloudflare

### 1.1. Tunel (strona i poczta w przeglądarce)
1. **dash.cloudflare.com → Zero Trust → Networks → Tunnels → Create a tunnel → Cloudflared**, nazwa np. `zniesione`.
2. Na ekranie instalacji wybierz **Docker** i skopiuj ciąg po `--token` (zaczyna się od `eyJ`). To jest `TUNNEL_TOKEN`.
   Polecenia nie uruchamiaj, `cloudflared` jest w stacku.
3. W tunelu: **Published application routes** (w starszym panelu **Public Hostname**) → **Add**, dwie pozycje:

   | Subdomain | Domain | Path | Service URL |
   |---|---|---|---|
   | puste | `zniesione.pl` | puste | `http://portal:8000` |
   | `poczta` | `zniesione.pl` | puste | `http://webmail:80` |

   Rekordy DNS dla tych adresów Cloudflare tworzy sam. W starszym panelu wybierz Type **HTTP** i wpisz URL bez `http://`.
4. **SSL/TLS → Edge Certificates → Always Use HTTPS**: włącz.

### 1.2. Token API (rekordy DNS i certyfikat poczty)
1. Profil (prawy górny róg) → **My Profile → API Tokens → Create Token** → szablon **Edit zone DNS → Use template**.
2. **Zone Resources**: *Include → Specific zone → zniesione.pl* → **Continue to summary → Create Token**.
3. Skopiuj token (pokazuje się tylko raz). To jest `CF_API_TOKEN`.

Kontener `dns` ustawi nim sam: `wg.zniesione.pl` i `mail.zniesione.pl` (A, bez proxy), `MX zniesione.pl → mail.zniesione.pl`,
SPF `v=spf1 mx -all`, DMARC i klucz DKIM. Jeśli SPF albo DMARC już istnieje, zostawi go i napisze o tym w logach.
Jeśli w domenie jest włączone **Cloudflare Email Routing**, wyłącz je (Email → Email Routing → Settings → Disable):
jego rekordy MX kierowałyby pocztę do Cloudflare zamiast do Twojego serwera.

## 2. Zmienne stacka

Wszystkie są opisane w [`.env.example`](../.env.example). Wymagane:

| Zmienna | Co wpisać |
|---|---|
| `SECRET_KEY` | losowy klucz sesji: `python3 -c "import secrets;print(secrets.token_hex(32))"` |
| `TUNNEL_TOKEN` | token tunelu z punktu 1.1 |
| `CF_API_TOKEN` | token API z punktu 1.2 |
| `MAIL_ADMIN_PASSWORD` | hasło skrzynki `admin@zniesione.pl` (min. 10 znaków) |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | konto administratora portalu, np. `admin@zniesione.pl` i hasło (min. 8 znaków) |

Konto administratora portalu tworzy się samo przy pierwszym starcie. Późniejsza zmiana `ADMIN_PASSWORD` nie zmienia
już hasła (żeby restart nie nadpisał hasła zmienionego w portalu).

## 3a. Serwer z Docker Compose

```sh
curl -fsSL https://get.docker.com | sudo sh
sudo git clone https://github.com/DavidNiespor/zniesione.git /opt/zniesione
cd /opt/zniesione
sudo cp .env.example .env
sudo nano .env                     # uzupełnij zmienne z punktu 2
sudo docker compose up -d --build
sudo ufw allow OpenSSH && sudo ufw allow 25,465,587,993/tcp && sudo ufw allow 51820/udp && sudo ufw enable
```

Aktualizacja: `cd /opt/zniesione && sudo git pull && sudo docker compose up -d --build`

## 3b. Portainer

1. **Stacks → Add stack**, nazwa `zniesione`, metoda **Repository**:
   Repository URL `https://github.com/DavidNiespor/zniesione`, Reference `refs/heads/main`, Compose path `docker-compose.yml`.
2. **Environment variables**: dodaj zmienne z punktu 2 (przycisk „Add an environment variable”).
3. **Deploy the stack**. Pierwsze uruchomienie buduje obraz portalu i pobiera obrazy poczty: kilka minut.

Aktualizacja: **Stacks → zniesione → Pull and redeploy**.

## 4. Pierwsze uruchomienie: co powinno się stać

W ciągu kilku minut (logi kontenerów w Portainerze albo `docker compose logs -f <kontener>`):
1. `poczta-start`: „Utworzono skrzynkę admin@zniesione.pl”, „Poczta przygotowana”, potem kończy pracę (to normalne).
2. `dns`: lista rekordów z wynikiem `created` (przy kolejnych obiegach już tylko zmiany).
3. `certyfikat`: „Successfully received certificate”. Do tego czasu `poczta` może się restartować: czeka na certyfikat.
4. `poczta`: działa (status „healthy”). `wireguard`: „WireGuard działa”. W Cloudflare tunel ma status „Healthy”.

## 5. Jak wejść

| Co | Adres | Login |
|---|---|---|
| Portal (administrator) | `https://zniesione.pl` → „Zaloguj / Zarejestruj” | `ADMIN_EMAIL` i `ADMIN_PASSWORD` |
| Poczta w przeglądarce | `https://poczta.zniesione.pl` | `admin@zniesione.pl` i `MAIL_ADMIN_PASSWORD` |

Program pocztowy lub telefon (Gmail, Outlook, Thunderbird, Poczta w iPhonie): konto **IMAP**

| | Serwer | Port | Szyfrowanie | Login |
|---|---|---|---|---|
| Poczta przychodząca (IMAP) | `mail.zniesione.pl` | 993 | SSL/TLS | pełny adres e-mail |
| Poczta wychodząca (SMTP) | `mail.zniesione.pl` | 465 (SSL/TLS) albo 587 (STARTTLS) | jak obok | pełny adres e-mail, to samo hasło |

Poczta do `postmaster@zniesione.pl` i `abuse@zniesione.pl` trafia do skrzynki administratora.

## 6. Kolejne skrzynki i hasła

Polecenia wpisujesz w konsoli kontenera `poczta` (Portainer: **Containers → zniesione-poczta-1 → Console → Connect**,
powłoka `/bin/bash`) albo na serwerze z przedrostkiem `sudo docker compose exec poczta`:

```sh
setup email add jan@zniesione.pl            # nowa skrzynka (zapyta o hasło)
setup email update admin@zniesione.pl       # zmiana hasła
setup email list                            # lista skrzynek
setup alias add sklep@zniesione.pl admin@zniesione.pl   # dodatkowy adres kierowany do istniejącej skrzynki
setup email del jan@zniesione.pl            # usunięcie skrzynki
```

Hasło do portalu zmieniasz osobno (konta portalu i poczty są niezależne). Kolejnego administratora portalu dodasz
w konsoli kontenera `zniesione`: `flask --app zniesione create-admin`.

## 7. Sprawdzenie poczty

1. Wyślij list z `admin@zniesione.pl` na swój adres Gmail i odpowiedz na niego.
2. W Gmailu: list → ⋮ → **Pokaż oryginał**: SPF, DKIM i DMARC powinny mieć wynik **PASS**.
3. Dokładny test: wyślij list na adres podany na **mail-tester.com** (cel: 9/10 lub 10/10).

## Kopie zapasowe

Kontener `kopie` zapisuje raz na dobę kopię bazy portalu (konta, zamówienia, harmonogramy, artykuły, klucze WireGuard).
Pocztę przechowują wolumeny `zniesione_poczta-dane` i `zniesione_poczta-konfig`. Uwzględnij je w kopii całego serwera
(migawki u dostawcy VPS albo np. `docker run --rm -v zniesione_poczta-dane:/d -v $PWD:/b alpine tar czf /b/poczta.tgz -C /d .`).

Kopia bazy portalu na dysk: `cd /opt/zniesione && sudo docker compose cp kopie:/backup ./kopie-$(date +%F)`

## Najczęstsze problemy

| Objaw | Przyczyna i rozwiązanie |
|---|---|
| „Bind for 0.0.0.0:25 (albo 465, 587, 993, 51820) failed: port is already allocated” | Na serwerze działa już inny serwer poczty lub WireGuard (np. Postfix z systemu: `sudo systemctl disable --now postfix`). |
| Brak zmiennej, np. „ustaw CF_API_TOKEN” | Uzupełnij zmienne z punktu 2. |
| Cloudflare: błąd 502 | Adres usługi w tunelu: `http://portal:8000` (portal) i `http://webmail:80` (poczta), nie `https://`. |
| `poczta` restartuje się dłużej niż 5 minut | Brak certyfikatu: sprawdź logi `certyfikat` (zły token albo token bez uprawnień do strefy). |
| Poczta nie przychodzi | Port 25 zablokowany u dostawcy, MX wskazuje gdzie indziej (Email Routing) albo zapora. Test: `nc -vz mail.zniesione.pl 25` z innej sieci. |
| Wysłane listy lądują w spamie | Brak rekordu PTR = `mail.zniesione.pl` u dostawcy serwera; sprawdź też wynik na mail-tester.com. |
| Logowanie do portalu nie trzyma sesji | Portal otwarty przez `http://` lub po IP. Używaj `https://zniesione.pl`. |
| Sterownik „Brak połączenia” | Port 51820/UDP, wgrany secrets.yaml; podgląd tunelu: `docker compose exec wireguard wg show`. |
| Logi `dns`: „Token nie ma dostępu do strefy” / „Invalid token” | Token musi mieć szablon „Edit zone DNS” dla Twojej domeny. |
| Godziny harmonogramów przesunięte | Zmienna `TZ` musi być `Europe/Warsaw` (domyślnie tak jest). |

Uruchamiaj jedną kopię portalu: silnik harmonogramów i limit logowania działają w pamięci procesu.
