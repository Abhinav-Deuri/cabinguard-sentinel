"""Software model of the CabinGuard Arduino: same logic as firmware, plus a scripted viva scenario."""
import random

AMBIENT = 27.0
CYCLE = 135  # seconds per scripted loop


class Board:
    def __init__(self):
        self.t = 0
        self.temp = AMBIENT
        self.hum = 48.0
        self.thr = 32.0
        self.mode = "AUTO"
        self.sil = False
        self.cooling = False
        self.locked_since = None
        self.heater = False
        self.dht_fault = False
        self.dist = 25.0
        self.lock = 0
        self.fan = 0
        self.srv = 0
        self.buz = 0
        # manual overrides (sliders in the UI); None = follow script
        self.manual = False
        self.m_temp = AMBIENT
        self.m_hum = 48.0
        self.m_dist = 25.0
        self.m_lock = 0

    # --- scripted scenario -------------------------------------------
    def _script(self, s):
        self.dist = 6.0 if 5 <= s < 90 else 25.0
        self.lock = 1 if 8 <= s < 85 else 0
        self.heater = 24 <= s < 45
        self.dht_fault = 105 <= s < 111

    def _physics(self):
        if self.heater:
            self.temp += 0.7
        else:
            rate = 0.5 if self.fan else 0.15
            self.temp += max(-rate, AMBIENT - self.temp)
        self.hum = max(25.0, min(80.0, self.hum + (50 - self.temp) * 0.01 + random.uniform(-0.4, 0.4)))

    # --- same control logic as cabinguard.ino -------------------------
    def _control(self):
        occ = self.dist < 12
        if self.lock and self.locked_since is None:
            self.locked_since = self.t
        if not self.lock:
            self.locked_since = None
        alert = occ and self.lock and self.locked_since is not None and self.t - self.locked_since > 10
        fault = self.dht_fault
        if not alert:
            self.cooling = False
            self.sil = False
        elif not fault:
            if self.temp >= self.thr:
                self.cooling = True
            elif self.temp < self.thr - 1:
                self.cooling = False
        vent = self.cooling or fault or self.mode == "VENT"
        self.fan, self.srv = (1, 90) if vent else (0, 0)
        if self.sil or not alert:
            self.buz = 0
        else:
            self.buz = 2 if (self.cooling or fault) else 1
        return occ

    def step(self):
        self.t += 1
        if self.manual:
            self.temp, self.hum, self.dist, self.lock = self.m_temp, self.m_hum, self.m_dist, self.m_lock
            self.dht_fault = False
        else:
            self._script(self.t % CYCLE)
            self._physics()
        occ = self._control()
        return self._packet(occ)

    def _packet(self, occ):
        d = self.dist + random.uniform(-0.3, 0.3)
        if not self.manual and random.random() < 0.02:
            d += random.choice([-1, 1]) * random.uniform(8, 14)  # echo glitch
        d = max(1.0, d)
        T = "NaN" if self.dht_fault else f"{self.temp + random.uniform(-0.1, 0.1):.1f}"
        return (f"T:{T},H:{self.hum:.0f},D:{d:.1f},OCC:{int(occ)},LOCK:{self.lock},FAN:{self.fan},"
                f"SRV:{self.srv},BUZ:{self.buz},THR:{self.thr:g},MODE:{self.mode},SIL:{int(self.sil)}")

    def command(self, cmd):
        if cmd.startswith("SET:"):
            self.thr = max(20.0, min(45.0, float(cmd[4:])))
        elif cmd == "VENT":
            self.mode = "VENT"
        elif cmd == "SILENCE":
            self.sil = True
        elif cmd == "AUTO":
            self.mode, self.sil = "AUTO", False
        occ = self._control()
        return self._packet(occ)
