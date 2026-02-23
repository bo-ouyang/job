import time
import threading
import random

class SnowflakeGenerator:
    """
    Snowflake ID Generator
    - 1 bit: unused (sign bit)
    - 41 bits: timestamp (milliseconds)
    - 5 bits: datacenter_id
    - 5 bits: worker_id
    - 12 bits: sequence
    """
    def __init__(self, datacenter_id=1, worker_id=1):
        self.datacenter_id = datacenter_id
        self.worker_id = worker_id
        self.sequence = 0
        
        self.epoch = 1640995200000  # 2022-01-01 00:00:00 UTC
        
        self.worker_id_bits = 5
        self.datacenter_id_bits = 5
        self.sequence_bits = 12
        
        self.max_worker_id = -1 ^ (-1 << self.worker_id_bits)
        self.max_datacenter_id = -1 ^ (-1 << self.datacenter_id_bits)
        self.sequence_mask = -1 ^ (-1 << self.sequence_bits)
        
        self.worker_id_shift = self.sequence_bits
        self.datacenter_id_shift = self.sequence_bits + self.worker_id_bits
        self.timestamp_left_shift = self.sequence_bits + self.worker_id_bits + self.datacenter_id_bits
        
        self.last_timestamp = -1
        self.lock = threading.Lock()

        if self.worker_id > self.max_worker_id or self.worker_id < 0:
            raise ValueError(f"Worker ID can't be greater than {self.max_worker_id} or less than 0")
        if self.datacenter_id > self.max_datacenter_id or self.datacenter_id < 0:
            raise ValueError(f"Datacenter ID can't be greater than {self.max_datacenter_id} or less than 0")

    def _current_timestamp(self):
        return int(time.time() * 1000)

    def next_id(self):
        with self.lock:
            timestamp = self._current_timestamp()

            if timestamp < self.last_timestamp:
                raise Exception(f"Clock moved backwards. Refusing to generate id for {self.last_timestamp - timestamp} milliseconds")

            if self.last_timestamp == timestamp:
                self.sequence = (self.sequence + 1) & self.sequence_mask
                if self.sequence == 0:
                    # Sequence exhausted, wait for next millisecond
                    while timestamp <= self.last_timestamp:
                        timestamp = self._current_timestamp()
            else:
                self.sequence = 0

            self.last_timestamp = timestamp

            new_id = ((timestamp - self.epoch) << self.timestamp_left_shift) | \
                     (self.datacenter_id << self.datacenter_id_shift) | \
                     (self.worker_id << self.worker_id_shift) | \
                     self.sequence
            return new_id

# Global instance
# In a distributed system, you'd want to configure worker_id/datacenter_id from env vars
_generator = SnowflakeGenerator(datacenter_id=1, worker_id=1)

def generate_id():
    return _generator.next_id()
