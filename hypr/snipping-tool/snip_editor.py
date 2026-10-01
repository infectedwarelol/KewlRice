import datetime
import math
import os

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_foreign("cairo")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk

from clipboard import copy_image

PEN_COLORS = ["#000000", "#ffffff", "#e81123", "#ffb900", "#16c60c", "#0078d7", "#e3008c", "#886ce4"]
HIGHLIGHTER_COLORS = ["#fff100", "#16c60c", "#00b7c3", "#e3008c", "#ff8c00", "#886ce4"]
INK_TOOLS = {
    "pen": {"label": "Ballpoint pen", "icon": "draw-brush", "color": "#e81123", "size": 4, "alpha": 1.0, "colors": PEN_COLORS},
    "pencil": {"label": "Pencil", "icon": "draw-freehand", "color": "#000000", "size": 2, "alpha": 0.75, "colors": PEN_COLORS},
    "highlighter": {"label": "Highlighter", "icon": "draw-highlight", "color": "#fff100", "size": 18, "alpha": 0.4, "colors": HIGHLIGHTER_COLORS},
}
ERASER_RADIUS = 10
BLUR_STRENGTH = 14


def hex_to_rgb(color):
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) / 255 for i in (0, 2, 4))


def draw_stroke(cr, stroke):
    points = stroke["points"]
    cr.set_source_rgba(*hex_to_rgb(stroke["color"]), stroke["alpha"])
    cr.set_line_width(stroke["size"])
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    cr.set_line_cap(cairo.LINE_CAP_SQUARE if stroke["tool"] == "highlighter" else cairo.LINE_CAP_ROUND)
    cr.move_to(*points[0])
    if len(points) == 1:
        cr.line_to(points[0][0] + 0.01, points[0][1])
    for point in points[1:]:
        cr.line_to(*point)
    cr.stroke()


def blurred_region(image, rect):
    x, y, w, h = (int(round(v)) for v in rect)
    x, y = max(0, x), max(0, y)
    w, h = min(w, image.get_width() - x), min(h, image.get_height() - y)
    if w < 2 or h < 2:
        return None, 0, 0
    region = image.new_subpixbuf(x, y, w, h)
    small = region.scale_simple(max(1, w // BLUR_STRENGTH), max(1, h // BLUR_STRENGTH), GdkPixbuf.InterpType.HYPER)
    return small.scale_simple(w, h, GdkPixbuf.InterpType.BILINEAR), x, y


def draw_item(cr, item, image):
    if item["tool"] != "blur":
        draw_stroke(cr, item)
        return
    blurred, x, y = blurred_region(image, item["rect"])
    if blurred:
        Gdk.cairo_set_source_pixbuf(cr, blurred, x, y)
        cr.rectangle(x, y, blurred.get_width(), blurred.get_height())
        cr.fill()


def normalized(x1, y1, x2, y2):
    return min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1)


def compose(image, items):
    width, height = image.get_width(), image.get_height()
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    cr = cairo.Context(surface)
    Gdk.cairo_set_source_pixbuf(cr, image, 0, 0)
    cr.paint()
    for item in items:
        draw_item(cr, item, image)
    return Gdk.pixbuf_get_from_surface(surface, 0, 0, width, height)


def icon_button(icon, tooltip, toggle=False):
    button = Gtk.ToggleButton() if toggle else Gtk.Button()
    button.set_image(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.LARGE_TOOLBAR))
    button.set_tooltip_text(tooltip)
    return button


