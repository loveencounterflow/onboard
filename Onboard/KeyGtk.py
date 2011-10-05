# -*- coding: UTF-8 -*-

import time
from math import floor, pi, sin, cos, sqrt

import cairo
from gi.repository import Gdk, Pango, PangoCairo, GdkPixbuf


from Onboard.KeyCommon import *
from Onboard.utils import brighten, roundrect_curve

### Logging ###
import logging
_logger = logging.getLogger("KeyGTK")
###############

### Config Singleton ###
from Onboard.Config import Config
config = Config()
########################

BASE_FONTDESCRIPTION_SIZE = 10000000
PangoUnscale = 1.0 / Pango.SCALE

class Key(KeyCommon):
    pango_layout = None

    def __init__(self):
        KeyCommon.__init__(self)

    def get_best_font_size(self, key_context, context):
        """
        Get the maximum font possible that would not cause the label to
        overflow the boundaries of the key.
        """

        raise NotImplementedException()

    @staticmethod
    def get_pango_layout(context, text, font_size):
        if Key.pango_layout is None: # work around memory leak (gnome #599730)
            # use PangoCairo.create_layout once it works with gi (pango >= 1.29.1)
            Key.pango_layout = Pango.Layout(context=Gdk.pango_context_get())
            #Key.pango_layout = PangoCairo.create_layout(context)
        layout = Key.pango_layout

        Key.prepare_pango_layout(layout, text, font_size)
        #context.update_layout(layout)
        return layout

    @staticmethod
    def prepare_pango_layout(layout, text, font_size):
        if text is None:
            text = ""
        layout.set_text(text, -1)
        font_description = Pango.FontDescription(config.theme.key_label_font)
        font_description.set_size(font_size)
        layout.set_font_description(font_description)


class DwellProgress(object):

    # dwell time in seconds
    dwell_delay = 4

    # time of dwell start
    dwell_start_time = None

    def is_dwelling(self):
        return not self.dwell_start_time is None

    def is_done(self):
        return time.time() > self.dwell_start_time + self.dwell_delay

    def start_dwelling(self):
        self.dwell_start_time = time.time()

    def stop_dwelling(self):
        self.dwell_start_time = None

    def draw(self, context):
        if self.is_dwelling():
            rect = self.get_rect().deflate(0.5)
            rect = self.context.log_to_canvas_rect(rect)
            xc, yc = rect.get_center()

            radius = min(rect.w, rect.h) / 2.0

            alpha0 = -pi / 2.0
            k = (time.time() - self.dwell_start_time) / self.dwell_delay
            k = min(k, 1.0)
            alpha = k * pi * 2.0

            context.move_to(xc, yc)
            context.arc(xc, yc, radius, alpha0, alpha0 + alpha)
            context.close_path()

            rgba = self.dwell_progress_rgba
            context.set_source_rgba(*rgba)
            context.fill_preserve()

            context.set_source_rgba(0,0,0,1)
            context.set_line_width(0)
            context.stroke()


