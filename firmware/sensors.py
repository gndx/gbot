"""Board sensors: IMU, chip temperature, and supply voltage.

The QMI8658 uses I2C1 on GP6/GP7 at address 0x6B. Chip temperature comes from
RP2040 ADC4; GP29 reads the board voltage divider.

Reset the QMI8658 before configuring it. In the original board bring-up,
skipping reset allowed register reads/writes but left STATUS0 at zero after
the first sample. Readiness therefore requires a fresh accelerometer sample."""

from machine import ADC, I2C, Pin
import math
import time

_ADDR = 0x6B
_WHO_AM_I = 0x00
_CTRL1 = 0x02
_CTRL2 = 0x03
_CTRL5 = 0x06
_CTRL7 = 0x08
_STATUS0 = 0x2E
_TEMP_L = 0x33
_AX_L = 0x35
_RESET = 0x60
_RESET_DONE = 0x4D     # Reset complete when the value reaches 0x80.

_ACC_SCALE = 4096.0    # LSB per g at the +/-8 g range.


class Sensors:
    def __init__(self):
        self.imu_ok = False
        try:
            self.i2c = I2C(1, sda=Pin(6), scl=Pin(7), freq=400_000)
            if self.i2c.readfrom_mem(_ADDR, _WHO_AM_I, 1)[0] == 0x05:
                self.i2c.writeto_mem(_ADDR, _RESET, b"\xb0")
                time.sleep_ms(20)
                if self.i2c.readfrom_mem(_ADDR, _RESET_DONE, 1)[0] == 0x80:
                    # Disable the accelerometer while configuring it;
                    # enable it last, as required by the datasheet.
                    self.i2c.writeto_mem(_ADDR, _CTRL7, b"\x00")
                    self.i2c.writeto_mem(_ADDR, _CTRL1, b"\x60")  # auto-increment
                    self.i2c.writeto_mem(_ADDR, _CTRL2, b"\x26")  # +/-8 g, 125 Hz
                    self.i2c.writeto_mem(_ADDR, _CTRL5, b"\x00")  # no filter
                    self.i2c.writeto_mem(_ADDR, _CTRL7, b"\x01")
                    time.sleep_ms(20)
                    # A register response alone is insufficient; require a fresh sample.
                    self.imu_ok = bool(
                        self.i2c.readfrom_mem(_ADDR, _STATUS0, 1)[0] & 0x01)
        except Exception:
            pass  # The rest of the monitor continues when no IMU is available.

        self.adc_temp = ADC(4)
        try:
            self.adc_vbat = ADC(Pin(29))
        except Exception:
            self.adc_vbat = None

        self._buf = bytearray(6)

    # ---- accelerometer ----

    def accel(self):
        """Return (x, y, z) in g, or (0, 0, 0) when the IMU is unavailable."""
        if not self.imu_ok:
            return (0.0, 0.0, 0.0)
        try:
            self.i2c.readfrom_mem_into(_ADDR, _AX_L, self._buf)
        except Exception:
            return (0.0, 0.0, 0.0)
        b = self._buf
        out = []
        for i in (0, 2, 4):
            v = b[i] | (b[i + 1] << 8)
            if v & 0x8000:
                v -= 65536
            out.append(v / _ACC_SCALE)
        return tuple(out)

    def magnitude(self):
        x, y, z = self.accel()
        return math.sqrt(x * x + y * y + z * z)

    def imu_temp(self):
        if not self.imu_ok:
            return None
        try:
            raw = self.i2c.readfrom_mem(_ADDR, _TEMP_L, 2)
        except Exception:
            return None
        v = raw[0] | (raw[1] << 8)
        if v & 0x8000:
            v -= 65536
        return v / 256.0

    # ---- other sensors ----

    def chip_temp(self):
        """Return the RP2040 internal sensor temperature in degrees Celsius."""
        volts = self.adc_temp.read_u16() * 3.3 / 65535
        return 27.0 - (volts - 0.706) / 0.001721

    def voltage(self):
        """Return the GP29 voltage, correcting for the board divider factor of two."""
        if self.adc_vbat is None:
            return None
        return self.adc_vbat.read_u16() * 3.3 / 65535 * 2
