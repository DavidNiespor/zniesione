# zniesione

Portal dla rolników z kurnikami: sprzedaż jaj od rolnika (zamówienia jednorazowe i cykliczne, potwierdza rolnik),
sterowanie kurnikiem (światło, drzwi, wentylacja, grzałki, elektrozawory), harmonogramy (także od wschodu i zachodu
słońca), termostat, odczyty temperatury oraz panel administratora z przypisywaniem sterowników do farm.

## Uruchomienie
    pip install -r requirements-dev.txt && python -m pytest -q
    export SECRET_KEY=$(python -c "import secrets;print(secrets.token_hex(32))")
    flask --app zniesione create-admin
    RUN_SCHEDULER=1 flask --app zniesione run

**Produkcja:** `docker-compose.yml` to pełny stack: portal, serwer WireGuard dla sterowników (klucze i `wg0.conf`
tworzy portal), tunel Cloudflare, rekordy DNS ustawiane automatycznie, serwer poczty `@zniesione.pl` z pocztą
w przeglądarce (`poczta.zniesione.pl`) i codzienne kopie bazy. Konto administratora portalu i poczty tworzy się samo
ze zmiennych stacka. Instrukcja: [docs/WDROZENIE.md](docs/WDROZENIE.md).

`/` serwuje interfejs (`static/app.html`, `app.css`, `app.js`). Stara makieta bez backendu jest pod `/prototype`.

Zmienne środowiskowe: `SECRET_KEY`, `DATABASE` (plik SQLite), `RUN_SCHEDULER=1` (silnik w wątku aplikacji),
`TICK_S` (odstęp obiegu silnika, domyślnie 2 s), `DEVICE_BASE` (adres atrapy urządzenia w testach),
`PROXY_COUNT` (liczba odwrotnych proxy przed aplikacją, adres klienta z `X-Forwarded-For`),
`REAL_IP_HEADER` (np. `CF-Connecting-IP`; tylko gdy aplikacja jest osiągalna wyłącznie przez Cloudflare).
Godziny harmonogramów i wschód/zachód słońca liczone są w strefie czasowej serwera (`TZ`, w obrazie Dockera domyślnie `Europe/Warsaw`).

## Funkcje
Panel rolnika (telefon jako pierwszy, dolne menu Start, Jaja, Sterowanie, Zamówienia, Więcej; na komputerze menu boczne):
- **Start**: powitanie według pory dnia, skróty Zbiór jaj, Sprzedaż, Zamówienia (z liczbą oczekujących), Sterowanie,
  karta „Stan kurnika” (temperatura, wilgotność, światło, drzwi z szybkimi przyciskami).
- **Sterowanie**: karta na każde urządzenie: odczyty i wykresy 24 h (temperatura i wilgotność osobno), kafelki światła
  i drzwi (Otwórz/Zamknij), pozostałe urządzenia z nazwą, przełącznikiem i automatyką „włącz powyżej/poniżej X °C”,
  harmonogramy, ostatnie zdarzenia, konfiguracja ESPHome (podgląd i kopiowanie), przypisanie przekaźników.
  Odczyty, stany i dziennik odświeżają się co 10 s bez przebudowy formularzy i bez utraty fokusu.
- **Harmonogramy**: początek o godzinie, względem wschodu albo zachodu słońca (przesunięcie ±180 min); koniec o godzinie,
  względem słońca albo po czasie działania (1 s – 12 h, auto-wyłączenie zapisane w bazie). Włączanie i wyłączanie
  przełącznikiem, zmiana godzin i dni. Okno od słońca, które przeszłoby przez północ i trwało ponad 18 h, jest puste
  (np. zimą „od wschodu −30 min do 07:00”, gdy wschód jest po 07:30).
- **Drzwi**: otwarcie i zamknięcie to impuls: przekaźnik włącza się na `door_run_s` (domyślnie 20 s, ustawiane w panelu),
  potem silnik wyłącza go sam. Przekaźniki otwierania i zamykania nigdy nie są włączone jednocześnie. Harmonogram drzwi:
  otwórz na początku okna, zamknij na końcu.
- **Silnik** (`services.tick`): najpierw zaplanowane wyłączenia (`channels.off_at`), potem harmonogram drzwi, potem pozostałe
  kanały. Reaguje na zmianę stanu pożądanego, więc ręczna zmiana obowiązuje do następnej zmiany w harmonogramie lub termostacie.
  Nieudane polecenie jest ponawiane co 30 s; wszystko jest w bazie, więc restart aplikacji nie zostawia przekaźnika
  włączonego na stałe. Bez `time.sleep`.
- **Zabezpieczenia w sterowniku** (generowany YAML ESPHome): każdy przekaźnik `restore_mode: ALWAYS_OFF`, przekaźniki drzwi
  z `interlock` i wyłączeniem po `door_run_s` w samym sterowniku, więc drzwi zatrzymają się także bez internetu.
  Po zmianie czasu pracy silnika trzeba ponownie wgrać konfigurację.
