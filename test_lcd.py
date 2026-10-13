#!/usr/bin/env python3
"""Test the LCD with sample screens or display a static callsign."""

import argparse
import sys
import time

from PIL import Image, ImageColor, ImageDraw

from displaygeo import FONT_BOLD, HEIGHT, WIDTH, generateLCDImage, load_font, write_fb


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


def callsign_image(callsign, color):
    image = Image.new("RGB", (WIDTH, HEIGHT), "black")
    draw = ImageDraw.Draw(image)
    for size in range(HEIGHT, 0, -1):
        font = load_font(FONT_BOLD, size)
        left, top, right, bottom = draw.textbbox((0, 0), callsign, font=font)
        if right - left <= WIDTH - 20 and bottom - top <= HEIGHT - 20:
            break
    draw.text(((WIDTH - (right - left)) // 2 - left,
               (HEIGHT - (bottom - top)) // 2 - top),
              callsign, font=font, fill=color)
    return image


def parse_color(value):
    try:
        return ImageColor.getrgb(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "Use a color name (such as yellow) or a hex color (such as #00ff00)."
        ) from error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--framebuffer", default="/dev/fb1", help="LCD device (default: /dev/fb1)")
    parser.add_argument("--county", default="Fauquier", help="Sample county/city")
    parser.add_argument("--abbr", default="FAU", help="Sample county abbreviation")
    parser.add_argument("--grid", default="FM18aw", help="Sample grid square")
    parser.add_argument("--flip-screen", action="store_true", help="Rotate the LCD image 180 degrees")
    parser.add_argument("--show_call", "--show-call", metavar="CALLSIGN",
                        help="Display a static callsign and exit, leaving it on the LCD")
    parser.add_argument("--color", type=parse_color, default="white",
                        help="Callsign color name or hex value (default: white)")
    args = parser.parse_args()
    if args.show_call is not None:
        args.show_call = args.show_call.strip()
        if not args.show_call or any(character.isspace() for character in args.show_call):
            parser.error("--show_call requires a nonempty callsign without whitespace")

    try:
        if args.show_call is not None:
            write_fb(callsign_image(args.show_call, args.color), args.framebuffer,
                     flip_screen=args.flip_screen)
            print(f"Displaying {args.show_call}; callsign left on the LCD.")
            return 0
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
