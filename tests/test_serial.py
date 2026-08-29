from gameboy.memory import Bus
from gameboy.memory_map import SERIAL_CONTROL, SERIAL_DATA
from gameboy.serial import Serial

TRANSFER = 0x81  # start, using our own clock


def send(device: Serial, byte: int) -> None:
    """What a ROM does: load the byte, then start the transfer."""
    device.write(SERIAL_DATA, byte)
    device.write(SERIAL_CONTROL, TRANSFER)


def test_a_transfer_appends_the_byte_to_the_output() -> None:
    device = Serial()

    send(device, ord("H"))
    send(device, ord("i"))

    assert device.text == "Hi"


def test_writing_sb_alone_transfers_nothing() -> None:
    device = Serial()

    device.write(SERIAL_DATA, ord("H"))

    assert device.output == b""


def test_a_control_write_without_the_start_bit_transfers_nothing() -> None:
    device = Serial()
    device.write(SERIAL_DATA, ord("H"))

    device.write(SERIAL_CONTROL, 0x01)  # our clock, but no start

    assert device.output == b""


def test_the_start_bit_is_clear_once_the_transfer_is_done() -> None:
    # The ROM polls this bit to know it can send the next byte. Leaving it set
    # is how a serial stub hangs a test ROM on its first character.
    device = Serial()

    send(device, ord("H"))

    assert device.read(SERIAL_CONTROL) & 0x80 == 0


def test_the_control_register_reads_its_unused_bits_as_one() -> None:
    device = Serial()

    send(device, ord("H"))

    assert device.read(SERIAL_CONTROL) == 0x7F  # 0x01 kept, bits 6-1 unwired


def test_sb_reads_back_the_high_line_and_not_what_was_sent() -> None:
    # A DMG with no cable attached clocks in a floating line, eight times.
    device = Serial()

    send(device, ord("H"))

    assert device.read(SERIAL_DATA) == 0xFF


def test_the_bus_routes_the_serial_registers(bus: Bus) -> None:
    bus.write(SERIAL_DATA, ord("O"))
    bus.write(SERIAL_CONTROL, TRANSFER)
    bus.write(SERIAL_DATA, ord("K"))
    bus.write(SERIAL_CONTROL, TRANSFER)

    assert bus.serial.text == "OK"


def test_the_serial_registers_do_not_fall_through_to_the_io_array(bus: Bus) -> None:
    # 0xFF01 and 0xFF02 sit inside the IO range, so their case only ever runs if
    # it comes first in the match.
    bus.write(SERIAL_DATA, ord("O"))

    assert bus.io[SERIAL_DATA - 0xFF00] == 0x00
    assert bus.serial.data == ord("O")
