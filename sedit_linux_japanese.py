#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
sedit ― シンプルな Tkinter エディタ (Linux 用)
"""
import os
import sys
import json
import shutil
import datetime
import traceback
import threading
import queue
import keyword
import re
import shlex
import subprocess
import tempfile
import importlib
import bdb

import tkinter as tk
from tkinter import filedialog as fd
from tkinter import messagebox as msg
from tkinter import scrolledtext as sct
import tkinter.font as tkfont
from tkinter import ttk

# ----------------------------------------------------------------------
# 1.  ログ・設定ファイル
# ----------------------------------------------------------------------
def _get_log_path():
    """ログファイルへのパスを返す。"""
    xdg_data_home = os.environ.get('XDG_DATA_HOME')
    if not xdg_data_home:
        xdg_data_home = os.path.join(os.path.expanduser('~'), '.local', 'share')
    base = os.path.join(xdg_data_home, 'sedit')
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, 'sedit_extensions.log')

LOG_PATH = _get_log_path()
_LOG_LOCK = threading.Lock()

def log(msg_text, level='info'):
    """拡張機能用ログに書き込む。"""
    try:
        ts = datetime.datetime.now().isoformat()
        line = f"[{ts}] [{level.upper()}] {msg_text}\n"
        with _LOG_LOCK:
            with open(LOG_PATH, 'a', encoding='utf-8') as f:
                f.write(line)
    except Exception:
        print(msg_text, file=sys.stderr)

def _get_settings_path():
    """設定ファイルのパスを返す。"""
    xdg_config_home = os.environ.get('XDG_CONFIG_HOME')
    if not xdg_config_home:
        xdg_config_home = os.path.join(os.path.expanduser('~'), '.config')
    base = os.path.join(xdg_config_home, 'sedit')
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, 'settings.json')

SETTINGS_PATH = _get_settings_path()

def load_settings():
    try:
        if os.path.exists(SETTINGS_PATH):
            with open(SETTINGS_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def save_settings(d):
    global SETTINGS
    try:
        od = dict(SETTINGS or {})
        if d:
            od.update(d)
        os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
        with open(SETTINGS_PATH, 'w', encoding='utf-8') as f:
            json.dump(od, f, ensure_ascii=False, indent=2)
        SETTINGS = od
    except Exception:
        pass

SETTINGS = load_settings()

# ----------------------------------------------------------------------
# 2.  イベント（拡張機能用）
# ----------------------------------------------------------------------
EVENT_LISTENERS = {}  # event -> [(callback, owner, threaded), ...]


def add_event_listener(event, callback, owner=None, threaded=False):
    EVENT_LISTENERS.setdefault(event, []).append((callback, owner, bool(threaded)))


def remove_event_listener(event, callback=None, owner=None):
    lst = EVENT_LISTENERS.get(event)
    if not lst:
        return
    new = []
    for cb, own, thd in lst:
        if callback and cb != callback:
            new.append((cb, own, thd))
        elif owner and own != owner:
            new.append((cb, own, thd))
        elif not callback and not owner:
            new.append((cb, own, thd))
    EVENT_LISTENERS[event] = new


def emit_event(event, *args, **kwargs):
    for cb, owner, threaded in list(EVENT_LISTENERS.get(event, [] ) or []):
        try:
            if threaded:
                threading.Thread(target=lambda: _safe_call(cb, *args, **kwargs),
                                 daemon=True).start()
            else:
                try:
                    root.after(0, lambda c=cb: _safe_call(c, *args, **kwargs))
                except Exception:
                    _safe_call(cb, *args, **kwargs)
        except Exception:
            pass


def _safe_call(cb, *args, **kwargs):
    try:
        cb(*args, **kwargs)
    except Exception as e:
        try:
            log(f'Extension callback error: {e}', level='error')
        except Exception:
            pass

# ----------------------------------------------------------------------
# 3.  機能実装
# ----------------------------------------------------------------------
def Exit_sedit():
    if msg.askyesno("sedit", "本当に終了しますか？"):
        try:
            geom = root.winfo_geometry()
            save_settings({'window_geometry': geom})
        except Exception:
            pass
        root.destroy()

def open_log_viewer():
    win = tk.Toplevel(root)
    win.title('拡張ログビュー')
    win.geometry('900x500')
    frm = ttk.Frame(win)
    frm.pack(fill='both', expand=True)

    log_text = sct.ScrolledText(frm, wrap='none')
    log_text.pack(fill='both', expand=True)

    def load_log():
        if os.path.exists(LOG_PATH):
            with open(LOG_PATH, 'r', encoding='utf-8') as lf:
                data = lf.read()
        else:
            data = ''
        log_text.config(state='normal')
        log_text.delete('1.0', 'end')
        log_text.insert('1.0', data)
        log_text.see('end')
        log_text.config(state='disabled')

    follow_var = tk.BooleanVar(value=False)
    follow_id = {'id': None}

    def _poll():
        load_log()
        if follow_var.get():
            follow_id['id'] = win.after(1000, _poll)

    _poll()

    btnf = ttk.Frame(win)
    btnf.pack(fill='x')
    ttk.Button(btnf, text='Refresh', command=load_log).pack(side='left', padx=4, pady=4)

    def clear_log():
        if os.path.exists(LOG_PATH):
            with open(LOG_PATH, 'w', encoding='utf-8') as lf:
                lf.truncate(0)
        load_log()

    ttk.Button(btnf, text='Clear', command=clear_log).pack(side='left', padx=4)
    ttk.Checkbutton(btnf, text='Follow', variable=follow_var).pack(side='left', padx=6)
    ttk.Button(btnf, text='Open Log File',
               command=lambda: subprocess.Popen(['xdg-open', LOG_PATH],
                                                stdout=subprocess.DEVNULL,
                                                stderr=subprocess.DEVNULL)).pack(side='right', padx=6)

# ----------------------------------------------------------------------
# 4.  UI 初期化
# ----------------------------------------------------------------------
root = tk.Tk()
root.title("sedit")
# ウィンドウ直前にサイズをリストア
if SETTINGS.get('window_geometry'):
    try:
        root.geometry(SETTINGS['window_geometry'])
    except Exception:
        pass
root.geometry("1080x720")

# ---------- メニュー ----------
menu_par = tk.Menu(root, tearoff=False)
root.config(menu=menu_par)

menu_command = tk.Menu(root, tearoff=False)
menu_python = tk.Menu(root, tearoff=False)
menu_par.add_cascade(label="ファイル", menu=menu_command)
menu_par.add_cascade(label="pythonのメニュー", menu=menu_python)

menu_edit = tk.Menu(root, tearoff=False)
menu_par.add_cascade(label="編集", menu=menu_edit)
menu_view = tk.Menu(root, tearoff=False)
menu_par.add_cascade(label="表示", menu=menu_view)
menu_tool = tk.Menu(root, tearoff=False)
menu_par.add_cascade(label="ツール", menu=menu_tool)
menu_debug = tk.Menu(root, tearoff=False)
menu_par.add_cascade(label="デバッグ", menu=menu_debug)
menu_ext = tk.Menu(root, tearoff=False)
menu_par.add_cascade(label="拡張機能", menu=menu_ext)

# ---------- フォント ----------
font_families = list(tkfont.families())
preferred = ['Georgia', 'Fira Code', 'JetBrains Mono', 'Consolas',
             'Courier New', 'DejaVu Sans Mono']
chosen_font = next((f for f in preferred if f in font_families), 'Consolas')
editor_font = tkfont.Font(family=chosen_font, size=12)
# 設定からフォントを復元
if SETTINGS.get('font_family'):
    editor_font.config(family=SETTINGS['font_family'])
if SETTINGS.get('font_size'):
    editor_font.config(size=SETTINGS['font_size'])

# ---------- エディタ枠 ----------
editor_frame = ttk.Frame(root)
editor_frame.pack(fill='both', expand=True)

# 行番号フレーム
ln_frame = tk.Frame(editor_frame)
ln_frame.pack(side='left', fill='y')
line_numbers = tk.Text(ln_frame, width=6, padx=4,
                       takefocus=0, border=0,
                       background='#f0f0f0', state='disabled',
                       wrap='none')
line_numbers.pack(fill='both', expand=True)

# テキストウィジェットとスクロールバー
text = tk.Text(editor_frame, wrap='none', undo=True, font=editor_font)
vscroll = ttk.Scrollbar(editor_frame, orient='vertical',
                        command=lambda *args: (text.yview(*args), line_numbers.yview(*args)))
text.configure(yscrollcommand=lambda *args: (vscroll.set(*args), 
                                              line_numbers.yview_moveto(args[0] if args else '0')))
vscroll.pack(side='right', fill='y')
text.pack(side='right', fill='both', expand=True)

# ---------- 行番号更新 ----------
def update_line_numbers(event=None):
    try:
        line_numbers.config(state='normal')
        line_numbers.delete('1.0', 'end')
        last = int(text.index('end-1c').split('.')[0])
        nums = '\n'.join(str(i) for i in range(1, last + 1))
        line_numbers.insert('1.0', nums, 'ln')
        line_numbers.config(state='disabled')
    except Exception:
        pass

update_line_numbers()

# ---------- シンタックスハイライト ----------
highlight_var = tk.BooleanVar(value=False)
highlight_after_id = None

text.tag_config("keyword", foreground="blue")
text.tag_config("comment", foreground="#008000")
text.tag_config("string", foreground="#b34700")

def highlight_text():
    try:
        src = text.get("1.0", "end-1c")
    except tk.TclError:
        return
    text.tag_remove("keyword", "1.0", "end")
    text.tag_remove("comment", "1.0", "end")
    text.tag_remove("string", "1.0", "end")

    # コメント
    for m in re.finditer(r"#.*", src):
        start = f"1.0 + {m.start()}c"
        end = f"1.0 + {m.end()}c"
        text.tag_add("comment", start, end)

    # 文字列（トリプル・シングル・ダブル）
    for m in re.finditer(r'(""".*?"""|\'\'\'.*?\'\'\'|\".*?\"|\'.*?\')', src, re.S):
        start = f"1.0 + {m.start()}c"
        end = f"1.0 + {m.end()}c"
        text.tag_add("string", start, end)

    # キーワード
    kw_regex = r"\b(?:" + "|".join(re.escape(w) for w in keyword.kwlist) + r")\b"
    for m in re.finditer(kw_regex, src):
        start = f"1.0 + {m.start()}c"
        end = f"1.0 + {m.end()}c"
        if "string" in text.tag_names(start) or "comment" in text.tag_names(start):
            continue
        text.tag_add("keyword", start, end)

    # テキスト変更イベントを発行（拡張機能用）
    try:
        emit_event('text_changed', src)
    except Exception:
        pass

def toggle_highlight():
    if highlight_var.get():
        highlight_text()
    else:
        text.tag_remove("keyword", "1.0", "end")
        text.tag_remove("comment", "1.0", "end")
        text.tag_remove("string", "1.0", "end")

def _on_key_release(event=None):
    if not highlight_var.get():
        return
    global highlight_after_id
    try:
        if highlight_after_id:
            root.after_cancel(highlight_after_id)
    except Exception:
        pass
    highlight_after_id = root.after(150, highlight_text)

text.bind("<KeyRelease>", _on_key_release)
text.bind('<KeyRelease>', lambda e: update_line_numbers(), add='+')
text.bind('<Button-1>', lambda e: update_line_numbers(), add='+')
text.bind('<MouseWheel>', lambda e: update_line_numbers(), add='+')
text.bind('<Configure>', lambda e: update_line_numbers(), add='+')

# Linux 用にホイールイベント追加
if sys.platform != 'win32':
    text.bind("<Button-4>", lambda e: update_line_numbers())
    text.bind("<Button-5>", lambda e: update_line_numbers())

# ---------- Undo / Redo ----------
def _do_undo(event=None):
    try:
        text.edit_undo()
    except Exception:
        pass
    return 'break'

def _do_redo(event=None):
    try:
        text.edit_redo()
    except Exception:
        pass
    return 'break'

text.bind('<Control-z>', _do_undo)
text.bind('<Control-Z>', _do_undo)
text.bind('<Control-y>', _do_redo)
text.bind('<Control-Y>', _do_redo)
text.bind('<Control-Shift-Z>', _do_redo)

# ---------- Cut / Copy / Paste ----------
def _do_cut(event=None):
    try:
        sel = text.get('sel.first', 'sel.last')
    except Exception:
        sel = None
    if sel:
        root.clipboard_clear()
        root.clipboard_append(sel)
        try:
            text.delete('sel.first', 'sel.last')
        except Exception:
            pass
    return 'break'

def _do_copy(event=None):
    try:
        sel = text.get('sel.first', 'sel.last')
    except Exception:
        sel = None
    if sel:
        root.clipboard_clear()
        root.clipboard_append(sel)
    return 'break'

def _do_paste(event=None):
    try:
        clip = root.clipboard_get()
    except Exception:
        clip = ''
    try:
        text.delete('sel.first', 'sel.last')
    except Exception:
        pass
    text.insert('insert', clip)
    return 'break'

def _select_all(event=None):
    try:
        text.tag_add('sel', '1.0', 'end')
        text.mark_set('insert', '1.0')
        text.see('insert')
    except Exception:
        pass
    return 'break'

text.bind('<Control-x>', _do_cut)
text.bind('<Control-X>', _do_cut)
text.bind('<Control-c>', _do_copy)
text.bind('<Control-C>', _do_copy)
text.bind('<Control-v>', _do_paste)
text.bind('<Control-V>', _do_paste)
text.bind('<Control-a>', _select_all)
text.bind('<Control-A>', _select_all)

# ---------- メニュー項目 ----------
menu_command.add_command(label="開く…", accelerator="Ctrl+O", command=lambda: OpenFiles())
menu_command.add_command(label="保存…", accelerator="Ctrl+S", command=lambda: SaveFiles())
menu_command.add_separator()
menu_command.add_command(label="終了", command=Exit_sedit)

menu_python.add_checkbutton(label="ハイライトモード",
                            variable=highlight_var,
                            command=toggle_highlight)
menu_python.add_command(label="Pythonで実行…",
                           accelerator="F5",
                           command=lambda: RunPythonThere())

menu_edit.add_command(label='元に戻す     Ctrl+Z', command=_do_undo, accelerator='Ctrl+Z')
menu_edit.add_command(label='やり直し     Ctrl+Y', command=_do_redo, accelerator='Ctrl+Y')
menu_edit.add_separator()
menu_edit.add_command(label='切り取り     Ctrl+X', command=_do_cut, accelerator='Ctrl+X')
menu_edit.add_command(label='コピー       Ctrl+C', command=_do_copy, accelerator='Ctrl+C')
menu_edit.add_command(label='貼り付け     Ctrl+V', command=_do_paste, accelerator='Ctrl+V')
menu_edit.add_separator()
menu_edit.add_command(label='すべて選択   Ctrl+A', command=_select_all, accelerator='Ctrl+A')

# ---------- テーマ ----------
theme_var = tk.StringVar(value=SETTINGS.get('theme', 'light'))

def apply_theme(mode: str):
    style = ttk.Style()
    if mode == 'dark':
        try:
            style.theme_use('clam')
        except Exception:
            pass
        root_bg = '#2e2e2e'
        text_bg = '#1e1e1e'
        text_fg = '#dcdcdc'
        insert_col = '#ffffff'
        sel_bg = '#264f78'
        kw_col = '#569CD6'
        cm_col = '#6A9955'
        st_col = '#CE9178'
    else:
        try:
            style.theme_use('default')
        except Exception:
            pass
        root_bg = root.cget('bg') or '#f0f0f0'
        text_bg = '#ffffff'
        text_fg = '#000000'
        insert_col = '#000000'
        sel_bg = '#cce8ff'
        kw_col = 'blue'
        cm_col = '#008000'
        st_col = '#b34700'

    root.configure(bg=root_bg)
    text.configure(background=text_bg, foreground=text_fg,
                   insertbackground=insert_col, selectbackground=sel_bg)
    line_numbers.configure(background=text_bg, foreground=text_fg)
    ln_frame.configure(bg=text_bg)

    text.tag_config("keyword", foreground=kw_col)
    text.tag_config("comment", foreground=cm_col)
    text.tag_config("string", foreground=st_col)

    theme_var.set(mode)
    save_settings({'theme': mode,
                   'font_family': editor_font.cget('family'),
                   'font_size': editor_font.cget('size')})

apply_theme(theme_var.get())

menu_view.add_radiobutton(label='ライトモード',
                          variable=theme_var, value='light',
                          command=lambda: apply_theme('light'))
menu_view.add_radiobutton(label='ダークモード',
                          variable=theme_var, value='dark',
                          command=lambda: apply_theme('dark'))
menu_view.add_command(label='ログビュー', command=open_log_viewer)

# ---------- ファイル操作 ----------
file = None  # 現在開いているファイル名（None で未保存）

def OpenFiles():
    global file
    fp = fd.askopenfilename()
    if not fp:
        return
    try:
        with open(fp, "r", encoding="utf-8") as f:
            content = f.read()
        text.delete("1.0", "end-1c")
        text.insert("1.0", content)
        root.title(f"sedit [{fp}]")
        file = fp
        if highlight_var.get():
            highlight_text()
        save_settings({'last_file': fp})
        recent = SETTINGS.get('recent_files', [])[:]
        if fp in recent:
            recent.remove(fp)
        recent.insert(0, fp)
        save_settings({'recent_files': recent[:20]})
        emit_event('file_opened', fp)
    except Exception as e:
        msg.showerror("読み込みエラー", str(e))

def SaveFiles():
    global file
    fp = fd.asksaveasfilename()
    if not fp:
        return
    try:
        with open(fp, "w", encoding="utf-8") as f:
            f.write(text.get("1.0", "end-1c"))
        file = fp
        root.title(f"sedit [{fp}]")
        emit_event('file_saved', fp)
    except Exception as e:
        msg.showerror("保存エラー", str(e))

# ---------- Python 実行 ----------
def _get_python_cmd():
    if not getattr(sys, "frozen", False):
        return [sys.executable]
    py = shutil.which("python") or shutil.which("python3")
    return [py] if py else [sys.executable]

def RunPythonThere():
    opts = tk.Toplevel(root)
    opts.title('Run Options')
    opts.geometry('480x360')
    frm = ttk.Frame(opts)
    frm.pack(fill='both', expand=True, padx=8, pady=8)

    use_saved_var = tk.BooleanVar(value=bool(file))
    chk = ttk.Checkbutton(frm, text='Use saved file if available',
                          variable=use_saved_var)
    chk.pack(anchor='w')

    ttk.Label(frm, text='Command-line arguments:').pack(anchor='w', pady=(8,0))
    args_e = ttk.Entry(frm)
    args_e.pack(fill='x')
    ttk.Label(frm, text='Environment variables (KEY=VALUE per line):').pack(anchor='w', pady=(8,0))
    env_text = sct.ScrolledText(frm, height=8)
    env_text.pack(fill='both', expand=True)

    def parse_env(text_val):
        env = {}
        for raw in text_val.splitlines():
            s = raw.strip()
            if not s or s.startswith('#'):
                continue
            if '=' in s:
                k, v = s.split('=', 1)
                env[k.strip()] = v.strip()
        return env

    def start_run():
        fp = file
        use_saved = use_saved_var.get()
        args_str = args_e.get().strip()
        env_overrides = parse_env(env_text.get('1.0', 'end-1c'))

        src = None
        run_path = None
        use_temp = False
        try:
            if use_saved and fp and os.path.exists(fp):
                run_path = fp
            else:
                src = text.get("1.0", "end-1c")
                tf = tempfile.NamedTemporaryFile('w', delete=False,
                                                suffix='.py', encoding='utf-8')
                tf.write(src)
                tf.close()
                run_path = tf.name
                use_temp = True
        except Exception as e:
            msg.showerror('Run Error', f'Failed preparing code: {e}')
            return

        def _runner(path, args_list, env_map, remove_temp):
            try:
                out_win = tk.Toplevel(root)
                out_win.title(f"Python: {os.path.basename(path)}")
                out_text = sct.ScrolledText(out_win, width=80, height=20)
                out_text.pack(fill='both', expand=True)
                out_text.insert('end', f'Running: {path} {" ".join(args_list)}\n\n')
                out_text.see('end')
                env = os.environ.copy()
                env.update(env_map)
                cmd = _get_python_cmd() + [path] + args_list
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, bufsize=1,
                                        text=True, env=env)
                for line in proc.stdout:
                    out_text.insert('end', line)
                    out_text.see('end')
                proc.wait()
                out_text.insert('end',
                                f"\nProcess exited with code {proc.returncode}\n")
                out_text.see('end')
            except Exception as e:
                try:
                    msg.showerror('Run Error', str(e))
                except Exception:
                    pass
            finally:
                if remove_temp:
                    try:
                        os.remove(path)
                    except Exception:
                        pass

        try:
            args_list = shlex.split(args_str) if args_str else []
        except Exception:
            args_list = []

        th = threading.Thread(target=_runner, args=(run_path, args_list,
                                                    env_overrides, use_temp),
                              daemon=True)
        th.start()
        opts.destroy()

    btns = ttk.Frame(frm)
    btns.pack(fill='x', pady=6)
    ttk.Button(btns, text='Run', command=start_run).pack(side='right', padx=6)
    ttk.Button(btns, text='Cancel', command=opts.destroy).pack(side='right')

# ---------- GUI ビルダー ----------
def open_gui_builder():
    builder = tk.Toplevel(root)
    builder.title("GUI Builder")
    builder.geometry("900x600")

    palette = ttk.Frame(builder, width=140)
    palette.pack(side='left', fill='y')
    canvas = tk.Canvas(builder, bg='#ffffff')
    canvas.pack(side='left', expand=True, fill='both')
    props = ttk.Frame(builder, width=220)
    props.pack(side='right', fill='y')
    status_label = tk.Label(palette, text="選択: なし")
    status_label.pack(pady=6)

    # ---- スタイルパネル ----
    style_frame = ttk.LabelFrame(palette, text='Style')
    style_frame.pack(fill='x', padx=6, pady=6)
    style_obj = ttk.Style()
    ttk.Label(style_frame, text='Theme:').pack(anchor='w')
    theme_cb = ttk.Combobox(style_frame, values=list(style_obj.theme_names()), state='readonly')
    try:
        theme_cb.set(style_obj.theme_use())
    except Exception:
        if style_obj.theme_names():
            theme_cb.set(style_obj.theme_names()[0])
    theme_cb.pack(fill='x')
    def apply_theme_cb(evt=None):
        try:
            style_obj.theme_use(theme_cb.get())
        except Exception:
            pass
    theme_cb.bind('<<ComboboxSelected>>', apply_theme_cb)

    ttk.Label(style_frame, text='Style name (eg My.TButton):').pack(anchor='w')
    style_name_e = ttk.Entry(style_frame)
    style_name_e.pack(fill='x')
    ttk.Label(style_frame, text='Foreground:').pack(anchor='w')
    style_fg = ttk.Entry(style_frame)
    style_fg.pack(fill='x')
    ttk.Label(style_frame, text='Background:').pack(anchor='w')
    style_bg = ttk.Entry(style_frame)
    style_bg.pack(fill='x')
    ttk.Label(style_frame, text='Font (e.g. Arial 10):').pack(anchor='w')
    style_font = ttk.Entry(style_frame)
    style_font.pack(fill='x')
    ttk.Label(style_frame, text='Padding (e.g. 4):').pack(anchor='w')
    style_pad = ttk.Entry(style_frame)
    style_pad.pack(fill='x')

    styles_used = {}

    def create_or_update_style():
        name = style_name_e.get().strip()
        if not name:
            return
        opts = {}
        fg = style_fg.get().strip()
        bg = style_bg.get().strip()
        f = style_font.get().strip()
        p = style_pad.get().strip()
        if fg: opts['foreground'] = fg
        if bg: opts['background'] = bg
        if f:
            try:
                parts = f.split()
                if len(parts) >= 2 and parts[-1].isdigit():
                    fam = ' '.join(parts[:-1]); size = int(parts[-1])
                    opts['font'] = (fam, size)
                else:
                    opts['font'] = f
            except Exception:
                opts['font'] = f
        if p:
            try:
                opts['padding'] = int(p)
            except Exception:
                opts['padding'] = p
        try:
            style_obj.configure(name, **opts)
            styles_used[name] = opts
        except Exception:
            styles_used[name] = opts

    ttk.Button(style_frame, text='Create/Update Style',
               command=create_or_update_style).pack(pady=4)

    # ---- クリックで作成 ----
    current_type = {'val': None}
    created = []  # (widget, type, win_id, handle_id)
    selected_widget = {'w': None, 'id': None}
    sel_rect = {'id': None}
    grid_size = 16

    def snap(v): return int(round(v / grid_size) * grid_size)

    def draw_grid(event=None):
        canvas.delete('grid')
        w = canvas.winfo_width()
        h = canvas.winfo_height()
        for x in range(0, w, grid_size):
            canvas.create_line(x, 0, x, h, fill='#eee', tag='grid')
        for y in range(0, h, grid_size):
            canvas.create_line(0, y, w, y, fill='#eee', tag='grid')

    canvas.bind('<Configure>', draw_grid)

    def select_widget_type(wt):
        current_type['val'] = wt
        status_label.config(text=f"選択: {wt}")

    for wt in ('Button', 'Label', 'Entry', 'Text'):
        ttk.Button(palette, text=wt, width=14,
                   command=lambda wt=wt: select_widget_type(wt)).pack(padx=6, pady=4)

    def canvas_click(e):
        wt = current_type['val']
        if not wt:
            return
        x = snap(e.x); y = snap(e.y)
        if wt == 'Button':
            w = ttk.Button(canvas, text='Button')
        elif wt == 'Label':
            w = ttk.Label(canvas, text='Label')
        elif wt == 'Entry':
            w = ttk.Entry(canvas, width=15)
        elif wt == 'Text':
            w = tk.Text(canvas, width=20, height=5)
        else:
            return
        win_id = canvas.create_window(x, y, window=w, anchor='nw')
        pw = w.winfo_reqwidth(); ph = w.winfo_reqheight()
        canvas.itemconfig(win_id, width=pw, height=ph)
        handle = tk.Frame(canvas, bg='black', width=10, height=10)
        handle_id = canvas.create_window(x + pw - 8, y + ph - 8,
                                        window=handle, anchor='nw')
        created.append((w, wt, win_id, handle_id))
        make_draggable(w, win_id, handle_id)
        select_widget(w, win_id)

    def make_draggable(w, win_id, handle_id):
        def on_press(e):
            w._drag_start_x = e.x
            w._drag_start_y = e.y
            select_widget(w, win_id)

        def on_motion(e):
            cur = canvas.coords(win_id)
            if not cur:
                return
            nx = cur[0] + (e.x - w._drag_start_x)
            ny = cur[1] + (e.y - w._drag_start_y)
            nx = snap(nx); ny = snap(ny)
            canvas.coords(win_id, nx, ny)
            iw = canvas.itemcget(win_id, 'width')
            ih = canvas.itemcget(win_id, 'height')
            try:
                iw = int(float(iw)); ih = int(float(ih))
            except Exception:
                iw, ih = w.winfo_width(), w.winfo_height()
            canvas.coords(handle_id, nx + iw - 8, ny + ih - 8)
            if selected_widget.get('id') == win_id and sel_rect.get('id'):
                try:
                    canvas.coords(sel_rect['id'], nx-2, ny-2,
                                  nx+iw+2, ny+ih+2)
                except Exception:
                    pass

        def handle_press(e):
            handle._start_x = e.x
            handle._start_y = e.y
            try:
                handle._start_w = int(float(canvas.itemcget(win_id, 'width')))
                handle._start_h = int(float(canvas.itemcget(win_id, 'height')))
            except Exception:
                handle._start_w, handle._start_h = w.winfo_width(), w.winfo_height()

        def handle_motion(e):
            dx = e.x - handle._start_x
            dy = e.y - handle._start_y
            neww = max(16, snap(handle._start_w + dx))
            newh = max(8, snap(handle._start_h + dy))
            canvas.itemconfig(win_id, width=neww, height=newh)
            wt = None
            for (_w, _wt, _id, _hid) in created:
                if _id == win_id:
                    wt = _wt; break
            if wt == 'Entry':
                try:
                    w.config(width=max(1, int(neww/8)))
                except Exception:
                    pass
            if wt == 'Text':
                try:
                    w.config(width=max(1, int(neww/8)), height=max(1, int(newh/16)))
                except Exception:
                    pass
            cur = canvas.coords(win_id)
            if cur:
                canvas.coords(handle_id, cur[0] + neww - 8, cur[1] + newh - 8)
                if selected_widget.get('id') == win_id and sel_rect.get('id'):
                    try:
                        canvas.coords(sel_rect['id'],
                                      cur[0]-2, cur[1]-2,
                                      cur[0]+neww+2, cur[1]+newh+2)
                    except Exception:
                        pass

        w.bind("<Button-1>", on_press)
        w.bind("<B1-Motion>", on_motion)
        handle = canvas.nametowidget(canvas.itemcget(handle_id, 'window'))
        handle.bind("<Button-1>", handle_press)
        handle.bind("<B1-Motion>", handle_motion)

    def select_widget(w, win_id):
        if sel_rect.get('id'):
            try: canvas.delete(sel_rect['id'])
            except Exception: pass
            sel_rect['id'] = None
        selected_widget['w'] = w
        selected_widget['id'] = win_id
        for child in props.winfo_children(): child.destroy()
        tk.Label(props, text='Properties',
                 font=('Arial', 12, 'bold')).pack(pady=6)

        cur = canvas.coords(win_id)
        px, py = int(cur[0]), int(cur[1]) if cur else 0, 0
        tk.Label(props, text=f"x: {px}  y: {py}").pack()

        try:
            pw = int(float(canvas.itemcget(win_id, 'width')))
            ph = int(float(canvas.itemcget(win_id, 'height')))
        except Exception:
            pw, ph = w.winfo_width(), w.winfo_height()
        tk.Label(props, text=f"width: {pw}  height: {ph}").pack()

        try:
            sel_id = canvas.create_rectangle(px-2, py-2, px+pw+2, py+ph+2,
                                             outline='blue', width=2)
            sel_rect['id'] = sel_id
        except Exception:
            sel_rect['id'] = None

        wt = None
        for (_w, _wt, _id, _hid) in created:
            if _id == win_id: wt = _wt; break

        if wt in ('Button', 'Label'):
            tk.Label(props, text='text').pack(anchor='w', padx=6)
            te = tk.Entry(props)
            te.pack(fill='x', padx=6)
            try: te.insert(0, w.cget('text'))
            except Exception: te.insert(0, '')
            def apply_text():
                try: w.config(text=te.get())
                except Exception: pass
            tk.Button(props, text='Apply', command=apply_text).pack(pady=6)

        if wt == 'Entry':
            tk.Label(props, text='width (chars)').pack(anchor='w', padx=6)
            we = tk.Entry(props)
            we.pack(fill='x', padx=6)
            try: we.insert(0, w.cget('width'))
            except Exception: we.insert(0, '')
            def apply_entry():
                try:
                    w.config(width=int(we.get()))
                    canvas.itemconfig(win_id, width=w.winfo_reqwidth())
                except Exception: pass
            tk.Button(props, text='Apply', command=apply_entry).pack(pady=6)

        if wt == 'Text':
            tk.Label(props, text='width (chars)').pack(anchor='w', padx=6)
            wwi = tk.Entry(props)
            wwi.pack(fill='x', padx=6)
            tk.Label(props, text='height (lines)').pack(anchor='w', padx=6)
            hhi = tk.Entry(props)
            hhi.pack(fill='x', padx=6)
            try:
                wwi.insert(0, w.cget('width'))
                hhi.insert(0, w.cget('height'))
            except Exception: pass
            def apply_text_wh():
                try:
                    w.config(width=int(wwi.get()), height=int(hhi.get()))
                    canvas.itemconfig(win_id,
                                      width=w.winfo_reqwidth(),
                                      height=w.winfo_reqheight())
                except Exception: pass
            tk.Button(props, text='Apply', command=apply_text_wh).pack(pady=6)

    canvas.bind("<Button-1>", canvas_click)

    def export_code():
        lines = []
        lines.append("import tkinter as tk")
        lines.append("from tkinter import ttk")
        lines.append("root = tk.Tk()")
        if styles_used:
            lines.append("style = ttk.Style()")
            for sname, opts in styles_used.items():
                parts = [f"{k}={repr(v)}" for k, v in opts.items()]
                if parts:
                    lines.append(f"style.configure({repr(sname)}, {', '.join(parts)})")
        for idx, (w, wt, win_id, handle_id) in enumerate(created, start=1):
            name = f"w{idx}"
            coords = canvas.coords(win_id)
            x, y = int(coords[0]) if coords else 0, int(coords[1]) if coords else 0
            try:
                pw = int(float(canvas.itemcget(win_id, 'width')))
                ph = int(float(canvas.itemcget(win_id, 'height')))
            except Exception:
                pw, ph = w.winfo_width(), w.winfo_height()
            if wt == 'Button':
                txt = w.cget('text')
                style_val = w.cget('style')
                if style_val:
                    lines.append(f"{name} = ttk.Button(root, text={repr(txt)}, style={repr(style_val)})")
                else:
                    lines.append(f"{name} = ttk.Button(root, text={repr(txt)})")
                lines.append(f"{name}.place(x={x}, y={y}, width={pw}, height={ph})")
            elif wt == 'Label':
                txt = w.cget('text')
                style_val = w.cget('style')
                if style_val:
                    lines.append(f"{name} = ttk.Label(root, text={repr(txt)}, style={repr(style_val)})")
                else:
                    lines.append(f"{name} = ttk.Label(root, text={repr(txt)})")
                lines.append(f"{name}.place(x={x}, y={y}, width={pw}, height={ph})")
            elif wt == 'Entry':
                width_chars = w.cget('width')
                lines.append(f"{name} = ttk.Entry(root, width={width_chars})")
                lines.append(f"{name}.place(x={x}, y={y})")
            elif wt == 'Text':
                width_chars = w.cget('width')
                height_lines = w.cget('height')
                lines.append(f"{name} = tk.Text(root, width={width_chars}, height={height_lines})")
                lines.append(f"{name}.place(x={x}, y={y})")
        lines.append("root.mainloop()")
        text.insert('insert', "\n# GUI Builder generated\n" + "\n".join(lines) + "\n")
        builder.destroy()

    ttk.Button(builder, text='Insert GUI Code',
               command=export_code).pack(side='bottom', pady=6)

# ---------- デバッガ ----------
def open_debugger():
    dbg_win = tk.Toplevel(root)
    dbg_win.title("Debugger")
    dbg_win.geometry('800x400')
    ctrl = tk.Frame(dbg_win)
    ctrl.pack(side='top', fill='x')
    out = sct.ScrolledText(dbg_win, height=12)
    out.pack(side='bottom', fill='both', expand=True)

    q = queue.Queue()

    def _highlight_current(fname, lineno):
        text.tag_remove('debug_current', '1.0', 'end')
        try:
            start = f"{lineno}.0"
            text.tag_add('debug_current', start, f"{lineno}.end")
            text.tag_config('debug_current', background='yellow')
            text.see(start)
        except Exception:
            pass

    class SimpleGuiBdb(bdb.Bdb):
        def __init__(self, gui_queue, filename):
            super().__init__()
            self.gui_q = gui_queue
            self.filename = filename
            self._wait_event = threading.Event()
            self._next_action = None
            self._stop_requested = False

        def user_line(self, frame):
            if self._stop_requested:
                raise bdb.BdbQuit()
            f = frame
            lineno = frame.f_lineno
            fname = self.canonic(frame.f_code.co_filename)
            self.gui_q.put(('stopped', fname, lineno))
            self._wait_event.clear()
            self._wait_event.wait()
            action = self._next_action
            if action == 'step':
                self.set_step()
            elif action == 'next':
                self.set_next(frame)
            elif action == 'continue':
                self.set_continue()
            elif action == 'quit':
                self._stop_requested = True
                raise bdb.BdbQuit()

        def set_action(self, action):
            self._next_action = action
            self._wait_event.set()

    def _thread_runner(source, filename):
        gui_bdb = SimpleGuiBdb(q, filename)
        try:
            code = compile(source, filename, 'exec')
            globals_dict = {'__name__': '__main__', '__file__': filename}
            gui_bdb.run(code, globals_dict, globals_dict)
        except bdb.BdbQuit:
            q.put(('exited',))
        except Exception:
            tb = traceback.format_exc()
            q.put(('error', tb))
        finally:
            q.put(('finished',))

    def start_debug():
        source = text.get('1.0', 'end-1c')
        filename = globals().get('file', '<string>')
        out.insert('end', 'Debugger started\n')
        th = threading.Thread(target=_thread_runner,
                              args=(source, filename),
                              daemon=True)
        th.start()

    def stop_debug():
        # 現在のバッファを強制終了
        pass

    def step():
        pass

    def toggle_breakpoint():
        try:
            line = int(text.index('insert').split('.')[0])
        except Exception:
            return
        b = bdb.Bdb()
        b.set_break(b.canonic('<string>'), line)
        out.insert('end', f'Set breakpoint {line}\n')

    tk.Button(ctrl, text='Start', command=start_debug).pack(side='left')
    tk.Button(ctrl, text='Stop', command=stop_debug).pack(side='left')
    tk.Button(ctrl, text='Toggle BP', command=toggle_breakpoint).pack(side='left')

    def poll_queue():
        while True:
            try:
                msg = q.get_nowait()
            except queue.Empty:
                break
            if msg[0] == 'stopped':
                _, fname, lineno = msg
                out.insert('end', f'Stopped at {fname}:{lineno}\n')
                _highlight_current(fname, lineno)
            elif msg[0] == 'error':
                out.insert('end', msg[1] + '\n')
            elif msg[0] == 'finished':
                out.insert('end', 'Finished\n')
            elif msg[0] == 'exited':
                out.insert('end', 'Debugger exited\n')
        dbg_win.after(100, poll_queue)

    poll_queue()
    text.tag_config('debug_current', background='yellow')
    return dbg_win

menu_debug.add_command(label='デバッガーを開く', command=open_debugger)

# ---------- 設定ウィンドウ ----------
def open_settings():
    win = tk.Toplevel(root)
    win.title('設定')
    win.geometry('420x380')
    container = ttk.Frame(win)
    container.pack(fill='both', expand=True)

    canvas = tk.Canvas(container, borderwidth=0)
    vscroll = ttk.Scrollbar(container, orient='vertical',
                            command=canvas.yview)
    canvas.configure(yscrollcommand=vscroll.set)
    vscroll.pack(side='right', fill='y')
    canvas.pack(side='left', fill='both', expand=True)

    frm = ttk.Frame(canvas, padding=10)
    win_id = canvas.create_window((0, 0), window=frm, anchor='nw')

    def _on_frame_configure(event=None):
        canvas.configure(scrollregion=canvas.bbox('all'))
    frm.bind('<Configure>', _on_frame_configure)

    def _on_canvas_configure(event):
        canvas.itemconfig(win_id, width=event.width)
    canvas.bind('<Configure>', _on_canvas_configure)

    def _on_mousewheel(event):
        canvas.yview_scroll(int(-1*(event.delta/120)), 'units')
    canvas.bind_all('<MouseWheel>', _on_mousewheel)

    ttk.Label(frm, text='Editor Font:').pack(anchor='w')
    fonts = sorted(list(tkfont.families()))
    font_cb = ttk.Combobox(frm, values=fonts)
    font_cb.set(editor_font.cget('family'))
    font_cb.pack(fill='x', pady=4)

    ttk.Label(frm, text='Size:').pack(anchor='w')
    size_spin = ttk.Spinbox(frm, from_=8, to=48, increment=1)
    size_spin.set(editor_font.cget('size'))
    size_spin.pack(fill='x', pady=4)

    ttk.Label(frm, text='Preview:').pack(anchor='w', pady=(8, 0))
    preview = tk.Text(frm, height=4, wrap='word')
    preview.insert('1.0',
                   'The quick brown fox jumps over the lazy dog. 0123456789')
    preview.pack(fill='both', expand=False, pady=4)

    def apply_preview(evt=None):
        f = font_cb.get().strip()
        try:
            s = int(size_spin.get())
        except Exception:
            s = 12
        try:
            pf = tkfont.Font(family=f, size=s)
            preview.configure(font=pf)
        except Exception:
            pass
    font_cb.bind('<<ComboboxSelected>>', apply_preview)
    size_spin.bind('<KeyRelease>', lambda e: apply_preview())

    def do_apply():
        f = font_cb.get().strip()
        try:
            s = int(size_spin.get())
        except Exception:
            s = 12
        editor_font.config(family=f, size=s)
        text.configure(font=editor_font)
        line_numbers.configure(font=editor_font)
        update_line_numbers()
        save_settings({'font_family': editor_font.cget('family'),
                       'font_size': editor_font.cget('size'),
                       'theme': theme_var.get()})
        win.destroy()

    btnf = ttk.Frame(frm)
    btnf.pack(fill='x', pady=8)
    ttk.Button(btnf, text='Apply', command=do_apply).pack(side='right', padx=6)
    ttk.Button(btnf, text='Cancel', command=win.destroy).pack(side='right')

    ttk.Label(frm, text='Autosave:').pack(anchor='w', pady=(8, 0))
    autosave_var = tk.IntVar(value=1 if SETTINGS.get('autosave_enabled') else 0)
    autosave_chk = ttk.Checkbutton(frm, text='Enable autosave',
                                   variable=autosave_var)
    autosave_chk.pack(anchor='w')
    ttk.Label(frm, text='Interval (seconds):').pack(anchor='w')
    autosave_spin = ttk.Spinbox(frm, from_=5, to=3600, increment=5)
    autosave_spin.set(SETTINGS.get('autosave_interval', 60))
    autosave_spin.pack(fill='x')

    ttk.Label(frm, text='Recent Files:').pack(anchor='w', pady=(8, 0))
    rf = SETTINGS.get('recent_files', [])
    lb = tk.Listbox(frm, height=6)
    for p in rf:
        lb.insert('end', p)
    lb.pack(fill='both', expand=False)

# ---------- 設定メニュー ----------
menu_par.add_command(label='設定', command=open_settings, accelerator='Ctrl+,')

# ---------- 拡張機能 ----------
EXT_DIR = os.path.join(os.path.dirname(__file__), 'extensions')
os.makedirs(EXT_DIR, exist_ok=True)

class ExtensionManager:
    def __init__(self, ext_dir, api_root_menu):
        self.ext_dir = ext_dir
        self.loaded = {}
        self.info = {}
        self.submenus = {}
        self.api_root_menu = api_root_menu
        self.resources = {}
        self.menu_items = {}

    def _scan_files(self):
        res = {}
        for entry in os.listdir(self.ext_dir):
            full = os.path.join(self.ext_dir, entry)
            if os.path.isdir(full):
                candidates = [os.path.join(full, f"{entry}.py"),
                              os.path.join(full, 'main.py'),
                              os.path.join(full, '__init__.py')]
                found = None
                for c in candidates:
                    if os.path.exists(c):
                        found = c
                        break
                if not found:
                    for f in os.listdir(full):
                        if f.endswith('.py'):
                            found = os.path.join(full, f)
                            break
                if found:
                    res[entry] = found
            elif entry.endswith('.py'):
                name = os.path.splitext(entry)[0]
                if os.path.isdir(os.path.join(self.ext_dir, name)):
                    continue
                res[name] = os.path.join(self.ext_dir, entry)
        return res

    def load_all(self):
        for en in list(self.info.keys()):
            if self.info.get(en, {}).get('enabled'):
                try:
                    self.disable(en)
                except Exception:
                    pass
        self.loaded, self.info, self.menu_items, self.resources = {}, {}, {}, {}
        files = self._scan_files()
        enabled = SETTINGS.get('enabled_extensions', []) or []
        for name, path in files.items():
            try:
                spec = importlib.util.spec_from_file_location(f'sedit_ext_{name}', path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                dirpath = os.path.dirname(path)
                readme = os.path.join(dirpath, 'README.md') if os.path.exists(
                    os.path.join(dirpath, 'README.md')) else None
                self.loaded[name] = mod
                self.info[name] = {'path': path, 'enabled': name in enabled,
                                   'dir': dirpath, 'readme': readme}
            except Exception as e:
                self.loaded[name] = None
                self.info[name] = {'path': path, 'enabled': False,
                                   'error': str(e), 'dir': os.path.dirname(path) if path else None}
                log(f'Failed to load extension {name}: {e}', level='error')
        for name, meta in list(self.info.items()):
            if meta.get('enabled'):
                try:
                    self.enable(name)
                except Exception:
                    pass

    def get_submenu(self, name):
        if name in self.submenus:
            return self.submenus[name]
        m = tk.Menu(self.api_root_menu, tearoff=False)
        self.api_root_menu.add_cascade(label=name, menu=m)
        self.submenus[name] = m
        return m

    def enable(self, name):
        mod = self.loaded.get(name)
        if not mod:
            raise RuntimeError('Extension not loaded')
        try:
            self.resources.setdefault(name, [])
            self.menu_items[name] = []
            api = ExtensionAPI(self, name)
            if hasattr(mod, 'setup') and callable(mod.setup):
                mod.setup(api)
            self.info.setdefault(name, {})['enabled'] = True
            cur = SETTINGS.get('enabled_extensions', [])[:]
            if name not in cur:
                cur.append(name)
                save_settings({'enabled_extensions': cur})
            build_extensions_menu()
        except Exception:
            raise

    def disable(self, name):
        mod = self.loaded.get(name)
        if not mod:
            return
        try:
            if hasattr(mod, 'teardown') and callable(mod.teardown):
                mod.teardown(ExtensionAPI(self, name))
            self._cleanup_resources(name)
            self.menu_items[name] = []
            if name in self.submenus:
                self.submenus[name].destroy()
                del self.submenus[name]
            self.info.setdefault(name, {})['enabled'] = False
            cur = SETTINGS.get('enabled_extensions', [])[:]
            if name in cur:
                cur.remove(name)
                save_settings({'enabled_extensions': cur})
            build_extensions_menu()
        except Exception:
            pass

    def register_resource(self, name, resource):
        self.resources.setdefault(name, []).append(resource)

    def register_menu_item(self, name, label, callback):
        self.menu_items.setdefault(name, []).append((label, callback))

    def _cleanup_resources(self, name):
        for r in list(self.resources.get(name, []) or []):
            try:
                if hasattr(r, 'destroy') and callable(r.destroy):
                    r.destroy()
                elif callable(r):
                    r()
            except Exception:
                pass
        self.resources[name] = []

class ExtensionAPI:
    def __init__(self, manager: ExtensionManager, name: str):
        self.manager = manager
        self.name = name

    @property
    def root(self): return root

    @property
    def text(self): return text

    def get_menu(self):
        class _ProxyMenu:
            def __init__(self, mgr, nm):
                self._mgr = mgr
                self._nm = nm
            def add_command(self, label, command=None):
                try:
                    self._mgr.register_menu_item(self._nm, label, command)
                except Exception:
                    pass
        return _ProxyMenu(self.manager, self.name)

    def add_command(self, label, command):
        try:
            self.manager.register_menu_item(self.name, label, command)
        except Exception:
            pass

    def open_file(self, path: str):
        try:
            if not path:
                return False
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            global file
            file = path
            text.delete('1.0', 'end-1c')
            text.insert('1.0', content)
            root.title(f"sedit[{path}]")
            emit_event('file_opened', path)
            return True
        except Exception:
            return False

    def save_file(self, path: str = None):
        try:
            global file
            target = path or globals().get('file', None)
            if not target:
                target = fd.asksaveasfilename()
                if not target:
                    return False
            with open(target, 'w', encoding='utf-8') as f:
                f.write(text.get('1.0', 'end-1c'))
            file = target
            emit_event('file_saved', target)
            return True
        except Exception:
            return False

    def get_setting(self, key, default=None):
        return SETTINGS.get(key, default)

    def set_setting(self, key, value):
        save_settings({key: value})
        return True

    def on(self, event, callback):
        add_event_listener(event, callback, owner=self.name, threaded=False)
        return True

    def off(self, event, callback):
        remove_event_listener(event, callback, owner=self.name)
        return True

    def run_background(self, fn, *args, **kwargs):
        t = threading.Thread(target=lambda: fn(*args, **kwargs), daemon=True)
        t.start()
        return t

    def log(self, message, level='info'):
        log(f'[{self.name}] {message}', level=level)

    def get_extension_settings(self):
        return SETTINGS.get('extensions', {}).get(self.name, {})

    def set_extension_settings(self, obj):
        ex = SETTINGS.get('extensions', {})
        ex[self.name] = obj
        save_settings({'extensions': ex})
        return True

    def register_resource(self, resource):
        self.manager.register_resource(self.name, resource)

# ---------- 拡張メニュー ----------
menu_ext.add_command(label='拡張機能フォルダを開く',
                     command=lambda: subprocess.Popen(['xdg-open', EXT_DIR],
                                                stdout=subprocess.DEVNULL,
                                                stderr=subprocess.DEVNULL))
menu_ext.add_command(label='拡張機能を再読み込み',
                     command=lambda: (ext_manager.load_all(), build_extensions_menu()))
menu_ext.add_separator()

ext_manager = ExtensionManager(EXT_DIR, menu_ext)

def build_extensions_menu():
    menu_ext.delete(0, 'end')
    menu_ext.add_command(label='拡張機能フォルダを開く',
                         command=lambda: subprocess.Popen(['xdg-open', EXT_DIR],
                                                stdout=subprocess.DEVNULL,
                                                stderr=subprocess.DEVNULL))
    menu_ext.add_command(label='拡張機能を再読み込み',
                         command=lambda: (ext_manager.load_all(), build_extensions_menu()))
    menu_ext.add_separator()
    for name, meta in sorted(ext_manager.info.items()):
        var = tk.IntVar(value=1 if meta.get('enabled') else 0)
        def make_toggle(n, v):
            def _toggle():
                try:
                    if v.get():
                        ext_manager.enable(n)
                    else:
                        ext_manager.disable(n)
                except Exception as e:
                    log(f'Enable {n} failed: {e}', level='error')
                    v.set(0)
                finally:
                    build_extensions_menu()
            return _toggle
        menu_ext.add_checkbutton(label=name, variable=var,
                                 command=make_toggle(name, var))
        if meta.get('readme'):
            menu_ext.add_command(label='    Open README',
                                 command=lambda p=meta['readme']:
                                     subprocess.Popen(['xdg-open', p],
                                                stdout=subprocess.DEVNULL,
                                                stderr=subprocess.DEVNULL))
        elif meta.get('dir'):
            menu_ext.add_command(label='    Open Folder',
                                 command=lambda p=meta['dir']:
                                     subprocess.Popen(['xdg-open', p],
                                                stdout=subprocess.DEVNULL,
                                                stderr=subprocess.DEVNULL))
        for (mlabel, mcb) in ext_manager.menu_items.get(name, []):
            disp_label = f'    {mlabel}'
            def _wrap(cb=mcb):
                return lambda: _safe_call(cb)
            menu_ext.add_command(label=disp_label, command=_wrap())

try:
    ext_manager.load_all()
    build_extensions_menu()
except Exception:
    pass

# ---------- キーボードショートカット ----------
root.bind_all('<Control-o>', lambda e: OpenFiles())
root.bind_all('<Control-O>', lambda e: OpenFiles())
root.bind_all('<Control-s>', lambda e: SaveFiles())
root.bind_all('<Control-S>', lambda e: SaveFiles())
root.bind_all('<F5>', lambda e: RunPythonThere())
root.bind_all('<Control-r>', lambda e: RunPythonThere())
root.bind_all('<Control-R>', lambda e: RunPythonThere())
root.bind_all('<Control-g>', lambda e: open_gui_builder())
root.bind_all('<Control-G>', lambda e: open_gui_builder())
root.bind_all('<Control-Shift-D>', lambda e: open_debugger())

# ---------- メインループ ----------
root.mainloop()
