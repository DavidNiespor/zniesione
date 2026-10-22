"""Katalog sterowników sprzedawanych przez operatora. Tylko te modele można zamówić."""
MODELS = {
    "tr4": dict(name="LilyGO T-Relay: ESP32, 4 przekaźniki", channels=4, board="esp32dev",
                tunnels=("wg",), relays=[21, 19, 18, 5]),
    "trs3": dict(name="LilyGO T-RelayS3: ESP32-S3, 6 przekaźników, DIN", channels=6,
                 board="esp32-s3-devkitc-1", tunnels=("wg", "ts"), sr=dict(data=7, clock=5, latch=6)),
    "wsp": dict(name="Waveshare ESP32-S3-POE-ETH-8DI-8RO-C", channels=8, board="esp32-s3-devkitc-1",
                tunnels=("wg", "ts"), eth=True),
    "shp": dict(name="Shelly Pro 4PM", channels=4, tunnels=("mqtt",), shelly=True),
}
KINDS = ("light", "door_open", "door_close", "vent", "heater", "water_heater",
         "valve", "pump", "feeder", "other")
COOL, HEAT = {"vent"}, {"heater", "water_heater"}


def default_channels(model):
    n = MODELS[model]["channels"]
    out = [("ch1", "Światło", "light"), ("ch2", "Drzwi: otwórz", "door_open"),
           ("ch3", "Drzwi: zamknij", "door_close")]
    return out[:n] + [(f"ch{i}", f"Przekaźnik {i}", "other") for i in range(4, n + 1)]
