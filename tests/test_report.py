from fakes import frame

from gyromote.report import BUTTONS, button_name, decode


def test_decode_reads_every_field_big_endian_and_signed():
    r = decode(frame(0xFE, button=0x808B, wheel=-1, gyro=(-1500, 200, 32767), accel=(4100, -3800, -32768)))
    assert (r.tick, r.gyro, r.accel, r.button, r.wheel) == (0xFE, (-1500, 200, 32767), (4100, -3800, -32768), 0x808B, -1)


def test_button_names_cover_the_remote_and_name_unknown_codes_by_hex():
    assert len(BUTTONS) == 23 and len(set(BUTTONS.values())) == 23
    assert button_name(0x8044) == "wheel" and button_name(0x803E) == "0x803E"
