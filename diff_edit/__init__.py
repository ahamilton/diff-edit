#!/usr/bin/env python3


"""Diff-edit.

Edit two files side by side, showing differences.
"""


import asyncio
import contextlib
import difflib
import functools
import os
import sys

import docopt
import fill3
import fill3.terminal as terminal
import termstr

import diff_edit.editor as editor


__version__ = "v2022.02.23"


PROJECT_NAME = "diff-edit"
USAGE = f"""
Usage:
  {PROJECT_NAME} <file-a> [<file-b>]
  {PROJECT_NAME} -h | --help
  {PROJECT_NAME} --version

Example:
  # {PROJECT_NAME} project.py.bak project.py

Keys:
  (Ctrl-x, Ctrl-s)         Save file.
  Alt-o or (Ctrl-x, o)     Switch focus between editors. (toggle)
  Alt-up                   Move to previous difference.
  Alt-down                 Move to next difference.
  Alt-c                    Change syntax highlighting theme. (cycle)
  Alt-h                    Hide sub-highlighting of modifications. (toggle)
  Esc or (Ctrl-x, Ctrl-c)  Quit.
"""


_LINE_MAP = {"━": 0b0101, "┃": 0b1010, "┏": 0b0110, "┗": 0b1100, "┛": 0b1001, "┓": 0b0011,
             "╋": 0b1111, "┣": 0b1110, "┳": 0b0111, "┫": 0b1011, "┻": 0b1101, " ": 0b0000}
_LINE_MAP_INVERTED = {v: k for k, v in _LINE_MAP.items()}


@functools.cache
def union_box_line(a_line, b_line):
    return _LINE_MAP_INVERTED[_LINE_MAP[a_line] | _LINE_MAP[b_line]]


@functools.lru_cache(maxsize=500)
def highlight_str(line, bg_color, transparency):
    def blend_style(style):
        return termstr.CharStyle(
            termstr.blend_color(style.fg_color, bg_color, transparency),
            termstr.blend_color(style.bg_color, bg_color, transparency),
            is_bold=style.is_bold, is_italic=style.is_italic, is_underlined=style.is_underlined)
    return termstr.TermStr(line).transform_style(blend_style)


@functools.lru_cache(maxsize=500)
def line_diff(a_text, b_text):
    return difflib.SequenceMatcher(a=a_text, b=b_text).get_opcodes()


def get_lines(text_editor, start, end):
    return (tuple(text_editor.text_widget[start:end]),
            tuple(text_editor.text_widget.appearance_interval((start, end))))


def replace_part(a_str, start, end, part):
    return a_str[:start] + part + a_str[end:]


@functools.lru_cache(maxsize=500)
def highlight_modification(a_lines, b_lines, show_sub_highlights):
    blue = termstr.Color.blue
    left_line = fill3.join("\n", tuple(colored_line[:len(line)]
                                       for line, colored_line in zip(*a_lines)))
    right_line = fill3.join("\n", tuple(colored_line[:len(line)]
                                        for line, colored_line in zip(*b_lines)))
    if show_sub_highlights:
        diff = line_diff(left_line.data, right_line.data)
        for opcode, left_start, left_end, right_start, right_end in diff:
            color = termstr.Color.white if opcode == "replace" else termstr.Color.green
            if opcode == "delete" or opcode == "replace":
                part = highlight_str(left_line[left_start:left_end], color, 0.8)
                left_line = replace_part(left_line, left_start, left_end, part)
            if opcode == "insert" or opcode == "replace":
                part = highlight_str(right_line[right_start:right_end], color, 0.8)
                right_line = replace_part(right_line, right_start, right_end, part)
    return ([highlight_str(line + a_line[len(line):], blue, 0.6)
             for line, a_line in zip(left_line.split("\n"), a_lines[1])],
            [highlight_str(line + b_line[len(line):], blue, 0.6)
             for line, b_line in zip(right_line.split("\n"), b_lines[1])])


