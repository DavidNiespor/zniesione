# zniesione

Portal dla rolników z kurnikami: sprzedaż jaj od rolnika (zamówienia jednorazowe i cykliczne, potwierdza rolnik),
sterowanie kurnikiem (światło, drzwi, wentylacja, grzałki, elektrozawory), harmonogramy, termostat, odczyty
temperatury oraz panel administratora z przypisywaniem sterowników do farm.

## Uruchomienie
    pip install -r requirements-dev.txt && python -m pytest -q
    export SECRET_KEY=$(python -c "import secrets;print(secrets.token_hex(32))")
    flask --app zniesione create-admin
    RUN_SCHEDULER=1 flask --app zniesione run        # lub: docker compose up --build

`/` serwuje interfejs podpięty do API (`static/app.html`). Stara makieta bez backendu jest pod `/prototype`.

## Co jest zrobione i przetestowane
Konta (rolnik, admin), publiczne wyszukiwanie farm i zamówienia, potwierdzanie zamówień przez rolnika, katalog
tylko sprzedawanych modeli, rejestracja i przypisywanie sterowników przez admina, alokacja adresów VPN, generator
YAML dla ESPHome (T-Relay, T-RelayS3, Waveshare, Shelly: instrukcja MQTT), odczyty z kluczem API urządzenia,
sterowanie z blokadą drzwi, harmonogramy (także przez północ), termostat z histerezą, silnik porównujący stan
(nadrabia utracone minuty, ponawia nieudane polecenia, oznacza urządzenia offline), ochrona CSRF nagłówkiem.

## Czego jeszcze nie ma (świadomie)
- Harmonogram drzwi (wymaga krańcówek i czasu pracy silnika).
- Shelly przez MQTT (sterowanie zwraca błąd "niezaimplementowane").
- Serwer WireGuard, ESPHome Device Builder i OTA: konfiguracja po stronie serwera.
- Ścieżkę REST `/switch/<id>/turn_on` zweryfikuj na sprzęcie z web_server ESPHome (`services.send_http`).
- Limit prób logowania, reset hasła, e-mail/SMS do rolnika, płatności online.
- Integracja z e-kurnik (`stan_magazynu`): tu zapas to prosty licznik `farms.stock`.

## Windows (PowerShell)
Potrzebne są dwa okna PowerShella w katalogu projektu. Polecenia `export` i `&` z poniższej sekcji dla Linuxa tam nie działają,
a `flask` często nie jest w PATH, więc używaj `python -m flask`. Gunicorn nie działa na Windows, do testów wystarczy serwer Flaska.

Okno 1 (atrapa sterownika):

    python tools/fake_device.py 9000

Okno 2 (portal):

    $env:DATABASE="$PWD\zn.db"; $env:SECRET_KEY="test"; $env:DEVICE_BASE="http://127.0.0.1:9000"; $env:RUN_SCHEDULER="1"
    python -m flask --app zniesione seed-demo
    python -m flask --app zniesione run

Potem otwórz http://127.0.0.1:5000. Seed działa tylko na pustej bazie, więc przed ponownym uruchomieniem usuń plik `zn.db`.
Testy: `python -m pytest -q`. Skrypt `tests/e2e/run.sh` wymaga powłoki sh (Linux, macOS, WSL albo Git Bash).

## Testy funkcjonalne (ręczne)
    export DATABASE=/tmp/zn.db SECRET_KEY=test DEVICE_BASE=http://127.0.0.1:9000 RUN_SCHEDULER=1
    python tools/fake_device.py 9000 &          # atrapa sterownika: wypisuje polecenia, GET /state pokazuje stan
    flask --app zniesione seed-demo             # dane demo
    flask --app zniesione run                   # http://127.0.0.1:5000

Konta demo (tylko do testów, nie używaj na produkcji):
| Rola | E-mail | Hasło |
|---|---|---|
| admin | admin@zniesione.test | Admin12345! |
| rolnik (farma „Kurnik pod Lipą", sterownik online) | rolnik@zniesione.test | Rolnik12345! |
| rolnik 2 i 3 | rolnik2@zniesione.test, rolnik3@zniesione.test | Rolnik12345! |

Scenariusze do przejścia ręcznie:
1. Klient: wyszukaj „45", zamów jaja jednorazowo i cyklicznie.
2. Rolnik: potwierdź i odrzuć zamówienie, zmień cenę i stan, sprawdź, że stan spada po potwierdzeniu.
3. Rolnik: włącz światło (zobacz polecenie w konsoli atrapy), dodaj harmonogram, ustaw termostat wentylatora na 25 °C.
4. Admin: wyślij odczyt 28 °C, kliknij „Uruchom silnik teraz", sprawdź, że atrapa dostała `ch4 -> on`. Wyślij 22 °C i uruchom ponownie: `ch4 -> off`.
5. Admin: przypisz sterownik do innej farmy, rolnik 1 przestaje go widzieć.
6. Rolnik: zamów T-Relay z Tailscale (odrzucone), zamów z domyślnym połączeniem, zobacz YAML po przesunięciu etapu przez admina.

## Testy automatyczne
    python -m pytest -q                      # 22 testy API i logiki
    cd tests/e2e && npm i && cd ../.. && NODE_PATH=tests/e2e/node_modules ./tests/e2e/run.sh   # 27 kroków przez interfejs (jsdom)
Test e2e uruchamia prawdziwy serwer i atrapę urządzenia. Nie zastępuje testu w prawdziwej przeglądarce na telefonie.
