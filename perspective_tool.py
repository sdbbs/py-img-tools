#!/usr/bin/env python3

import os
import sys
import argparse
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk, ImageOps, ImageEnhance

APP_TITLE = "Perspective Tool"
__version__ = 1
HSEPARATOR_WIDTH = 4

HELP_TEXT = f"""
{APP_TITLE} (Cross-Platform)
------------------------------
APPLICATION WORKFLOW:
  1. LOAD: Select a PNG or JPG reference image (or pass as positional argument).
  2. LEFT VIEWER: Shows the image with a Curves filter and a 4-corner perspective box.
     - Click a corner to select it (blue).
     - Shift+Click a corner to drag it.
     - Mouse over a corner to highlight it (yellow, or green if Shift is held).
     - Use arrow keys to nudge the selected corner by 1 pixel.
  3. RIGHT VIEWER: Shows a live preview of the perspective-corrected image (no filter).
  4. CURVES EDITOR: Press 'e' to open a graphical Curves editor (like GIMP).
  5. EXECUTE: Press ENTER to save the corrected image.
     - A dialog suggests a filename like '[original]_fix01.[ext]' (auto-increments if exists).
     - The equivalent ImageMagick command is printed to stdout.
  6. FINISH: The corrected image is saved, and the app exits.

CONTROLS:
  Left-Click Drag       : Pan image (in either viewer) or drag corner (left viewer, Shift+Click)
  Ctrl + Left-Click Drag: Sync pan to both viewers (absolute)
  Ctrl + Mouse Wheel    : Sync zoom to both viewers (absolute)
  Mouse Wheel           : Zoom in/out (in either viewer)
  Arrow Keys            : Nudge selected corner by 1 pixel
  r                     : Reset zoom/pan for the last selected viewer
  e                     : Open Curves editor dialog
  c                     : Copy Curves + Perspective settings to clipboard
  v                     : Paste settings from clipboard
  Enter                 : Save corrected image
  o                     : Open a different reference image
  q                     : Quit application or close dialogs
"""

