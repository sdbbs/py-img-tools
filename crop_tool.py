#!/usr/bin/env python3

# vibe coded with google ai mode

import os
import sys
import argparse
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk

APP_TITLE = "Crop ROI Tool"

HELP_TEXT = f"""
{APP_TITLE} (Cross-Platform)
------------------------------
APPLICATION WORKFLOW:
  1. LOAD: Select a PNG or JPG reference image.
  2. COMPOSE: Pan with Left-Click, Zoom with Mouse Wheel.
  3. SELECT: Hold SHIFT and drag Left-Click to draw a new ROI.
  4. ADJUST: Hover over a corner handle.
     - Turns YELLOW: Ready to drag/resize.
     - Turns GREEN (Hold SHIFT): Confirmation for handle repositioning.
  5. EXECUTE: Press ENTER to finalize. A dialog appears:
     - Choose 'Yes' to get a file dalog to choose specific files to
       apply the same cropping to
     - Choose 'No' for the same cropping to be applied to all files
       in the folder of the reference image
     - Choose 'Cancel' to stop
  6. FINISH: The tool opens the 'cropped' folder (subfolder in the
     folder of the reference image, where the cropped output images
     are stored) and exits.

CONTROLS:
  Left-Click Drag       : Pan image (or drag handle if highlighted)
  Shift + L-Click Drag  : Draw NEW box (or drag handle if highlighted)
  Mouse Wheel           : Zoom in/out
  o                     : Open a different reference image
  q                     : Quit application
  ?                     : Show this help dialog
  Enter                 : Confirm batch processing
  Esc / Space           : Close Preview or Help dialogs

INSTALLATION:
  Linux   : sudo apt update && sudo apt install python3-pil.imagetk
  Windows : pip install Pillow

KNOWN THEME ISSUES (Ubuntu MATE / Dark Mode):
  If the file dialog shows invisible/white text, try these fixes:
  1. Use keyboard arrows and 'Enter' to navigate folders blind.
  2. Set 'GTK_THEME=Adwaita:light python3 adv_crop_tool.py' in terminal.
  3. Install tkfilebrowser: 'pip install tkfilebrowser'.
"""

