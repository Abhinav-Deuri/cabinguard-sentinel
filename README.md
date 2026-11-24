# CabinGuard Sentinel

Child heatstroke car alarm: Arduino Uno + Streamlit parent dashboard (DBT7745 Sensors and Microcontrollers, CA4).

Detects a child in a locked car (HC-SR04 + lock button), alerts with LED/buzzer, and opens the window and runs a fan when the cabin (DHT11) passes a threshold. Fail-safe on sensor NaN.

## Run
```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\streamlit run app.py
```
Starts in Viva Demo Simulator mode. For hardware, flash `firmware/cabinguard/cabinguard.ino`, pick "Live Serial" and the port marked `[ARDUINO]`.

Serial protocol (9600 baud): board sends `T,H,D,OCC,LOCK,FAN,SRV,BUZ,THR,MODE,SIL` every second; PC sends `SET:<t>`, `VENT`, `SILENCE`, `AUTO`.
