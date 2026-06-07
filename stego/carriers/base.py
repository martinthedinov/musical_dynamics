"""Carrier interface. A carrier exposes its embeddable bit-planes as a flat slot array."""

class Carrier:
    #: file extensions this carrier handles (lower-case, with dot)
    EXTS = frozenset()

    def get_bits(self, n_lsb):
        """Return a uint8 array of the carrier's low n_lsb bit-planes.
           Slot s maps to unit s//n_lsb, bit-plane s%n_lsb."""
        raise NotImplementedError

    def set_bits(self, bits, n_lsb):
        """Write the slot array back into the carrier's bit-planes (stealthy on plane 0)."""
        raise NotImplementedError

    def write(self, path):
        """Serialize the (modified) carrier to `path`."""
        raise NotImplementedError