def parse_args():
    parser = argparse.ArgumentParser(
        description=HELP_TEXT,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    return parser.parse_args()

class ZoomCropTool:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.source_dir = os.getcwd()
        self.roi_coords = None
        self.active_handle = None
        self.hover_handle = None
        self.shift_active = False
        self.last_mouse_x = self.last_mouse_y = 0
        self.scale = 1.0
        self.offset_x = self.offset_y = 0

        # UI Setup
        self.canvas = tk.Canvas(root, width=1000, height=800, bg='#1a1a1a', highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self.status_var = tk.StringVar(value="Help: press ? | Open: o | Quit: q")
        self.status_bar = tk.Label(root, textvariable=self.status_var, bd=1, relief=tk.SUNKEN, anchor=tk.W)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        self.overlay = self.canvas.create_text(10, 10, anchor="nw", fill="yellow", font=("Monospace", 12), text="")

        # Bindings
        self.canvas.bind("<ButtonPress-1>", self.on_click)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Motion>", self.on_mouse_move)
        self.canvas.bind("<MouseWheel>", self.zoom)
        self.canvas.bind("<Button-4>", self.zoom)
        self.canvas.bind("<Button-5>", self.zoom)

        self.root.bind("<KeyPress-Shift_L>", self.set_shift)
        self.root.bind("<KeyRelease-Shift_L>", self.set_shift)
        self.root.bind("<KeyPress-Shift_R>", self.set_shift)
        self.root.bind("<KeyRelease-Shift_R>", self.set_shift)

        self.root.bind("<Return>", self.confirm_dialog)
        self.root.bind("<space>", self.toggle_preview)
        self.root.bind("?", self.show_help)
        self.root.bind("q", lambda e: self.root.destroy())
        self.root.bind("o", self.load_image_dialog)

        if not self.load_image_dialog():
            self.root.destroy()

    def set_shift(self, event):
        self.shift_active = (event.type == tk.EventType.KeyPress)
        if self.hover_handle is not None:
            self.redraw()

    def get_handle_at(self, x, y):
        if not self.roi_coords: return None
        x1, y1, x2, y2 = self.roi_coords
        pts = [(x1,y1), (x2,y1), (x2,y2), (x1,y2)]
        for i, (ix, iy) in enumerate(pts):
            cx, cy = ix * self.scale + self.offset_x, iy * self.scale + self.offset_y
            if abs(cx - x) < 20 and abs(cy - y) < 20:
                return i
        return None

    def on_mouse_move(self, event):
        new_hover = self.get_handle_at(event.x, event.y)
        if new_hover != self.hover_handle:
            self.hover_handle = new_hover
            self.redraw()

    def get_im_format(self, coords):
        x1, y1, x2, y2 = coords
        w, h = abs(int(x2-x1)), abs(int(y2-y1))
        x, y = int(min(x1, x2)), int(min(y1, y2))
        return f"{w}x{h}+{x}+{y}", x, y, w, h

    def print_status(self, action):
        self.root.update_idletasks()
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        vx1, vy1 = -self.offset_x / self.scale, -self.offset_y / self.scale
        v_str, vx, vy, vw_i, vh_i = self.get_im_format((vx1, vy1, vx1 + cw/self.scale, vy1 + ch/self.scale))
        crop_str = "None"
        if self.roi_coords:
            c_im, cx, cy, cw_i, ch_i = self.get_im_format(self.roi_coords)
            crop_str = f"{c_im} (X: {cx} Y: {cy} W: {cw_i} H: {ch_i})"
        print(f"{action}: Image size {self.img_w}x{self.img_h} zoom {self.scale:.6f}; "
              f"area shown {v_str} (X: {vx} Y: {vy} W: {vw_i} H: {vh_i}); crop box {crop_str};")

    def redraw(self):
        self.canvas.delete("img", "roi", "hdl")
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        if cw <= 1: cw, ch = 1000, 800

        vx1, vy1 = -self.offset_x / self.scale, -self.offset_y / self.scale
        vx2, vy2 = vx1 + cw / self.scale, vy1 + ch / self.scale
        ix1, iy1 = max(0, int(vx1)), max(0, int(vy1))
        ix2, iy2 = min(self.img_w, int(vx2)), min(self.img_h, int(vy2))

        if ix2 > ix1 and iy2 > iy1:
            img_chunk = self.orig_img.crop((ix1, iy1, ix2, iy2))
            try: mode = Image.Resampling.NEAREST
            except AttributeError: mode = Image.NEAREST

            chunk_w = max(1, int((ix2-ix1)*self.scale))
            chunk_h = max(1, int((iy2-iy1)*self.scale))
            img_chunk = img_chunk.resize((chunk_w, chunk_h), mode)
            self.tk_img = ImageTk.PhotoImage(img_chunk)
            self.canvas.create_image(ix1*self.scale + self.offset_x, iy1*self.scale + self.offset_y, anchor="nw", image=self.tk_img, tags="img")

        if self.roi_coords:
            x1, y1, x2, y2 = self.roi_coords
            cx1, cy1 = x1 * self.scale + self.offset_x, y1 * self.scale + self.offset_y
            cx2, cy2 = x2 * self.scale + self.offset_x, y2 * self.scale + self.offset_y
            self.canvas.create_rectangle(cx1, cy1, cx2, cy2, outline="red", width=2, tags="roi")
            pts = [(cx1, cy1), (cx2, cy1), (cx2, cy2), (cx1, cy2)]
            for i, (px, py) in enumerate(pts):
                color = "red"
                if i == self.hover_handle:
                    color = "#00FF00" if self.shift_active else "yellow"
                self.canvas.create_rectangle(px-6, py-6, px+6, py+6, fill=color, tags="hdl")

            im_str, _, _, _, _ = self.get_im_format(self.roi_coords)
            self.canvas.itemconfig(self.overlay, text=f"ROI: {im_str}")
        else:
            self.canvas.itemconfig(self.overlay, text="Shift+Drag to draw ROI")
        self.canvas.tag_raise(self.overlay)

    def load_image_dialog(self, event=None):
        target = filedialog.askopenfilename(
            parent=self.root,
            title="Select Reference Image",
            initialdir=self.source_dir,
            filetypes=[("Images", "*.png *.jpg *.jpeg *.jpeg")]
        )
        if target:
            self.source_file = target
            self.source_dir = os.path.dirname(target)
            self.orig_img = Image.open(target)
            self.img_w, self.img_h = self.orig_img.size
            self.scale, self.offset_x, self.offset_y = 1.0, 0, 0
            self.redraw()
            return True
        return False

    def on_click(self, event):
        self.last_mouse_x, self.last_mouse_y = event.x, event.y
        handle = self.get_handle_at(event.x, event.y)
        if handle is not None:
            self.active_handle = handle
        else:
            self.active_handle = "new" if (event.state & 0x0001) else "pan"
            if self.active_handle == "new":
                self.start_x = round((event.x - self.offset_x)/self.scale)
                self.start_y = round((event.y - self.offset_y)/self.scale)

    def on_drag(self, event):
        cur_x = round((event.x - self.offset_x)/self.scale)
        cur_y = round((event.y - self.offset_y)/self.scale)
        if self.active_handle == "pan":
            self.offset_x += (event.x - self.last_mouse_x)
            self.offset_y += (event.y - self.last_mouse_y)
            self.last_mouse_x, self.last_mouse_y = event.x, event.y
        elif self.active_handle == "new":
            self.roi_coords = [self.start_x, self.start_y, cur_x, cur_y]
        else:
            if self.active_handle == 0: self.roi_coords[0:2] = [cur_x, cur_y]
            elif self.active_handle == 1: self.roi_coords[2] = cur_x; self.roi_coords[1] = cur_y
            elif self.active_handle == 2: self.roi_coords[2:4] = [cur_x, cur_y]
            elif self.active_handle == 3: self.roi_coords[0] = cur_x; self.roi_coords[3] = cur_y
        self.redraw()

    def on_release(self, event):
        if self.active_handle:
            label = "Image panned" if self.active_handle == "pan" else "Crop box edited"
            self.print_status(label)
        self.active_handle = None

    def zoom(self, event):
        factor = 1.2 if (event.num == 4 or event.delta > 0) else 0.8
        self.offset_x = event.x - (event.x - self.offset_x) * factor
        self.offset_y = event.y - (event.y - self.offset_y) * factor
        self.scale *= factor
        self.redraw()
        self.print_status("Image zoomed")

    def show_help(self, event=None):
        h_win = tk.Toplevel(self.root)
        h_win.title("Help")
        tk.Label(h_win, text=HELP_TEXT, font=("Monospace", 10), justify=tk.LEFT, padx=20, pady=20).pack()
        h_win.bind("<Escape>", lambda e: h_win.destroy())
        h_win.bind("<space>", lambda e: h_win.destroy())
        h_win.bind("q", lambda e: h_win.destroy())

    def toggle_preview(self, event=None):
        if hasattr(self, 'preview_win') and self.preview_win:
            self.preview_win.destroy()
            self.preview_win = None
            return
        if not self.roi_coords: return
        x1, y1, x2, y2 = self.roi_coords
        box = (int(min(x1, x2)), int(min(y1, y2)), int(max(x1, x2)), int(max(y1, y2)))
        self.preview_win = tk.Toplevel(self.root)
        self.preview_win.title("Preview")
        tk_p = ImageTk.PhotoImage(self.orig_img.crop(box))
        lbl = tk.Label(self.preview_win, image=tk_p)
        lbl.image = tk_p
        lbl.pack()
        self.preview_win.bind("<Escape>", lambda e: self.toggle_preview())
        self.preview_win.bind("<space>", lambda e: self.toggle_preview())
        self.preview_win.bind("q", lambda e: self.toggle_preview())

    def confirm_dialog(self, event):
        if not self.roi_coords: return
        self.print_status("Crop box accepted")
        res = messagebox.askyesnocancel("Batch Options", "Yes: Choose files | No: All files | Cancel: Stop")
        if res is None: return
        exts = ('.png', '.jpg', '.jpeg')
        files = filedialog.askopenfilenames(initialdir=self.source_dir, filetypes=[("Images", "*.png *.jpg *.jpeg")]) if res else \
                [os.path.join(self.source_dir, f) for f in os.listdir(self.source_dir) if f.lower().endswith(exts)]
        if files: self.run_crop(files)

    def run_crop(self, file_list):
        out_dir = os.path.join(self.source_dir, "cropped")
        os.makedirs(out_dir, exist_ok=True)
        x1, y1, x2, y2 = self.roi_coords
        cx, cy, cw, ch = int(min(x1, x2)), int(min(y1, y2)), int(abs(x2 - x1)), int(abs(y2 - y1))
        im_geo = f"{cw}x{ch}+{cx}+{cy}"
        for f in file_list:
            out = os.path.join(out_dir, os.path.basename(f))
            with Image.open(f) as img:
                img.crop((cx, cy, cx + cw, cy + ch)).save(out)
            print(f"Cropped as with: magick \"{f}\" -crop {im_geo} +repage \"{out}\"")

        if sys.platform == 'win32':
            os.startfile(out_dir)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', out_dir])
        else:
            subprocess.Popen(['xdg-open', out_dir])
        self.root.destroy()

def main():
    parse_args()
    root = tk.Tk()
    app = ZoomCropTool(root)
    root.mainloop()

if __name__ == "__main__":
    main()