def draw_connector(columns, color, left_y, right_y):
    left_arrows, line, right_arrows = columns
    height = len(left_arrows)
    left_corner, right_corner = ("┓", "┗") if left_y < right_y else ("┛", "┏")
    if left_y == right_y:
        left_corner, right_corner = "━", "━"
    for column, y, arrow, corner in [(left_arrows, left_y, "╺", left_corner),
                                     (right_arrows, right_y, "╸", right_corner)]:
        if y <= 0:
            pass
        elif y >= height - 1:
            pass
        else:
            column[y] = termstr.TermStr(arrow).fg_color(color)
            line[y] = union_box_line(corner, line[y])
    if 0 < left_y < height - 1 or 0 < right_y < height - 1:
        if left_y != right_y:
            start, end = sorted([left_y, right_y])
            start = max(start, -1)
            end = min(end, height)
            for index in range(start+1, end):
                line[index] = union_box_line("┃", line[index])


def ranges_overlap(a, b):
    return a[1] > b[0] and a[0] < b[1]


def overlay_list(bg_list, fg_list, index):
    if index < 0:
        bg_len = len(bg_list)
        bg_list[:len(fg_list) + index] = fg_list[abs(index):]
        bg_list[bg_len:] = []
    else:
        bg_list[index:index + len(fg_list)] = fg_list[:len(bg_list) - index]
    return bg_list


