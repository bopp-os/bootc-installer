#!/usr/bin/env python3
"""Generate distinctive branding and prove both real COSMIC pages rendered it."""

import json
import sys
import tempfile
from pathlib import Path

from PIL import Image

COLOR = (19, 185, 125)
NAME = "Example Remix"


def prepare(directory):
    directory.mkdir(parents=True, exist_ok=True)
    logo = directory / "logo with spaces #1.png"
    Image.new("RGB", (120, 60), COLOR).save(logo)
    fixture = Path(__file__).resolve().parents[3] / "shared/branding/fixtures/fork-branding.json"
    branding = json.loads(fixture.read_text())
    assert branding["name"] == NAME
    branding["logo"] = str(logo.resolve())
    (directory / "branding.json").write_text(json.dumps(branding))


def check(directory):
    texts = json.loads((directory / "texts.json").read_text())
    for filename, page in [("01-welcome.png", "welcome"), ("06-done.png", "done")]:
        with Image.open(directory / filename) as image:
            count = sum(
                all(abs(value - expected) <= 2 for value, expected in zip(pixel, COLOR))
                for pixel in image.convert("RGB").getdata()
            )
        # A 64x32 logo has 2048 coloured pixels; leave room for scaling and
        # antialiasing, but reject an absent icon or a stray accent pixel.
        assert count >= 400, f"{page}: custom logo missing ({count} matching pixels)"
        assert NAME in texts[page], f"{page}: custom name missing"
        print(f"{page}: custom logo has {count} pixels and name is present")


def self_test():
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        prepare(directory)
        (directory / "texts.json").write_text(json.dumps({"welcome": NAME, "done": NAME}))
        for filename in ["01-welcome.png", "06-done.png"]:
            Image.new("RGB", (64, 32), COLOR).save(directory / filename)
        check(directory)
        for filename, page in [("01-welcome.png", "welcome"), ("06-done.png", "done")]:
            Image.new("RGB", (64, 32), "white").save(directory / filename)
            try:
                check(directory)
            except AssertionError as error:
                assert str(error).startswith(page + ": custom logo missing"), str(error)
            else:
                raise AssertionError("pixel gate accepted a missing " + page + " logo")
            Image.new("RGB", (64, 32), COLOR).save(directory / filename)
        (directory / "texts.json").write_text(json.dumps({"welcome": "Wrong OS", "done": NAME}))
        try:
            check(directory)
        except AssertionError as error:
            assert "custom name missing" in str(error)
        else:
            raise AssertionError("name gate accepted foreign branding")
    print("branding capture gate rejects missing logos and foreign names")


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        self_test()
    else:
        {"prepare": prepare, "check": check}[sys.argv[1]](Path(sys.argv[2]))