class RectKey(Key, RectKeyCommon, DwellProgress):
    def __init__(self, id="", location=(0,0), geometry=(0,0)):
        Key.__init__(self)
        RectKeyCommon.__init__(self, id, location, geometry)

    def is_key(self):
        """ Returns true if self is a key. """
        return True

    def draw_font(self, context = None):
        # Skip cairo errors when drawing labels with font size 0
        # This may happen for hidden keys and keys with bad size groups.
        if self.font_size == 0:
            return

        layout = self.get_pango_layout(context, self.get_label(),
                                                self.font_size)
        log_rect = self.get_label_rect()
        src_size = layout.get_size()
        src_size = (src_size[0] * PangoUnscale, src_size[1] * PangoUnscale)

        for x, y, rgba in self._label_iterations(src_size, log_rect):
            context.move_to(x, y)
            context.set_source_rgba(*rgba)
            PangoCairo.show_layout(context, layout)

    def draw_image(self, context):
        """ Draws the keys optional image. """
        if not self.image_filename:
            return

        rect = self.context.log_to_canvas_rect(self.get_label_rect())
        if rect.w < 1 or rect.h < 1:
            return

        pixbuf = self.get_image(rect.w, rect.h)
        if not pixbuf:
            return
 
        log_rect = self.get_label_rect()
        src_size = (pixbuf.get_width(), pixbuf.get_height())

        for x, y, rgba in self._label_iterations(src_size, log_rect):
            # Draw the image in the themes label color.
            # Only the alpha channel of the image is used.
            Gdk.cairo_set_source_pixbuf(context, pixbuf, x, y)
            pattern = context.get_source()
            context.rectangle(*rect)
            context.set_source_rgba(*rgba)
            context.mask(pattern)
            context.new_path()

    def _label_iterations(self, src_size, log_rect):
        canvas_rect = self.context.log_to_canvas_rect(log_rect)
        xoffset, yoffset = self.align_label(
                 (src_size[0], src_size[1]),
                 (canvas_rect.w, canvas_rect.h))

        stroke_gradient   = config.theme.key_stroke_gradient / 100.0
        if config.theme.key_style != "flat" and stroke_gradient:
            fill = self.get_fill_color()
            d = 0.5  # fake emboss distance
            d = max(src_size[1] * 0.02, 0.0)

            # shadow
            alpha = self.get_gradient_angle()
            xo = d * cos(alpha)
            yo = d * sin(alpha)
            rgba = brighten(-stroke_gradient*.4, *fill) # darker
            x, y = self.context.log_to_canvas((log_rect.x, log_rect.y))
            yield xoffset + x + xo, yoffset + y + yo, rgba

            # highlight
            alpha = pi + self.get_gradient_angle()
            xo = d * cos(alpha)
            yo = d * sin(alpha)
            rgba = brighten(+stroke_gradient*.4, *fill) # brighter
            x,y = self.context.log_to_canvas((log_rect.x, log_rect.y))
            yield xoffset + x + xo, yoffset + y + yo, rgba


        rgba = self.get_label_color()
        yield canvas_rect.x + xoffset, canvas_rect.y + yoffset, rgba


    def draw(self, context):

        key_context = self.context
        rect = key_context.log_to_canvas_rect(self.get_rect())
        t    = key_context.scale_log_to_canvas((1.0, 1.0))
        line_width = (t[0] + t[1]) / 2.0
        fill = self.get_fill_color()

        if config.theme.key_style == "flat":
            # old style key from before theming was added
            self.build_rect_path(context, rect)
            context.set_source_rgba(*fill)
            context.fill_preserve()
            context.set_source_rgba(*self.stroke_rgba)
            context.set_line_width(line_width)
            context.stroke()

        elif config.theme.key_style == "gradient":
            self.draw_gradient_key(context, rect, fill, line_width)

        elif config.theme.key_style == "dish":
            self.draw_dish_key(context, rect, fill, line_width)

        DwellProgress.draw(self, context)


    def draw_dish_key(self, context, rect, fill, line_width):
        # simple gradients for fill and stroke
        fill_gradient   = config.theme.key_fill_gradient / 100.0
        stroke_gradient = config.theme.key_stroke_gradient / 100.0
        alpha = self.get_gradient_angle()
        # unfinished

    def draw_gradient_key(self, context, rect, fill, line_width):
        # simple gradients for fill and stroke
        fill_gradient   = config.theme.key_fill_gradient / 100.0
        stroke_gradient = config.theme.key_stroke_gradient / 100.0
        alpha = self.get_gradient_angle()

        self.build_rect_path(context, rect)
        gline = self.get_gradient_line(rect, alpha)

        # fill
        if fill_gradient:
            pat = cairo.LinearGradient (*gline)
            rgba = brighten(+fill_gradient*.5, *fill)
            pat.add_color_stop_rgba(0, *rgba)
            rgba = brighten(-fill_gradient*.5, *fill)
            pat.add_color_stop_rgba(1, *rgba)
            context.set_source (pat)
        else: # take gradient from color scheme (not implemented)
            context.set_source_rgba(*fill)

        context.fill_preserve()

        # stroke
        if stroke_gradient:
            stroke = fill
            pat = cairo.LinearGradient (*gline)
            rgba = brighten(+stroke_gradient*.5, *stroke)
            pat.add_color_stop_rgba(0, *rgba)
            rgba = brighten(-stroke_gradient*.5, *stroke)
            pat.add_color_stop_rgba(1, *rgba)
            context.set_source (pat)
        else:
            context.set_source_rgba(*self.stroke_rgba)

        context.set_line_width(line_width)
        context.stroke()

    def build_rect_path(self, context, rect):
        roundness = config.theme.roundrect_radius
        if roundness:
            roundrect_curve(context, rect, roundness)
        else:
            context.rectangle(*rect)

    def get_gradient_line(self, rect, alpha):
        # Find gradient start and end points.
        # Line end points follow the largest extent of the rotated rectangle.
        # The gradient reaches across the entire key.
        x0, y0, w, h = rect.x, rect.y, rect.w, rect.h
        a = w / 2.0
        b = h / 2.0
        coords = [(-a, -b), (a, -b), (a, b), (-a, b)]
        vx = [c[0]*cos(alpha)-c[1]*sin(alpha) for c in coords]
        dx = max(vx) - min(vx)
        r = dx / 2.0
        return (r * cos(alpha) + x0 + a,
                r * sin(alpha) + y0 + b,
               -r * cos(alpha) + x0 + a,
               -r * sin(alpha) + y0 + b)

    def get_gradient_angle(self):
        return -pi/2.0 - 2*pi * config.theme.key_gradient_direction / 360.0

    def get_best_font_size(self, context):
        """
        Get the maximum font size that would not cause the label to
        overflow the boundaries of the key.
        """
        layout = Pango.Layout(context)
        self.prepare_pango_layout(layout, self.get_label(),
                                          BASE_FONTDESCRIPTION_SIZE)

        # In Pango units
        label_width, label_height = layout.get_size()
        if label_width == 0: label_width = 1

        size_for_maximum_width = self.context.scale_log_to_canvas_x(
                (self.geometry[0] - config.LABEL_MARGIN[0]*2) \
                * Pango.SCALE \
                * BASE_FONTDESCRIPTION_SIZE) \
            / label_width

        size_for_maximum_height = self.context.scale_log_to_canvas_y(
                (self.geometry[1] - config.LABEL_MARGIN[1]*2) \
                * Pango.SCALE \
                * BASE_FONTDESCRIPTION_SIZE) \
            / label_height

        if size_for_maximum_width < size_for_maximum_height:
            return int(size_for_maximum_width)
        else:
            return int(size_for_maximum_height)

    def get_image(self, width, height):
        """
        Get the cached image pixbuf object. Load it if necessary.
        Width and height in canvas coordinates.
        """
        if not self.image_filename:
            return

        pixbuf = self.image_pixbuf
        if not pixbuf or \
           pixbuf.get_width()  != width or \
           pixbuf.get_height() != height:

            self.image_pixbuf = None

            filename = config.get_image_filename(self.image_filename)
            if filename:
                self.image_pixbuf = GdkPixbuf.Pixbuf. \
                               new_from_file_at_size(filename, width, height)
                p = self.image_pixbuf
        return self.image_pixbuf


