#!/usr/bin/env python3
"""Repeat sample location and color bars 10 times, five seconds per screen."""

import argparse
import sys
import time

from PIL import Image, ImageDraw

from displaygeo import HEIGHT, WIDTH, generateLCDImage, write_fb


class SampleLocation:
    def __init__(self, county, abbr, grid):
        self.county = county
        self.county_abbr = abbr
        self.grid = grid

    def get_county_grid(self):
        return self.county, self.county_abbr, self.grid


def color_test_image():
    image = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(image)
    colors = ["white", "yellow", "cyan", "lime", "magenta", "red", "blue", "black"]
    for index, color in enumerate(colors):
        left = index * WIDTH // len(colors)
        right = (index + 1) * WIDTH // len(colors) - 1
        draw.rectangle((left, 0, right, HEIGHT - 81), fill=color)
        draw.text((left + 4, 12), color.upper(),
                  fill="black" if index < 4 else "white")
    for x in range(WIDTH):
        level = round(x * 255 / (WIDTH - 1))
        draw.line((x, HEIGHT - 80, x, HEIGHT - 1), fill=(level, level, level))
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--framebuffer", default="/dev/fb0", help="LCD device (default: /dev/fb0)")
    parser.add_argument("--county", default="Fauquier", help="Sample county/city")
    parser.add_argument("--abbr", default="FAU", help="Sample county abbreviation")
    parser.add_argument("--grid", default="FM18aw", help="Sample grid square")
    parser.add_argument("--flip-screen", action="store_true", help="Rotate the LCD image 180 degrees")
    args = parser.parse_args()

    try:
        location = SampleLocation(args.county, args.abbr, args.grid)
        for cycle in range(1, 11):
            print(f"Cycle {cycle}/10: showing sample location for 5 seconds.", flush=True)
            write_fb(generateLCDImage(location), args.framebuffer, flip_screen=args.flip_screen)
            time.sleep(5)
            print(f"Cycle {cycle}/10: showing color bars and grayscale ramp for 5 seconds.", flush=True)
            write_fb(color_test_image(), args.framebuffer, flip_screen=args.flip_screen)
            time.sleep(5)
        write_fb(Image.new("RGB", (WIDTH, HEIGHT), "black"), args.framebuffer,
                 flip_screen=args.flip_screen)
        print("LCD test complete; screen cleared.")
    except OSError as error:
        print(f"LCD test failed: {error}. Check the framebuffer path and run with sudo.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
