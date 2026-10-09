import time
from machine import Pin, ADC

# Configuration Constants
Q_CAPACITY = 16
CRITICAL_VOLTAGE_MV = 4250  # Overvoltage safety limit
SHUTDOWN_PIN = 15           # Hardware fail-safe gate interlock
MONITORED_PINS = [2, 4, 5, 12, 14]

class TelemetryQueue:
    def __init__(self, capacity):
        self.capacity = capacity
        self.buffer = [{'pins': 0, 'voltage': 0} for _ in range(capacity)]
        self.head = 0
        self.tail = 0
        self.size = 0

    def enqueue(self, item):
        if self.size < self.capacity:
            self.buffer[self.tail] = item
            self.tail = (self.tail + 1) % self.capacity
            self.size += 1
        else:
            # FIFO overflow: overwrite tail and advance head (drop oldest)
            self.buffer[self.tail] = item
            self.tail = (self.tail + 1) % self.capacity
            self.head = (self.head + 1) % self.capacity

    def get_chronological_items(self):
        """Extracts items from oldest to newest for pattern matching."""
        ordered = []
        for i in range(self.size):
            idx = (self.head + i) % self.capacity
            ordered.append(self.buffer[idx])
        return ordered

class SupervisoryROM:
    def __init__(self):
        # Initialize hardware interlock pin (HIGH = normal operation, LOW = isolation)
        self.gate_shutdown = Pin(SHUTDOWN_PIN, Pin.OUT)
        self.gate_shutdown.value(1)
        
        # Initialize the FIFO Telemetry Q
        self.telemetry_q = TelemetryQueue(Q_CAPACITY)
        
        # Setup ADC for voltage telemetry monitoring
        self.adc = ADC(Pin(34))
        self.adc.atten(ADC.ATTN_11DB)
        
        # Setup GPIO observation pins
        self.pins = [Pin(p, Pin.IN) for p in MONITORED_PINS]

    def capture_frame(self):
        pin_mask = 0
        for idx, p in enumerate(self.pins):
            if p.value():
                pin_mask |= (1 << idx)
                
        voltage_mv = int(self.adc.read() * 3.3 * 1000 / 4095)
        return {'pins': pin_mask, 'voltage': voltage_mv}

    def validate_behavior(self):
        history = self.telemetry_q.get_chronological_items()
        
        # Check absolute safety limits on the most recent frame
        if history and history[-1]['voltage'] > CRITICAL_VOLTAGE_MV:
            return False
            
        # Reconstruct temporal transition pattern from the Q
        # In production, match chronological sequence against immutable golden profile
        return True

    def run(self):
        print("Supervisory ROM active. Initializing FIFO telemetry Q monitoring...")
        while True:
            frame = self.capture_frame()
            self.telemetry_q.enqueue(frame)
            
            if not self.validate_behavior():
                self.trigger_emergency_shutdown()
                
            time.sleep_ms(10)  # 100Hz supervisory tick rate

    def trigger_emergency_shutdown(self):
        print("CRITICAL: Q telemetry evaluation failed! Isolating hardware gates.")
        self.gate_shutdown.value(0)
        while True:
            time.sleep(1)

if __name__ == "__main__":
    supervisor = SupervisoryROM()
    supervisor.run()
