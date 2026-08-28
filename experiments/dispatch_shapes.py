"""How much does the shape of an address dispatch cost?

`Bus.read` runs on every instruction fetch, so the way it picks a branch is one
of the few places in this project where Python's constant factors are visible.
This measures the four shapes the codebase could plausibly use, over the
timer's four addresses.

Run with:

    uv run python experiments/dispatch_shapes.py

Sample run (Python 3.12.13, best of 7 x 2M calls, ns per call):

                                 if       elif      match       dict
    first branch (0xFF04)     40.1n      26.2n      26.4n      45.3n
    last branch  (0xFF07)     40.6n      40.9n      38.9n      45.4n

Four things it showed:

1. Independent `if`s are flat, because they always run every comparison. They
   tie on the last branch and lose on every other one.
2. `match` on constant values is NOT a jump table. It gets slower on later
   branches exactly like `if`/`elif` does, which is the tell: CPython compiles
   it to a comparison chain. It happens to edge out `elif` by a nanosecond or
   two, which is not a reason to choose it. Readability is.
3. A `dict` of handlers is flat, and the slowest of the four. Constant-time
   lookup wins on paper and loses here: hashing the key and calling through a
   function reference costs more than one to four integer comparisons. The
   crossover is further out than four branches.
4. What you pay for is the number of comparisons before you hit, which is why
   ordering branches by frequency (as `Bus.read` does) buys more than any
   choice of syntax.

What it does not show: whether any of this matters. Only 4 of the 65536
addresses reach the timer, and a ROM writes TAC a handful of times in its whole
life. Measure `Bus.read` before optimising anything here.
"""

import timeit

DIVIDER = 0xFF04
TIMER_COUNTER = 0xFF05
TIMER_MODULO = 0xFF06
TIMER_CONTROL = 0xFF07

CALLS = 2_000_000
# Take the best of several runs rather than the average: the slow runs measure
# whatever else the machine was doing, not the code.
REPEATS = 7

SETUP = """
DIVIDER = 0xFF04
TIMER_COUNTER = 0xFF05
TIMER_MODULO = 0xFF06
TIMER_CONTROL = 0xFF07


class Device:
    __slots__ = ("counter", "tac", "tima", "tma")

    def __init__(self):
        self.counter = self.tima = self.tma = self.tac = 0

    def write_if(self, address, value):
        # Four independent comparisons, every time.
        if address == DIVIDER:
            self.counter = 0
        if address == TIMER_COUNTER:
            self.tima = value
        if address == TIMER_MODULO:
            self.tma = value
        if address == TIMER_CONTROL:
            self.tac = value

    def write_elif(self, address, value):
        # Mutually exclusive alternatives, said in the syntax.
        if address == DIVIDER:
            self.counter = 0
        elif address == TIMER_COUNTER:
            self.tima = value
        elif address == TIMER_MODULO:
            self.tma = value
        elif address == TIMER_CONTROL:
            self.tac = value

    def write_match(self, address, value):
        # The shape Bus.read uses.
        match address:
            case 0xFF04:
                self.counter = 0
            case 0xFF05:
                self.tima = value
            case 0xFF06:
                self.tma = value
            case 0xFF07:
                self.tac = value

    def write_dict(self, address, value):
        # Constant-time lookup on paper. Note what the hash and the bound-method
        # call cost in practice.
        setter = _SETTERS.get(address)
        if setter is not None:
            setter(self, value)


def _set_counter(device, _value):
    device.counter = 0


def _set_tima(device, value):
    device.tima = value


def _set_tma(device, value):
    device.tma = value


def _set_tac(device, value):
    device.tac = value


_SETTERS = {
    DIVIDER: _set_counter,
    TIMER_COUNTER: _set_tima,
    TIMER_MODULO: _set_tma,
    TIMER_CONTROL: _set_tac,
}

device = Device()
"""

SHAPES = ("write_if", "write_elif", "write_match", "write_dict")
CASES = {
    "first branch (0xFF04)": DIVIDER,
    "last branch  (0xFF07)": TIMER_CONTROL,
}


def nanoseconds_per_call(shape: str, address: int) -> float:
    seconds = timeit.repeat(
        f"device.{shape}({address}, 0x42)",
        setup=SETUP,
        number=CALLS,
        repeat=REPEATS,
    )
    return min(seconds) / CALLS * 1e9


def main() -> None:
    header = "".join(f"{shape.removeprefix('write_'):>11}" for shape in SHAPES)
    print(f"{'':24}{header}")

    for label, address in CASES.items():
        row = "".join(
            f"{nanoseconds_per_call(shape, address):10.1f}n" for shape in SHAPES
        )
        print(f"{label:24}{row}")


if __name__ == "__main__":
    main()
