# zniesione

Portal dla rolników z kurnikami: sprzedaż jaj od rolnika (zamówienia jednorazowe i cykliczne, potwierdza rolnik),
sterowanie kurnikiem (światło, drzwi, wentylacja, grzałki, elektrozawory), harmonogramy, termostat, odczyty
temperatury oraz panel administratora z przypisywaniem sterowników do farm.

## Uruchomienie
    pip install -r requirements-dev.txt && python -m pytest -q
    export SECRET_KEY=$(python -c "import secrets;print(secrets.token_hex(32))")
    flask --app zniesione create-admin
    RUN_SCHEDULER=1 flask --app zniesione run        # lub: docker compose up --build

`/` serwuje makietę interfejsu (`static/prototype.html`, dane w localStorage, jeszcze niepodpięta do API).

## Co jest zrobione i przetestowane
Konta (rolnik, admin), publiczne wyszukiwanie farm i zamówienia, potwierdzanie zamówień przez rolnika, katalog
tylko sprzedawanych modeli, rejestracja i przypisywanie sterowników przez admina, alokacja adresów VPN, generator
YAML dla ESPHome (T-Relay, T-RelayS3, Waveshare, Shelly: instrukcja MQTT), odczyty z kluczem API urządzenia,
sterowanie z blokadą drzwi, harmonogramy (także przez północ), termostat z histerezą, silnik porównujący stan
(nadrabia utracone minuty, ponawia nieudane polecenia, oznacza urządzenia offline), ochrona CSRF nagłówkiem.

## Czego jeszcze nie ma (świadomie)
- Interfejs podpięty do API (jest tylko makieta).
- Harmonogram drzwi (wymaga krańcówek i czasu pracy silnika).
- Shelly przez MQTT (sterowanie zwraca błąd "niezaimplementowane").
- Serwer WireGuard, ESPHome Device Builder i OTA: konfiguracja po stronie serwera.
- Ścieżkę REST `/switch/<id>/turn_on` zweryfikuj na sprzęcie z web_server ESPHome (`services.send_http`).
- Limit prób logowania, reset hasła, e-mail/SMS do rolnika, płatności online.
- Integracja z e-kurnik (`stan_magazynu`): tu zapas to prosty licznik `farms.stock`.