- **Jaja** (zbiór i sprzedaż na miejscu zmieniają stan w sklepie atomowo, dziennik wpisów), **Stado** (stada, liczba kur, rasa,
  notatki, jaja dziennie i szacunkowa nieśność ze zbiorów), **Zamówienia**, **Klienci** (z zamówień, przycisk Zadzwoń),
  **Oferta** (cena, opis, położenie gospodarstwa, przycisk „Użyj mojej lokalizacji”), **Sterowniki** (zamawianie, etapy dostawy),
  **Raporty** (jaja z 7 i 30 dni, sprzedaż z 30 dni i od początku), **Baza wiedzy** (porady z wyszukiwaniem i kategoriami),
  **Ustawienia** (motyw auto/jasny/czarny zapamiętany w przeglądarce, wylogowanie).
- Tylko sterowniki z katalogu operatora (`catalog.py`): API odrzuca inne modele, interfejs nie ma innych opcji.
  Najtańszy model (LilyGO T-Relay) jest oznaczony i domyślny, bez ceny w kodzie.
- Rolnik widzi rodzaje kanałów po polsku, nigdy kluczy `ch1`…; API używa kodów z `catalog.KINDS`.

Administrator: przypisywanie sterowników do farm, etapy dostawy, **baza wiedzy** (artykuły z prostym formatowaniem:
nagłówki, listy, pogrubienie, ramki, linki, obrazy https; podgląd na żywo, szkic lub publikacja), konfiguracja tunelu
WireGuard, odczyt testowy, uruchomienie silnika, generator YAML dla ESPHome (T-Relay, T-RelayS3, Waveshare, Shelly: instrukcja MQTT).
Treść artykułów jest escapowana przed formatowaniem, więc HTML wpisany w artykuł nie jest wykonywany.

Bezpieczeństwo: nagłówek `X-Requested-With` przy zmianach (CSRF), każde zapytanie rolnika sprawdza własność urządzenia
po `farm_id`, limit logowania (5 nieudanych prób na e-mail i 20 na adres IP w ciągu 10 min, licznik w pamięci procesu),
ciasteczko sesji `HttpOnly`, `SameSite=Lax`, `Secure` poza trybem testowym (bez `Secure` tylko pod 127.0.0.1/localhost,
żeby działało uruchomienie lokalne po http), walidacja wszystkich pól (zakresy, typy, GG:MM, dni).

## API panelu rolnika (wybrane)
| Metoda i ścieżka | Opis |
|---|---|
| `GET /api/my/devices` | urządzenia z kanałami, regułami termostatu, ostatnimi odczytami, `door`, `door_run_s` |
| `PATCH /api/my/devices/<id>` | `door_run_s` (1–300) |
| `POST /api/my/devices/<id>/door` | `{"action": "open" \| "close"}` |
| `POST /api/my/devices/<id>/channels/<key>` | `{"state": true}`; `PATCH`: nazwa i rodzaj |
| `GET/POST /api/my/devices/<id>/schedules`, `PATCH/DELETE …/<sid>` | `mode`/`off_mode`: `time`, `sunrise`, `sunset`; `t_on`, `t_off`, `offset_min`, `off_offset_min`, `duration_s`, `days` (`a`, `w`, `e`), `enabled` |
| `PUT /api/my/devices/<id>/rules/<key>` | `threshold`, `enabled` (wentylacja i grzanie) |
| `GET /api/my/devices/<id>/log?limit=` | zdarzenia: nazwa kanału, `src` (`manual`, `schedule`, `thermostat`, `timer`), `ok` |
| `GET /api/my/devices/<id>/readings?hours=` | historia temperatury i wilgotności (1–168 h) |
| `GET/PUT /api/my/farm` | oferta i położenie (`lat`, `lon`; niewidoczne publicznie) |
| `GET /api/catalog`, `GET /api/kinds` | katalog z flagami `cheapest`, `default`; polskie nazwy rodzajów |
| `GET/POST /api/my/flocks`, `PATCH/DELETE …/<id>` | stada: `name`, `birds` (0–100 000), `breed`, `since` (RRRR-MM-DD), `notes` |
| `GET /api/my/eggs?days=`, `POST /api/my/eggs` | dziennik jaj; `{"kind": "collect" \| "sale", "packs": 1–500}` zmienia stan |
| `GET /api/kb?q=&category=`, `GET /api/kb/<id>` | baza wiedzy (zalogowani; rolnik widzi tylko opublikowane) |
| `POST /api/admin/kb`, `PUT/DELETE /api/admin/kb/<id>` | artykuły: `title`, `category`, `body`, `published` (tylko admin) |

## Ograniczenia i do zrobienia
- **Do weryfikacji na sprzęcie:** ścieżka REST `/switch/<id>/turn_on` w `services.send_http` (web_server ESPHome)
  oraz zabezpieczenia w YAML (`interlock`, `on_turn_on` z `delay`). Sterowanie, impulsy drzwi i ponawianie sprawdzono
  tylko na atrapie `tools/fake_device.py`, a YAML tylko parserem (nie kompilatorem ESPHome).
