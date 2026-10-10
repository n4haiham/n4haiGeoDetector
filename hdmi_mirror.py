"""Scale the LCD image into a Linux truecolor HDMI framebuffer."""

import ctypes
import fcntl
import mmap
import sys

from PIL import Image


class Bitfield(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint32) for name in ('offset', 'length', 'msb_right')]


class VariableInfo(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint32) for name in (
        'xres', 'yres', 'xres_virtual', 'yres_virtual', 'xoffset', 'yoffset',
        'bits_per_pixel', 'grayscale')]
    _fields_ += [(name, Bitfield) for name in ('red', 'green', 'blue', 'transp')]
    _fields_ += [('remaining', ctypes.c_uint32 * 20)]


class FixedInfo(ctypes.Structure):
    _fields_ = [('id', ctypes.c_char * 16), ('smem_start', ctypes.c_ulong),
                ('smem_len', ctypes.c_uint32), ('type', ctypes.c_uint32),
                ('type_aux', ctypes.c_uint32), ('visual', ctypes.c_uint32),
                ('xpanstep', ctypes.c_uint16), ('ypanstep', ctypes.c_uint16),
                ('ywrapstep', ctypes.c_uint16), ('line_length', ctypes.c_uint32),
                ('mmio_start', ctypes.c_ulong), ('mmio_len', ctypes.c_uint32),
                ('accel', ctypes.c_uint32), ('capabilities', ctypes.c_uint16),
                ('reserved', ctypes.c_uint16 * 2)]


def encode_pixels(image, info):
    fields = (info.red, info.green, info.blue)
    layout = [(field.offset, field.length) for field in fields]
    if sys.byteorder == 'little' and info.bits_per_pixel in (24, 32):
        mode = {((16, 8), (8, 8), (0, 8)): 'BGR',
                ((0, 8), (8, 8), (16, 8)): 'RGB'}.get(tuple(layout))
        if mode:
            if info.bits_per_pixel == 32:
                mode += 'A' if info.transp.length else 'X'
            return image.convert('RGBA' if info.transp.length else 'RGB').tobytes('raw', mode)
    size = info.bits_per_pixel // 8
    alpha = ((1 << info.transp.length) - 1) << info.transp.offset
    output = bytearray()
    for pixel in image.convert('RGB').getdata():
        value = alpha
        for channel, field in zip(pixel, fields):
            value |= (channel >> (8 - field.length)) << field.offset
        output.extend(value.to_bytes(size, sys.byteorder))
    return bytes(output)


class HDMIMirror:
    def __init__(self, device):
        self.file = open(device, 'r+b', buffering=0)
        try:
            self.info = VariableInfo()
            self.fixed = FixedInfo()
            fcntl.ioctl(self.file.fileno(), 0x4600, self.info)  # FBIOGET_VSCREENINFO
            fcntl.ioctl(self.file.fileno(), 0x4602, self.fixed)  # FBIOGET_FSCREENINFO
            fields = (self.info.red, self.info.green, self.info.blue, self.info.transp)
            if (self.fixed.type != 0 or self.fixed.visual != 2 or self.info.grayscale
                    or self.info.bits_per_pixel not in (16, 24, 32)
                    or any(f.msb_right or f.length > 8 or f.offset + f.length > self.info.bits_per_pixel for f in fields)
                    or any(f.length == 0 for f in fields[:3])):
                raise ValueError('HDMI requires a packed 16/24/32-bit truecolor framebuffer')
            if not self.info.xres or not self.info.yres:
                raise ValueError('HDMI framebuffer has no active resolution')
            row_end = (self.info.xoffset + self.info.xres) * (self.info.bits_per_pixel // 8)
            end = (self.info.yoffset + self.info.yres - 1) * self.fixed.line_length + row_end
            if row_end > self.fixed.line_length or end > self.fixed.smem_len:
                raise ValueError('HDMI framebuffer dimensions exceed its available memory')
            self.memory = mmap.mmap(self.file.fileno(), self.fixed.smem_len)
        except Exception:
            self.file.close()
            raise

    def write(self, image):
        info = self.info
        scale = min(info.xres / image.width, info.yres / image.height)
        resized = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))),
                               Image.Resampling.NEAREST)
        canvas = Image.new('RGB', (info.xres, info.yres), 'black')
        canvas.paste(resized, ((info.xres - resized.width) // 2, (info.yres - resized.height) // 2))
        pixels = encode_pixels(canvas, info)
        row_size = info.xres * (info.bits_per_pixel // 8)
        for y in range(info.yres):
            start = (y + info.yoffset) * self.fixed.line_length + info.xoffset * (info.bits_per_pixel // 8)
            self.memory[start:start + row_size] = pixels[y * row_size:(y + 1) * row_size]

    def close(self):
        self.memory.close()
        self.file.close()
