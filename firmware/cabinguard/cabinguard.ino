// CabinGuard firmware - Arduino Uno. Libraries: "DHT sensor library" (Adafruit), Servo.
// Serial 9600. Out: T,H,D,OCC,LOCK,FAN,SRV,BUZ,THR,MODE,SIL every 1 s.  In: SET:<t>, VENT, SILENCE, AUTO.
#include <DHT.h>
#include <Servo.h>

const uint8_t TRIG = 2, ECHO = 3, DHTPIN = 4, SERVO_PIN = 9, BUZZER = 8, RELAY = 7,
              LED_G = 10, LED_R = 11, LOCK_BTN = 12;
const bool RELAY_ACTIVE_LOW = false;   // set true for active-low relay boards
const float OCC_CM = 12.0;
const unsigned long ALERT_DELAY_MS = 10000;

DHT dht(DHTPIN, DHT11);
Servo windowServo;

float threshold = 32.0;
bool locked = false, cooling = false, silenced = false, ventMode = false;
unsigned long lockedSince = 0, lastTelemetry = 0, lastBtn = 0;
bool lastBtnState = HIGH;
String cmdBuf;

float readDistance() {
  float v[3];
  for (int i = 0; i < 3; i++) {
    digitalWrite(TRIG, LOW); delayMicroseconds(2);
    digitalWrite(TRIG, HIGH); delayMicroseconds(10);
    digitalWrite(TRIG, LOW);
    unsigned long us = pulseIn(ECHO, HIGH, 30000UL);
    v[i] = us ? us * 0.0343 / 2.0 : 99.0;
    delay(10);
  }
  if (v[0] > v[1]) { float t = v[0]; v[0] = v[1]; v[1] = t; }
  if (v[1] > v[2]) { float t = v[1]; v[1] = v[2]; v[2] = t; }
  if (v[0] > v[1]) { float t = v[0]; v[0] = v[1]; v[1] = t; }
  return v[1];  // median of 3 rejects echo glitches
}

void applyCommand(String c) {
  c.trim(); c.toUpperCase();
  if (c.startsWith("SET:")) threshold = constrain(c.substring(4).toFloat(), 20, 45);
  else if (c == "VENT") ventMode = true;
  else if (c == "SILENCE") silenced = true;
  else if (c == "AUTO") { ventMode = false; silenced = false; }
}

void setup() {
  Serial.begin(9600);
  pinMode(TRIG, OUTPUT); pinMode(ECHO, INPUT);
  pinMode(BUZZER, OUTPUT); pinMode(RELAY, OUTPUT);
  pinMode(LED_G, OUTPUT); pinMode(LED_R, OUTPUT);
  pinMode(LOCK_BTN, INPUT_PULLUP);
  digitalWrite(RELAY, RELAY_ACTIVE_LOW ? HIGH : LOW);
  windowServo.attach(SERVO_PIN); windowServo.write(0);
  dht.begin();
}

void sendTelemetry(float t, float h, float d, bool occ, bool fan, int srv, int buz) {
  Serial.print(F("T:")); if (isnan(t)) Serial.print(F("NaN")); else Serial.print(t, 1);
  Serial.print(F(",H:")); if (isnan(h)) Serial.print(F("NaN")); else Serial.print(h, 0);
  Serial.print(F(",D:")); Serial.print(d, 1);
  Serial.print(F(",OCC:")); Serial.print(occ);
  Serial.print(F(",LOCK:")); Serial.print(locked);
  Serial.print(F(",FAN:")); Serial.print(fan);
  Serial.print(F(",SRV:")); Serial.print(srv);
  Serial.print(F(",BUZ:")); Serial.print(buz);
  Serial.print(F(",THR:")); Serial.print(threshold, 1);
  Serial.print(F(",MODE:")); Serial.print(ventMode ? F("VENT") : F("AUTO"));
  Serial.print(F(",SIL:")); Serial.println(silenced);
}

void loop() {
  // lock button toggles locked state (debounced)
  bool b = digitalRead(LOCK_BTN);
  if (b == LOW && lastBtnState == HIGH && millis() - lastBtn > 50) {
    locked = !locked; lastBtn = millis();
    if (locked) lockedSince = millis();
  }
  lastBtnState = b;

  // serial commands
  while (Serial.available()) {
    char ch = Serial.read();
    if (ch == '\n') { applyCommand(cmdBuf); cmdBuf = ""; lastTelemetry = 0; }  // echo state now
    else if (cmdBuf.length() < 24) cmdBuf += ch;
  }

  if (millis() - lastTelemetry < 1000) return;
  lastTelemetry = millis();

  float t = dht.readTemperature(), h = dht.readHumidity(), d = readDistance();
  bool occ = d < OCC_CM;
  bool alert = occ && locked && (millis() - lockedSince > ALERT_DELAY_MS);
  bool fault = isnan(t);

  if (!alert) { cooling = false; silenced = false; }
  else if (!fault) {
    if (t >= threshold) cooling = true;
    else if (t < threshold - 1.0) cooling = false;   // hysteresis
  }
  bool vent = cooling || fault || ventMode;           // fail-safe: NaN presumes hot
  int buz = (!alert || silenced) ? 0 : ((cooling || fault) ? 2 : 1);

  digitalWrite(RELAY, (vent != RELAY_ACTIVE_LOW) ? HIGH : LOW);
  windowServo.write(vent ? 90 : 0);
  digitalWrite(LED_R, alert); digitalWrite(LED_G, !alert);
  if (buz == 2) digitalWrite(BUZZER, HIGH);
  else if (buz == 1) { digitalWrite(BUZZER, HIGH); delay(150); digitalWrite(BUZZER, LOW); }
  else digitalWrite(BUZZER, LOW);

  sendTelemetry(t, h, d, occ, vent, vent ? 90 : 0, buz);
}