- Portal nie odczytuje stanu przekaźników ze sterownika (wymagałoby to API ESPHome, którego nie zgadujemy): po zaniku
  zasilania w kurniku przekaźniki są wyłączone (`ALWAYS_OFF`), a portal może jeszcze pokazywać stan sprzed awarii.
- Limit logowania jest w pamięci jednego procesu (gunicorn z 1 workerem, jak w Dockerfile). Za Cloudflare ustaw
  `REAL_IP_HEADER` albo `PROXY_COUNT` (w `docker-compose.yml` są ustawione).
- Nieśność w Stadzie jest szacunkowa: liczona z zapisanych zbiorów w pełnych opakowaniach po 10 jaj.
- Hasło API i OTA w secrets.yaml są losowane przy każdym pobraniu (portal ich nie używa); klucze WireGuard są stałe.
- Poza zakresem: Shelly przez MQTT (sterowanie zwraca błąd „niezaimplementowane”), OTA z portalu, płatności online,
  reset hasła, e-mail/SMS, integracja z e-kurnik.

## Windows (PowerShell)
Potrzebne są dwa okna PowerShella w katalogu projektu. `flask` często nie jest w PATH, więc używaj `python -m flask`.
Gunicorn nie działa na Windows, lokalnie wystarczy serwer Flaska.

Okno 1 (atrapa sterownika):

    python tools/fake_device.py 9000

Okno 2 (portal):

    $env:DATABASE="$PWD\zn.db"; $env:SECRET_KEY="test"; $env:DEVICE_BASE="http://127.0.0.1:9000"; $env:RUN_SCHEDULER="1"
    python -m flask --app zniesione seed-demo
    python -m flask --app zniesione run

Potem otwórz http://127.0.0.1:5000 (nie przez inny adres, bo poza 127.0.0.1/localhost ciasteczko wymaga HTTPS).
Seed działa tylko na pustej bazie, więc przed ponownym uruchomieniem usuń plik `zn.db`.
Testy: `python -m pytest -q`. Test e2e (wymaga Node.js 18+): `cd tests\e2e; npm i; cd ..\..; node tests\e2e\run.js`.

## Testy funkcjonalne (ręczne)
Linux/macOS: `export DATABASE=/tmp/zn.db SECRET_KEY=test DEVICE_BASE=http://127.0.0.1:9000 RUN_SCHEDULER=1`,
potem `python tools/fake_device.py 9000 &`, `flask --app zniesione seed-demo`, `flask --app zniesione run`.

Konta demo (tylko do testów, nie używaj na produkcji):
| Rola | E-mail | Hasło |
|---|---|---|
| admin | admin@zniesione.test | Admin12345! |
| rolnik (farma „Kurnik pod Lipą", sterownik online, położenie ustawione) | rolnik@zniesione.test | Rolnik12345! |
| rolnik 2 i 3 | rolnik2@zniesione.test, rolnik3@zniesione.test | Rolnik12345! |

Scenariusze do przejścia ręcznie (najlepiej na telefonie lub w trybie telefonu przeglądarki, szerokość 375 px):
1. Klient: wyszukaj „45”, zamów jaja jednorazowo i cyklicznie.
2. Rolnik, Start: sprawdź powitanie, liczbę oczekujących zamówień, włącz światło i otwórz drzwi z karty „Stan kurnika”.
3. Rolnik, Zamówienia: potwierdź i odrzuć zamówienie; Jaja: dodaj zbiór, sprawdź stan w sklepie.
4. Rolnik, Sterowanie: Otwórz, potem Zamknij drzwi (w konsoli atrapy `ch2 -> on`, `ch2 -> off`, `ch3 -> on`, po 20 s `ch3 -> off`).
5. Rolnik, Sterowanie: dodaj harmonogram „Światło, względem wschodu słońca, przesunięcie −30, wyłącz o 07:00”, wyłącz go przełącznikiem.
6. Rolnik, Sterowanie: przy Wentylatorze ustaw „Włącz powyżej 25 °C”. Admin: wyślij odczyt 28 °C, kliknij „Uruchom silnik teraz”, atrapa dostaje `ch4 -> on`.
7. Zatrzymaj atrapę w trakcie pracy silnika drzwi i uruchom ponownie: wyłączenie zostanie wysłane po powrocie.
8. Admin: przypisz sterownik do innej farmy, rolnik 1 przestaje go widzieć.
9. Rolnik, Więcej, Sterowniki: T-Relay jest domyślny i oznaczony jako najtańszy; T-Relay z Tailscale zostaje odrzucony.

## Testy automatyczne
    python -m pytest -q                                  # 68 testów API i logiki
    cd tests/e2e && npm i && cd ../.. && node tests/e2e/run.js   # 73 kroki przez interfejs (jsdom), każdy system
`run.js` zakłada bazę w katalogu tymczasowym, uruchamia atrapę urządzenia (port 9123) i serwer Flaska (port 8765);
porty i interpreter zmienisz zmiennymi `DEV_PORT`, `WEB_PORT`, `PYTHON`. `tests/e2e/run.sh` tylko wywołuje `run.js`.
Test e2e nie zastępuje sprawdzenia w prawdziwej przeglądarce na telefonie.