class SnipEditor(Gtk.Window):
    def __init__(self, on_new):
        super().__init__(title="Snip & Sketch")
        self.get_style_context().add_class("snip-editor")
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)
        self.set_default_size(1100, 720)
        self.on_new = on_new
        self.image = None
        self.strokes = []
        self.history = []
        self.future = []
        self.tool = "pen"
        self.settings = {name: dict(values) for name, values in INK_TOOLS.items()}
        self.drawing = None
        self.erasing = False
        self.erase_saved = False
        self.crop_rect = None
        self.crop_start = None
        self.zoom = 1.0
        self.tool_buttons = {}
        self.updating_tools = False

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(root)
        root.pack_start(self.build_toolbar(), False, False, 0)

        layers = Gtk.Overlay()
        root.pack_start(layers, True, True, 0)
        self.stack = Gtk.Stack()
        layers.add(self.stack)
        self.stack.add_named(self.build_empty_page(), "empty")
        self.stack.add_named(self.build_canvas(), "canvas")

        self.toast_label = Gtk.Label()
        self.toast_label.get_style_context().add_class("snip-toast")
        self.toast = Gtk.Revealer()
        self.toast.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)
        self.toast.set_halign(Gtk.Align.CENTER)
        self.toast.set_valign(Gtk.Align.END)
        self.toast.add(self.toast_label)
        layers.add_overlay(self.toast)
        self.toast_timer = None

        self.context_menu = Gtk.Menu()
        for label, action in [("Copy", self.copy), ("Save as", self.save_as)]:
            item = Gtk.MenuItem(label=label)
            item.connect("activate", lambda _item, run=action: run())
            self.context_menu.append(item)
        self.context_menu.show_all()

        self.connect("key-press-event", self.on_key)
        self.show_all()
        self.set_crop_controls(False)
        self.update_buttons()

    def build_toolbar(self):
        bar = Gtk.Box(spacing=2)
        bar.get_style_context().add_class("snip-toolbar")

        new_menu = Gtk.MenuButton()
        new_box = Gtk.Box(spacing=6)
        new_box.pack_start(Gtk.Image.new_from_icon_name("document-new", Gtk.IconSize.LARGE_TOOLBAR), False, False, 0)
        new_box.pack_start(Gtk.Label(label="New"), False, False, 0)
        new_box.pack_start(Gtk.Image.new_from_icon_name("pan-down-symbolic", Gtk.IconSize.BUTTON), False, False, 0)
        new_menu.add(new_box)
        popover = Gtk.Popover()
        options = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        options.set_margin_top(6)
        options.set_margin_bottom(6)
        options.set_margin_start(6)
        options.set_margin_end(6)
        for label, action in [
            ("Snip now", lambda: self.request_new(0)),
            ("Snip in 3 seconds", lambda: self.request_new(3)),
            ("Snip in 10 seconds", lambda: self.request_new(10)),
            ("Open file", self.open_file),
        ]:
            item = Gtk.Button(label=label)
            item.get_child().set_halign(Gtk.Align.START)
            item.connect("clicked", lambda _b, run=action, pop=popover: (pop.popdown(), run()))
            options.pack_start(item, False, False, 0)
        options.show_all()
        popover.add(options)
        new_menu.set_popover(popover)
        new_menu.set_tooltip_text("New snip (Ctrl+N)")
        bar.pack_start(new_menu, False, False, 0)

        center = Gtk.Box(spacing=2)
        for name, values in INK_TOOLS.items():
            button = icon_button(values["icon"], values["label"], toggle=True)
            button.connect("toggled", self.on_tool_toggled, name)
            button.connect("button-press-event", self.on_tool_pressed, name)
            self.tool_buttons[name] = button
            center.pack_start(button, False, False, 0)
        eraser = icon_button("draw-eraser", "Eraser", toggle=True)
        eraser.connect("toggled", self.on_tool_toggled, "eraser")
        self.tool_buttons["eraser"] = eraser
        center.pack_start(eraser, False, False, 0)
        blur = icon_button("blurimage", "Blur", toggle=True)
        blur.connect("toggled", self.on_tool_toggled, "blur")
        self.tool_buttons["blur"] = blur
        center.pack_start(blur, False, False, 0)
        center.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)
        self.crop_button = icon_button("transform-crop", "Image crop", toggle=True)
        self.crop_button.connect("toggled", self.on_crop_toggled)
        center.pack_start(self.crop_button, False, False, 0)
        self.crop_apply = icon_button("dialog-ok-apply", "Apply crop (Enter)")
        self.crop_apply.connect("clicked", lambda _: self.apply_crop())
        center.pack_start(self.crop_apply, False, False, 0)
        self.crop_cancel = icon_button("dialog-cancel", "Cancel crop (Esc)")
        self.crop_cancel.connect("clicked", lambda _: self.crop_button.set_active(False))
        center.pack_start(self.crop_cancel, False, False, 0)
        center.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)
        self.undo_button = icon_button("edit-undo", "Undo (Ctrl+Z)")
        self.undo_button.connect("clicked", lambda _: self.undo())
        center.pack_start(self.undo_button, False, False, 0)
        self.redo_button = icon_button("edit-redo", "Redo (Ctrl+Y)")
        self.redo_button.connect("clicked", lambda _: self.redo())
        center.pack_start(self.redo_button, False, False, 0)
        bar.set_center_widget(center)

        self.save_button = icon_button("document-save-as", "Save as (Ctrl+S)")
        self.save_button.connect("clicked", lambda _: self.save_as())
        bar.pack_end(self.save_button, False, False, 0)
        self.copy_button = icon_button("edit-copy", "Copy (Ctrl+C)")
        self.copy_button.connect("clicked", lambda _: self.copy())
        bar.pack_end(self.copy_button, False, False, 0)

        self.tool_buttons["pen"].set_active(True)
        return bar

    def build_empty_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_valign(Gtk.Align.CENTER)
        title = Gtk.Label(label="Snip & Sketch")
        title.get_style_context().add_class("snip-empty-title")
        hint = Gtk.Label(label="Take a snip with the New button or Super + Shift + S,\nthen draw on it, crop it and copy it.")
        hint.set_justify(Gtk.Justification.CENTER)
        hint.get_style_context().add_class("snip-empty-hint")
        box.pack_start(title, False, False, 0)
        box.pack_start(hint, False, False, 0)
        return box

    def build_canvas(self):
        self.scroller = Gtk.ScrolledWindow()
        self.scroller.connect("size-allocate", self.on_viewport_resized)
        holder = Gtk.Box()
        holder.get_style_context().add_class("snip-canvas-holder")
        holder.set_halign(Gtk.Align.CENTER)
        holder.set_valign(Gtk.Align.CENTER)
        self.canvas = Gtk.DrawingArea()
        self.canvas.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
        )
        self.canvas.connect("draw", self.on_draw)
        self.canvas.connect("button-press-event", self.on_press)
        self.canvas.connect("motion-notify-event", self.on_motion)
        self.canvas.connect("button-release-event", self.on_release)
        holder.pack_start(self.canvas, False, False, 0)
        self.scroller.add(holder)
        return self.scroller

    def load(self, pixbuf):
        self.image = pixbuf
        self.strokes = []
        self.history = []
        self.future = []
        self.crop_button.set_active(False)
        self.stack.set_visible_child_name("canvas")
        self.fit_zoom()
        self.update_buttons()

    def fit_zoom(self):
        if not self.image:
            return
        allocation = self.scroller.get_allocation()
        available_w = max(200, allocation.width - 40) if allocation.width > 1 else 1040
        available_h = max(200, allocation.height - 40) if allocation.height > 1 else 620
        self.zoom = min(1.0, available_w / self.image.get_width(), available_h / self.image.get_height())
        self.canvas.set_size_request(int(self.image.get_width() * self.zoom), int(self.image.get_height() * self.zoom))
        self.canvas.queue_draw()

    def on_viewport_resized(self, _widget, _allocation):
        GLib.idle_add(self.fit_zoom)

    def to_image(self, x, y):
        return x / self.zoom, y / self.zoom

    def on_draw(self, _widget, cr):
        if not self.image:
            return False
        cr.scale(self.zoom, self.zoom)
        Gdk.cairo_set_source_pixbuf(cr, self.image, 0, 0)
        cr.paint()
        for item in self.strokes + ([self.drawing] if self.drawing else []):
            draw_item(cr, item, self.image)
        if self.drawing and self.drawing["tool"] == "blur":
            cr.rectangle(*self.drawing["rect"])
            cr.set_source_rgba(0.9, 0.93, 0.95, 0.9)
            cr.set_line_width(1.5 / self.zoom)
            cr.stroke()
        if self.crop_button.get_active() and self.crop_rect:
            x, y, w, h = self.crop_rect
            cr.rectangle(0, 0, self.image.get_width(), self.image.get_height())
            cr.rectangle(x, y + h, w, -h)
            cr.set_source_rgba(0, 0, 0, 0.5)
            cr.fill()
            cr.rectangle(x, y, w, h)
            cr.set_source_rgba(0.9, 0.93, 0.95, 0.95)
            cr.set_line_width(2 / self.zoom)
            cr.stroke()
        return False

    def on_tool_pressed(self, button, event, name):
        if event.button == 1 and button.get_active() and self.tool == name:
            self.show_tool_options(button, name)
            return True
        return False

    def on_tool_toggled(self, button, name):
        if self.updating_tools:
            return
        self.updating_tools = True
        if button.get_active():
            self.tool = name
            self.crop_button.set_active(False)
            for other, other_button in self.tool_buttons.items():
                if other != name:
                    other_button.set_active(False)
        elif self.tool == name:
            button.set_active(True)
        self.updating_tools = False

    def show_tool_options(self, button, name):
        settings = self.settings[name]
        popover = Gtk.Popover(relative_to=button)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for side in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{side}")(10)
        grid = Gtk.FlowBox()
        grid.set_max_children_per_line(4)
        grid.set_selection_mode(Gtk.SelectionMode.NONE)
        swatches = []
        for color in settings["colors"]:
            swatch = Gtk.ToggleButton()
            swatch.get_style_context().add_class("color-swatch")
            dot = Gtk.DrawingArea()
            dot.set_size_request(22, 22)
            dot.connect("draw", self.draw_swatch, color)
            swatch.add(dot)
            swatch.set_active(color == settings["color"])
            swatch.connect("clicked", self.pick_color, name, color, swatches)
            swatches.append(swatch)
            grid.add(swatch)
        box.pack_start(grid, False, False, 0)
        size_label = Gtk.Label(label="Size")
        size_label.set_halign(Gtk.Align.START)
        box.pack_start(size_label, False, False, 0)
        size = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 40, 1)
        size.set_value(settings["size"])
        size.set_draw_value(False)
        size.set_size_request(180, -1)
        size.connect("value-changed", lambda scale: settings.__setitem__("size", int(scale.get_value())))
        box.pack_start(size, False, False, 0)
        box.show_all()
        popover.add(box)
        popover.popup()

    def draw_swatch(self, widget, cr, color):
        width, height = widget.get_allocated_width(), widget.get_allocated_height()
        cr.arc(width / 2, height / 2, min(width, height) / 2 - 1, 0, 2 * math.pi)
        cr.set_source_rgb(*hex_to_rgb(color))
        cr.fill_preserve()
        cr.set_source_rgba(1, 1, 1, 0.35)
        cr.set_line_width(1)
        cr.stroke()
        return False

    def pick_color(self, button, name, color, swatches):
        self.settings[name]["color"] = color
        for swatch in swatches:
            if swatch is not button and swatch.get_active():
                swatch.set_active(False)
        if not button.get_active():
            button.set_active(True)

    def on_crop_toggled(self, button):
        self.set_crop_controls(button.get_active())
        if button.get_active() and self.image:
            self.crop_rect = (0, 0, self.image.get_width(), self.image.get_height())
        else:
            self.crop_rect = None
        self.canvas.queue_draw()

    def set_crop_controls(self, active):
        self.crop_apply.set_visible(active)
        self.crop_cancel.set_visible(active)

    def remember(self):
        self.history.append((self.image, list(self.strokes)))
        self.future = []

    def undo(self):
        if not self.history:
            return
        self.future.append((self.image, list(self.strokes)))
        self.image, self.strokes = self.history.pop()
        self.after_change()

    def redo(self):
        if not self.future:
            return
        self.history.append((self.image, list(self.strokes)))
        self.image, self.strokes = self.future.pop()
        self.after_change()

    def after_change(self):
        self.crop_button.set_active(False)
        self.fit_zoom()
        self.update_buttons()

    def update_buttons(self):
        has_image = self.image is not None
        for widget in [self.copy_button, self.save_button, self.crop_button]:
            widget.set_sensitive(has_image)
        self.undo_button.set_sensitive(bool(self.history))
        self.redo_button.set_sensitive(bool(self.future))

    def on_press(self, _widget, event):
        if not self.image:
            return False
        if event.button == 3:
            self.context_menu.popup_at_pointer(event)
            return True
        if event.button != 1:
            return False
        point = self.to_image(event.x, event.y)
        if self.crop_button.get_active():
            self.crop_start = point
            self.crop_rect = (point[0], point[1], 0, 0)
        elif self.tool == "eraser":
            self.erasing = True
            self.erase_at(point)
        elif self.tool == "blur":
            self.drawing = {"tool": "blur", "start": point, "rect": (point[0], point[1], 0, 0)}
        else:
            settings = self.settings[self.tool]
            self.drawing = {
                "tool": self.tool,
                "color": settings["color"],
                "size": settings["size"],
                "alpha": settings["alpha"],
                "points": [point],
            }
        self.canvas.queue_draw()
        return True

    def on_motion(self, _widget, event):
        if not self.image:
            return False
        point = self.to_image(event.x, event.y)
        if self.crop_button.get_active() and self.crop_start:
            x1, y1 = self.crop_start
            x2 = max(0, min(self.image.get_width(), point[0]))
            y2 = max(0, min(self.image.get_height(), point[1]))
            self.crop_rect = (min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))
        elif self.erasing:
            self.erase_at(point)
        elif self.drawing and self.drawing["tool"] == "blur":
            x = max(0, min(self.image.get_width(), point[0]))
            y = max(0, min(self.image.get_height(), point[1]))
            self.drawing["rect"] = normalized(*self.drawing["start"], x, y)
        elif self.drawing:
            self.drawing["points"].append(point)
        else:
            return False
        self.canvas.queue_draw()
        return True

    def on_release(self, _widget, event):
        if event.button != 1:
            return False
        if self.drawing:
            if self.drawing["tool"] == "blur":
                self.drawing = {"tool": "blur", "rect": self.drawing["rect"]}
            if self.drawing["tool"] != "blur" or min(self.drawing["rect"][2:]) >= 2:
                self.remember()
                self.strokes.append(self.drawing)
            self.drawing = None
            self.update_buttons()
        self.erasing = False
        self.erase_saved = False
        self.crop_start = None
        self.canvas.queue_draw()
        return True

    def erase_at(self, point):
        reach = ERASER_RADIUS / self.zoom
        keep = [s for s in self.strokes if not self.touches(s, point, reach)]
        if len(keep) != len(self.strokes):
            if not self.erase_saved:
                self.remember()
                self.erase_saved = True
            self.strokes = keep
            self.update_buttons()

    def touches(self, item, point, reach):
        if item["tool"] == "blur":
            x, y, w, h = item["rect"]
            return x - reach <= point[0] <= x + w + reach and y - reach <= point[1] <= y + h + reach
        return any(math.hypot(px - point[0], py - point[1]) <= reach + item["size"] / 2 for px, py in item["points"])

    def apply_crop(self):
        if not self.image or not self.crop_rect:
            return
        x, y, w, h = (int(round(v)) for v in self.crop_rect)
        if w < 2 or h < 2:
            return
        self.remember()
        self.image = self.image.new_subpixbuf(x, y, w, h).copy()
        self.strokes = [
            dict(s, rect=(s["rect"][0] - x, s["rect"][1] - y, s["rect"][2], s["rect"][3]))
            if s["tool"] == "blur"
            else dict(s, points=[(px - x, py - y) for px, py in s["points"]])
            for s in self.strokes
        ]
        self.after_change()

    def rendered(self):
        return compose(self.image, self.strokes)

    def copy(self):
        if not self.image:
            return
        copy_image(self.rendered())
        self.show_toast("Copied to clipboard")

    def save_as(self):
        if not self.image:
            return
        dialog = Gtk.FileChooserDialog(title="Save as", parent=self, action=Gtk.FileChooserAction.SAVE)
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Save", Gtk.ResponseType.ACCEPT)
        dialog.set_do_overwrite_confirmation(True)
        pictures = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES) or os.path.expanduser("~")
        if os.path.isdir(pictures):
            dialog.set_current_folder(pictures)
        dialog.set_current_name(datetime.datetime.now().strftime("Snip %Y-%m-%d %H%M%S.png"))
        if dialog.run() == Gtk.ResponseType.ACCEPT:
            path = dialog.get_filename()
            kind = "jpeg" if path.lower().endswith((".jpg", ".jpeg")) else "png"
            if kind == "png" and not path.lower().endswith(".png"):
                path += ".png"
            self.rendered().savev(path, kind, [], [])
            self.show_toast("Saved")
        dialog.destroy()

    def open_file(self):
        dialog = Gtk.FileChooserDialog(title="Open file", parent=self, action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Open", Gtk.ResponseType.ACCEPT)
        images = Gtk.FileFilter()
        images.set_name("Images")
        images.add_pixbuf_formats()
        dialog.add_filter(images)
        if dialog.run() == Gtk.ResponseType.ACCEPT:
            self.load(GdkPixbuf.Pixbuf.new_from_file(dialog.get_filename()))
        dialog.destroy()

    def request_new(self, delay):
        self.on_new(delay)

    def show_toast(self, text):
        self.toast_label.set_text(text)
        self.toast.set_reveal_child(True)
        if self.toast_timer:
            GLib.source_remove(self.toast_timer)
        self.toast_timer = GLib.timeout_add(1800, self.hide_toast)

    def hide_toast(self):
        self.toast.set_reveal_child(False)
        self.toast_timer = None
        return False

    def on_key(self, _widget, event):
        ctrl = event.state & Gdk.ModifierType.CONTROL_MASK
        key = Gdk.keyval_to_lower(event.keyval)
        if ctrl and key == Gdk.KEY_z:
            self.undo()
        elif ctrl and key == Gdk.KEY_y:
            self.redo()
        elif ctrl and key == Gdk.KEY_c:
            self.copy()
        elif ctrl and key == Gdk.KEY_s:
            self.save_as()
        elif ctrl and key == Gdk.KEY_n:
            self.request_new(0)
        elif ctrl and key == Gdk.KEY_o:
            self.open_file()
        elif key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and self.crop_button.get_active():
            self.apply_crop()
        elif key == Gdk.KEY_Escape and self.crop_button.get_active():
            self.crop_button.set_active(False)
        else:
            return False
        return True