def parse_args():
    parser = argparse.ArgumentParser(
        description=HELP_TEXT,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("image_file", nargs="?", default=None, help="Input image file")
    parser.add_argument("--settings", type=str, default=None, help="Settings string to apply on startup")
    return parser.parse_args()

class CurvesEditor:
    def __init__(self, parent, curves_settings, apply_callback):
        self.parent = parent
        self.curves_settings = curves_settings.copy()
        self.apply_callback = apply_callback
        self.root = tk.Toplevel(parent)
        self.root.title("Curves Editor")
        self.root.bind("q", lambda e: self.root.destroy())

        tk.Label(self.root, text="Contrast:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.contrast_slider = ttk.Scale(
            self.root, from_=0.1, to=3.0, value=self.curves_settings.get("contrast", 1.0),
            command=lambda v: self.update_settings("contrast", float(v))
        )
        self.contrast_slider.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        tk.Label(self.root, text="Brightness:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.brightness_slider = ttk.Scale(
            self.root, from_=-100, to=100, value=self.curves_settings.get("brightness", 0),
            command=lambda v: self.update_settings("brightness", int(float(v)))
        )
        self.brightness_slider.grid(row=1, column=1, padx=5, pady=5, sticky="ew")

        tk.Button(self.root, text="Apply", command=self.apply).grid(row=2, column=0, columnspan=2, pady=10)
        tk.Button(self.root, text="Close", command=self.root.destroy).grid(row=3, column=0, columnspan=2, pady=5)

    def update_settings(self, key, value):
        self.curves_settings[key] = value

    def apply(self):
        self.apply_callback(self.curves_settings)
        self.root.destroy()

class PerspectiveTool:
    def __init__(self, root, args):
        self.root = root
        self.root.title(APP_TITLE)
        self.args = args
        self.source_file = args.image_file
        self.source_dir = os.path.dirname(self.source_file) if self.source_file else os.getcwd()
        self.settings_string = args.settings

        self.curves_settings = {"contrast": 1.0, "brightness": 0}
        self.perspective_box = None
        self.selected_corner = None
        self.last_selected_viewer = "left"
        self.active_handle = None
        self.shift_active = False
        self.ctrl_active = False
        self.hover_handle = None

        self.viewers = {
            "left": {"scale": 1.0, "offset_x": 0, "offset_y": 0, "canvas": None, "img": None, "tk_img": None},
            "right": {"scale": 1.0, "offset_x": 0, "offset_y": 0, "canvas": None, "img": None, "tk_img": None}
        }

        self.setup_ui()
        self.root.bind("<KeyPress-Shift_L>", lambda e: setattr(self, "shift_active", True))
        self.root.bind("<KeyRelease-Shift_L>", lambda e: setattr(self, "shift_active", False))
        self.root.bind("<KeyPress-Shift_R>", lambda e: setattr(self, "shift_active", True))
        self.root.bind("<KeyRelease-Shift_R>", lambda e: setattr(self, "shift_active", False))
        self.root.bind("<KeyPress-Control_L>", lambda e: setattr(self, "ctrl_active", True))
        self.root.bind("<KeyRelease-Control_L>", lambda e: setattr(self, "ctrl_active", False))
        self.root.bind("<KeyPress-Control_R>", lambda e: setattr(self, "ctrl_active", True))
        self.root.bind("<KeyRelease-Control_R>", lambda e: setattr(self, "ctrl_active", False))
        self.root.bind("<Left>", self.nudge_corner)
        self.root.bind("<Right>", self.nudge_corner)
        self.root.bind("<Up>", self.nudge_corner)
        self.root.bind("<Down>", self.nudge_corner)
        self.root.bind("r", self.reset_viewer)
        self.root.bind("e", self.open_curves_editor)
        self.root.bind("c", self.copy_settings)
        self.root.bind("v", self.paste_settings)
        self.root.bind("<Return>", self.save_image)
        self.root.bind("o", self.load_image_dialog)
        self.root.bind("q", lambda e: self.root.destroy())
        self.root.bind("<Motion>", self.on_mouse_move)

        if not self.load_image(self.source_file):
            self.root.destroy()
        if self.settings_string:
            self.apply_settings_string(self.settings_string)

    def setup_ui(self):
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        app_w = int(screen_w * 0.8)
        app_h = int(screen_h * 0.8)
        self.root.geometry(f"{app_w}x{app_h}")

        self.toolbar = tk.Menu(self.root)
        self.root.config(menu=self.toolbar)
        self.actions_menu = tk.Menu(self.toolbar, tearoff=0)
        self.toolbar.add_cascade(label="Actions", menu=self.actions_menu)
        self.actions_menu.add_command(label="Help", command=self.show_help)

        self.left_frame = tk.Frame(self.root)
        self.right_frame = tk.Frame(self.root)
        self.separator = tk.Frame(self.root, bg='black')
        self.separator.pack_propagate(False)
        self.separator.configure(width=HSEPARATOR_WIDTH)

        self.left_frame.pack(side="left", fill="both", expand=True)
        self.separator.pack(side="left", fill="y")
        self.right_frame.pack(side="right", fill="both", expand=True)

        self.viewers["left"]["canvas"] = tk.Canvas(self.left_frame, bg='#1a1a1a', highlightthickness=0)
        self.viewers["left"]["canvas"].pack(fill="both", expand=True)
        self.viewers["left"]["canvas"].bind("<MouseWheel>", lambda e: self.zoom("left", e))
        self.viewers["left"]["canvas"].bind("<Button-4>", lambda e: self.zoom("left", e))
        self.viewers["left"]["canvas"].bind("<Button-5>", lambda e: self.zoom("left", e))
        self.viewers["left"]["canvas"].bind("<Left>", self.nudge_corner)
        self.viewers["left"]["canvas"].bind("<Right>", self.nudge_corner)
        self.viewers["left"]["canvas"].bind("<Up>", self.nudge_corner)
        self.viewers["left"]["canvas"].bind("<Down>", self.nudge_corner)
        self.viewers["left"]["canvas"].bind("<ButtonPress-1>", lambda e: self.on_click("left", e))
        self.viewers["left"]["canvas"].bind("<B1-Motion>", lambda e: self.on_drag("left", e))

        self.viewers["right"]["canvas"] = tk.Canvas(self.right_frame, bg='#1a1a1a', highlightthickness=0)
        self.viewers["right"]["canvas"].pack(fill="both", expand=True)
        self.viewers["right"]["canvas"].bind("<MouseWheel>", lambda e: self.zoom("right", e))
        self.viewers["right"]["canvas"].bind("<Button-4>", lambda e: self.zoom("right", e))
        self.viewers["right"]["canvas"].bind("<Button-5>", lambda e: self.zoom("right", e))
        self.viewers["right"]["canvas"].bind("<ButtonPress-1>", lambda e: self.on_click("right", e))
        self.viewers["right"]["canvas"].bind("<B1-Motion>", lambda e: self.on_drag("right", e))

    def on_mouse_move(self, event):
        new_hover = self.get_handle_at("left", event.x, event.y)
        if new_hover != self.hover_handle:
            self.hover_handle = new_hover
            self.redraw("left")

    def load_image(self, file_path=None):
        if file_path is None:
            return self.load_image_dialog()
        try:
            self.orig_img = Image.open(file_path)
            self.source_file = file_path
            self.source_dir = os.path.dirname(file_path)
            self.img_w, self.img_h = self.orig_img.size
            self.viewers["left"]["img"] = self.orig_img.copy()
            self.viewers["right"]["img"] = self.orig_img.copy()
            self.apply_curves()
            self.perspective_box = [0, 0, self.img_w, 0, self.img_w, self.img_h, 0, self.img_h]
            self.update_preview()
            self.redraw("left")
            self.redraw("right")
            return True
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load image: {e}")
            return False

    def load_image_dialog(self, event=None):
        target = filedialog.askopenfilename(
            parent=self.root,
            title="Select Reference Image",
            initialdir=self.source_dir,
            filetypes=[("Images", "*.png *.jpg *.jpeg")]
        )
        if target:
            return self.load_image(target)
        return False

    def apply_curves(self):
        img = self.orig_img.copy()
        if "contrast" in self.curves_settings:
            img = ImageOps.autocontrast(img)
        if "brightness" in self.curves_settings:
            enhancer = ImageEnhance.Brightness(img)
            img = enhancer.enhance(1.0 + self.curves_settings["brightness"] / 100.0)
        self.viewers["left"]["img"] = img
        self.redraw("left")
        self.update_preview()

    def get_handle_at(self, viewer, x, y):
        if viewer != "left" or not self.perspective_box:
            return None
        scale = self.viewers[viewer]["scale"]
        offset_x = self.viewers[viewer]["offset_x"]
        offset_y = self.viewers[viewer]["offset_y"]
        for i in range(4):
            idx = i * 2
            px = self.perspective_box[idx] * scale + offset_x
            py = self.perspective_box[idx + 1] * scale + offset_y
            if abs(px - x) < 10 and abs(py - y) < 10:
                return i
        return None

    def on_click(self, viewer, event):
        self.last_selected_viewer = viewer
        if viewer == "left":
            handle = self.get_handle_at(viewer, event.x, event.y)
            if handle is not None and (event.state & 0x1):
                self.active_handle = handle
                self.redraw(viewer)
                return
            elif handle is not None:
                self.selected_corner = handle
                self.redraw(viewer)
                return
            self.selected_corner = None
        self.active_handle = None
        self.viewers[viewer]["last_mouse_x"] = event.x
        self.viewers[viewer]["last_mouse_y"] = event.y
        self.viewers[viewer]["active_handle"] = "pan"

    def on_drag(self, viewer, event):
        if viewer == "left" and self.active_handle is not None and isinstance(self.active_handle, int):
            idx = self.active_handle * 2
            cur_x = round((event.x - self.viewers[viewer]["offset_x"]) / self.viewers[viewer]["scale"])
            cur_y = round((event.y - self.viewers[viewer]["offset_y"]) / self.viewers[viewer]["scale"])
            self.perspective_box[idx] = cur_x
            self.perspective_box[idx + 1] = cur_y
            self.update_preview()
            self.redraw(viewer)
        elif self.viewers[viewer].get("active_handle") == "pan":
            dx = event.x - self.viewers[viewer]["last_mouse_x"]
            dy = event.y - self.viewers[viewer]["last_mouse_y"]
            self.viewers[viewer]["last_mouse_x"] = event.x
            self.viewers[viewer]["last_mouse_y"] = event.y
            if self.ctrl_active:
                for v in ["left", "right"]:
                    self.viewers[v]["offset_x"] += dx
                    self.viewers[v]["offset_y"] += dy
            else:
                self.viewers[viewer]["offset_x"] += dx
                self.viewers[viewer]["offset_y"] += dy
            self.redraw("left")
            self.redraw("right")

    def zoom(self, viewer, event):
        self.last_selected_viewer = viewer
        factor = 1.2 if (event.num == 4 or event.delta > 0) else 0.8
        if self.ctrl_active:
            new_offset_x = event.x - (event.x - self.viewers[viewer]["offset_x"]) * factor
            new_offset_y = event.y - (event.y - self.viewers[viewer]["offset_y"]) * factor
            new_scale = self.viewers[viewer]["scale"] * factor
            for v in ["left", "right"]:
                self.viewers[v]["offset_x"] = new_offset_x
                self.viewers[v]["offset_y"] = new_offset_y
                self.viewers[v]["scale"] = new_scale
        else:
            self.viewers[viewer]["offset_x"] = event.x - (event.x - self.viewers[viewer]["offset_x"]) * factor
            self.viewers[viewer]["offset_y"] = event.y - (event.y - self.viewers[viewer]["offset_y"]) * factor
            self.viewers[viewer]["scale"] *= factor
        self.redraw("left")
        self.redraw("right")

    def reset_viewer(self, event=None):
        if self.last_selected_viewer:
            self.viewers[self.last_selected_viewer]["scale"] = 1.0
            self.viewers[self.last_selected_viewer]["offset_x"] = 0
            self.viewers[self.last_selected_viewer]["offset_y"] = 0
            self.redraw(self.last_selected_viewer)

    def nudge_corner(self, event):
        if self.selected_corner is None or self.last_selected_viewer != "left":
            return
        dx, dy = 0, 0
        if event.keysym == "Left":
            dx = -1
        elif event.keysym == "Right":
            dx = 1
        elif event.keysym == "Up":
            dy = -1
        elif event.keysym == "Down":
            dy = 1
        idx = self.selected_corner * 2
        self.perspective_box[idx] += dx
        self.perspective_box[idx + 1] += dy
        self.update_preview()
        self.redraw("left")

    def update_preview(self):
        if not self.perspective_box:
            return
        try:
            # Counter-clockwise order: top-left, bottom-left, bottom-right, top-right
            reordered_box = [
                self.perspective_box[0], self.perspective_box[1],
                self.perspective_box[6], self.perspective_box[7],
                self.perspective_box[4], self.perspective_box[5],
                self.perspective_box[2], self.perspective_box[3]
            ]
            transformed = self.orig_img.transform(
                (self.img_w, self.img_h),
                Image.QUAD,
                reordered_box,
                resample=Image.BICUBIC
            )
            self.viewers["right"]["img"] = transformed
            self.redraw("right")
        except Exception as e:
            print(f"Preview error: {e}")

    def redraw(self, viewer):
        canvas = self.viewers[viewer]["canvas"]
        canvas.delete("all")
        cw, ch = canvas.winfo_width(), canvas.winfo_height()
        if cw <= 1 or ch <= 1:
            cw, ch = 1000, 800

        scale = self.viewers[viewer]["scale"]
        offset_x = self.viewers[viewer]["offset_x"]
        offset_y = self.viewers[viewer]["offset_y"]

        img = self.viewers[viewer]["img"]
        vx1, vy1 = -offset_x / scale, -offset_y / scale
        vx2, vy2 = vx1 + cw / scale, vy1 + ch / scale
        ix1, iy1 = max(0, int(vx1)), max(0, int(vy1))
        ix2, iy2 = min(img.width, int(vx2)), min(img.height, int(vy2))

        if ix2 > ix1 and iy2 > iy1:
            img_chunk = img.crop((ix1, iy1, ix2, iy2))
            try:
                mode = Image.Resampling.NEAREST
            except AttributeError:
                mode = Image.NEAREST
            chunk_w = max(1, int((ix2 - ix1) * scale))
            chunk_h = max(1, int((iy2 - iy1) * scale))
            img_chunk = img_chunk.resize((chunk_w, chunk_h), mode)
            self.viewers[viewer]["tk_img"] = ImageTk.PhotoImage(img_chunk)
            canvas.create_image(
                ix1 * scale + offset_x,
                iy1 * scale + offset_y,
                anchor="nw",
                image=self.viewers[viewer]["tk_img"]
            )

        if viewer == "left" and self.perspective_box:
            for i in range(4):
                idx = i * 2
                x = self.perspective_box[idx] * scale + offset_x
                y = self.perspective_box[idx + 1] * scale + offset_y
                if self.selected_corner == i:
                    color = "blue"
                elif self.hover_handle == i:
                    color = "green" if self.shift_active else "yellow"
                else:
                    color = "red"
                canvas.create_oval(x - 5, y - 5, x + 5, y + 5, fill=color, outline="white", width=2)
            for i in range(4):
                idx1 = i * 2
                idx2 = ((i + 1) % 4) * 2
                x1 = self.perspective_box[idx1] * scale + offset_x
                y1 = self.perspective_box[idx1 + 1] * scale + offset_y
                x2 = self.perspective_box[idx2] * scale + offset_x
                y2 = self.perspective_box[idx2 + 1] * scale + offset_y
                canvas.create_line(x1, y1, x2, y2, fill="red", width=2)

    def open_curves_editor(self, event=None):
        CurvesEditor(self.root, self.curves_settings, self.update_curves_from_editor)

    def update_curves_from_editor(self, new_settings):
        self.curves_settings.update(new_settings)
        self.apply_curves()

    def save_image(self, event=None):
        if not self.perspective_box:
            return
        base, ext = os.path.splitext(os.path.basename(self.source_file))
        out_dir = self.source_dir
        i = 1
        while True:
            out_file = os.path.join(out_dir, f"{base}_fix{i:02d}{ext}")
            if not os.path.exists(out_file):
                break
            i += 1
        save_path = filedialog.asksaveasfilename(
            initialdir=out_dir,
            initialfile=os.path.basename(out_file),
            defaultextension=ext[1:],
            filetypes=[("Images", "*.png *.jpg *.jpeg")]
        )
        if save_path:
            try:
                reordered_box = [
                    self.perspective_box[0], self.perspective_box[1],
                    self.perspective_box[6], self.perspective_box[7],
                    self.perspective_box[4], self.perspective_box[5],
                    self.perspective_box[2], self.perspective_box[3]
                ]
                transformed = self.orig_img.transform(
                    (self.img_w, self.img_h),
                    Image.QUAD,
                    reordered_box,
                    resample=Image.BICUBIC
                )
                transformed.save(save_path)
                x1, y1, x2, y2, x3, y3, x4, y4 = self.perspective_box
                magick_cmd = (
                    f'magick "{self.source_file}" -distort Perspective '
                    f'"0,0 {x1},{y1} {self.img_w},0 {x2},{y2} '
                    f'{self.img_w},{self.img_h} {x3},{y3} 0,{self.img_h} {x4},{y4}" '
                    f'"{save_path}"'
                )
                print(f"Saved: {save_path}")
                print(f"ImageMagick command: {magick_cmd}")
                self.root.destroy()
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save image: {e}")

    def copy_settings(self, event=None):
        curves_str = ",".join(f"{k}:{v}" for k, v in self.curves_settings.items())
        perspective_str = ",".join(map(str, self.perspective_box))
        settings_str = f"curves:{curves_str};perspective:{perspective_str}"
        self.settings_string = settings_str
        print(f"Copied settings: {settings_str}")

    def paste_settings(self, event=None):
        if not self.settings_string:
            return
        self.apply_settings_string(self.settings_string)
        print(f"Pasted settings: {self.settings_string}")

    def apply_settings_string(self, settings_str):
        try:
            parts = settings_str.split(";")
            for part in parts:
                if part.startswith("curves:"):
                    curves_part = part[len("curves:"):]
                    for item in curves_part.split(","):
                        if ":" in item:
                            k, v = item.split(":")
                            self.curves_settings[k] = float(v)
                    self.apply_curves()
                elif part.startswith("perspective:"):
                    perspective_part = part[len("perspective:"):]
                    coords = list(map(int, perspective_part.split(",")))
                    if len(coords) == 8:
                        self.perspective_box = coords
            self.update_preview()
            self.redraw("left")
            self.redraw("right")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to apply settings: {e}")

    def show_help(self, event=None):
        h_win = tk.Toplevel(self.root)
        h_win.title("Help")
        tk.Label(
            h_win,
            text=HELP_TEXT,
            font=("Monospace", 10),
            justify=tk.LEFT,
            padx=20,
            pady=20
        ).pack()
        h_win.bind("<Escape>", lambda e: h_win.destroy())
        h_win.bind("q", lambda e: h_win.destroy())

def main():
    args = parse_args()
    root = tk.Tk()
    app = PerspectiveTool(root, args)
    root.mainloop()

if __name__ == "__main__":
    main()