class DiffEditor:

    def __init__(self, left_path, right_path):
        self.left_editor = editor.Editor(is_left_aligned=False)
        self.left_editor.load(left_path)
        self.left_editor.view_widget.is_left_scrollbar = True
        self.right_editor = editor.Editor()
        self.right_editor.load(right_path)
        self.show_sub_highlights = True
        self.previous_term_code = None
        left_decor = editor.Decor(self.left_editor.text_widget, self._left_highlight_lines)
        self.left_editor.decor_widget.widget = left_decor
        self.left_view = self.left_editor.view_widget
        right_decor = editor.Decor(self.right_editor.text_widget, self._right_highlight_lines)
        self.right_editor.decor_widget.widget = right_decor
        self.right_view = self.right_editor.view_widget
        self.right_editor.is_editing = False
        self.editors = [self.left_editor, self.right_editor]

    @functools.cached_property
    def diff(self):
        return difflib.SequenceMatcher(a=self.left_editor.text_widget,
                                       b=self.right_editor.text_widget).get_opcodes()

    def diff_changed(self):
        with contextlib.suppress(AttributeError):
            del self.diff

    def _highlight_lines(self, appearance, start, end, opcode, change_opcode):
        if opcode == change_opcode:
            for index in range(start, end):
                appearance[index] = highlight_str(appearance[index], (0, 200, 0), 0.6)

    def _left_highlight_lines(self, appearance):
        view_x, view_y = self.left_view.position
        view_end_y = view_y + len(appearance)
        for op, left_start, left_end, right_start, right_end in self.diff:
            if op == "replace" and ranges_overlap((left_start, left_end), (view_y, view_end_y)):
                left_lines = get_lines(self.left_editor, left_start, left_end)
                right_lines = get_lines(self.right_editor, right_start, right_end)
                left_appearance, right_appearance = highlight_modification(
                    left_lines, right_lines, self.show_sub_highlights)
                overlay_list(appearance, left_appearance, left_start - view_y)
            self._highlight_lines(appearance, max(left_start, view_y) - view_y,
                                  min(left_end, view_end_y) - view_y, op, "delete")
        return appearance

    def _right_highlight_lines(self, appearance):
        view_x, view_y = self.right_view.position
        view_end_y = view_y + len(appearance)
        for op, left_start, left_end, right_start, right_end in self.diff:
            if op == "replace" and ranges_overlap((right_start, right_end), (view_y, view_end_y)):
                left_lines = get_lines(self.left_editor, left_start, left_end)
                right_lines = get_lines(self.right_editor, right_start, right_end)
                left_appearance, right_appearance = highlight_modification(
                    left_lines, right_lines, self.show_sub_highlights)
                overlay_list(appearance, right_appearance, right_start - view_y)
            self._highlight_lines(appearance, max(right_start, view_y) - view_y,
                                  min(right_end, view_end_y) - view_y, op, "insert")
        return appearance

    def _equivalent_line(self, y):
        for opcode, left_start, left_end, right_start, right_end in self.diff:
            if self.editors[0] == self.right_editor:
                left_start, left_end, right_start, right_end = \
                    right_start, right_end, left_start, left_end
            if left_start <= y < left_end:
                fraction = (y - left_start) / (left_end - left_start)
                other_y = round(right_start + fraction * (right_end - right_start))
                return other_y - 1 if other_y == len(self.editors[1].text_widget) else other_y
        return y

    def follow_scroll(self):
        x, y = self.editors[0].scroll_position
        last_width, last_height = self.last_dimensions
        middle_y = last_height // 2
        new_y = self._equivalent_line(y + middle_y)
        self.editors[1].scroll_position = max(0, x), max(0, new_y - middle_y)

    def switch_editor(self):
        self.editors[1].cursor_x = self.editors[0].cursor_x
        self.editors[1].cursor_y = self._equivalent_line(
            self.editors[0].cursor_y)
        self.editors[1].follow_cursor()
        self.editors.reverse()
        self.editors[0].is_editing, self.editors[1].is_editing = True, False

    def on_divider_pressed(self, x, y, left_x, right_x):
        left_scroll = self.left_view.position[1]
        right_scroll = self.right_view.position[1]
        for opcode, left_start, left_end, right_start, right_end in self.diff:
            if opcode == "equal":
                continue
            left_y = left_start - left_scroll + 1  # 1 for header
            right_y = right_start - right_scroll + 1  # 1 for header
            if x == left_x and left_y == y:
                self.left_editor.text_widget[left_start:left_end] = \
                    [self.right_editor.text_widget[line_num]
                     for line_num in range(right_start, right_end)]
                self.diff_changed()
            elif x == right_x and right_y == y:
                self.right_editor.text_widget[right_start:right_end] = \
                    [self.left_editor.text_widget[line_num]
                     for line_num in range(left_start, left_end)]
                self.diff_changed()

    def on_mouse_press(self, x, y, left_x, right_x):
        if x < left_x:
            if self.editors[0] == self.right_editor:
                self.switch_editor()
            self.left_editor.on_mouse_press(x, y)
        elif x > right_x:
            if self.editors[0] == self.left_editor:
                self.switch_editor()
            self.right_editor.on_mouse_press(x - right_x - 1, y)
        else:  # divider pressed
            self.on_divider_pressed(x, y, left_x, right_x)

    def on_mouse_event(self, action, x, y):
        width, height = self.last_dimensions
        divider_width = 3
        left_x = (width - divider_width) // 2
        right_x = left_x + 2
        if action == terminal.MOUSE_PRESS:
            self.on_mouse_press(x, y, left_x, right_x)
        elif action == terminal.MOUSE_DRAG:
            if x < left_x:
                self.left_editor.on_mouse_drag(x, y)
            elif x > right_x:
                self.right_editor.on_mouse_drag(x - right_x - 1, y)

    def toggle_highlights(self):
        self.show_sub_highlights = not self.show_sub_highlights

    def jump_to_next_diff(self):
        y = self.editors[0].cursor_y
        for op, left_start, left_end, right_start, right_end in self.diff:
            if op == "equal":
                continue
            start = (left_start if self.editors[0] == self.left_editor
                     else right_start)
            if start > y:
                try:
                    self.editors[0].cursor_y = start
                except IndexError:
                    self.editors[0].cursor_y = start - 1
                self.editors[0].center_cursor()
                break

    def jump_to_previous_diff(self):
        y = self.editors[0].cursor_y
        for op, left_start, left_end, right_start, right_end in reversed(self.diff):
            if op == "equal":
                continue
            start = (left_start if self.editors[0] == self.left_editor
                     else right_start)
            if start < y:
                try:
                    self.editors[0].cursor_y = start
                except IndexError:
                    self.editors[0].cursor_y = start - 1
                self.editors[0].center_cursor()
                break

    def cycle_syntax_highlighting(self):
        for editor_ in self.editors:
            editor_.cycle_syntax_highlighting()

    def on_keyboard_input(self, term_code):
        if action := (self.KEY_MAP.get((self.previous_term_code, term_code))
                      or self.KEY_MAP.get(term_code)):
            action(self)
        else:
            self.editors[0].on_keyboard_input(term_code)
            self.diff_changed()
        self.previous_term_code = term_code
        fill3.APPEARANCE_CHANGED_EVENT.set()

    def on_mouse_input(self, term_code):
        action, flag, x, y = terminal.decode_mouse_input(term_code)
        if action in [terminal.MOUSE_PRESS, terminal.MOUSE_DRAG, terminal.MOUSE_RELEASE]:
            self.on_mouse_event(action, x, y)
            fill3.APPEARANCE_CHANGED_EVENT.set()

    _ARROW_COLORS = [termstr.Color.yellow, termstr.Color.green, termstr.Color.red,
                     termstr.Color.light_blue, termstr.Color.purple, termstr.Color.orange,
                     termstr.Color.brown]

    def divider_appearance(self, height):
        left_scroll = self.left_view.position[1]
        right_scroll = self.right_view.position[1]
        left_arrows = [" "] * height
        line = [" "] * height
        right_arrows = [" "] * height
        columns = [left_arrows, line, right_arrows]
        color_index = 0
        colors = self._ARROW_COLORS
        has_top_mark, has_bottom_mark = False, False
        for opcode, left_start, left_end, right_start, right_end in self.diff:
            if opcode == "equal":
                continue
            color = colors[color_index % len(colors)]
            left_y = left_start - left_scroll + 1  # 1 for header
            right_y = right_start - right_scroll + 1  # 1 for header
            draw_connector(columns, color, left_y, right_y)
            for y in [left_y, right_y]:
                if y <= 0:
                    has_top_mark = True
                elif y >= height - 1:
                    has_bottom_mark = True
            color_index += 1
        if has_top_mark:
            line[0] = "↑"
        if has_bottom_mark:
            line[-1] = "↓"
        return columns

    def appearance_for(self, dimensions):
        width, height = self.last_dimensions = dimensions
        self.follow_scroll()
        divider_width = 3
        left_width = (width - divider_width) // 2
        right_width = width - divider_width - left_width
        left_appearance = self.left_editor.appearance_for((left_width, height))
        right_appearance = self.right_editor.appearance_for((right_width, height))
        inactive_appearance = (right_appearance if self.left_editor is self.editors[0]
                               else left_appearance)
        inactive_appearance[0] = highlight_str(inactive_appearance[0], termstr.Color.black, 0.5)
        return fill3.join_horizontal(
            [left_appearance] + self.divider_appearance(height) + [right_appearance])

    KEY_MAP = {(terminal.CTRL_X, "o"): switch_editor, terminal.ALT_o: switch_editor,
               terminal.ALT_h: toggle_highlights, terminal.ALT_DOWN: jump_to_next_diff,
               terminal.ALT_UP: jump_to_previous_diff, terminal.ALT_c: cycle_syntax_highlighting}


def check_arguments():
    arguments = docopt.docopt(USAGE)
    if arguments["--version"]:
        print(__version__)
        sys.exit(0)
    for path in [arguments["<file-a>"], arguments["<file-b>"]]:
        if path is not None and not os.path.isfile(path):
            print("File does not exist:", path)
            sys.exit(1)
    return arguments["<file-a>"], arguments["<file-b>"]


def main():
    path_a, path_b = check_arguments()
    if path_b is None:
        editor_ = editor.Editor(path_a)
        editor_.load(path_a)
    else:
        editor_ = DiffEditor(path_a, path_b)
    asyncio.run(fill3.tui(PROJECT_NAME, editor_))


if __name__ == "__main__":
    main()
