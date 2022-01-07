#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import asyncio
import contextlib
import functools
import string
import sys

import fill3
import fill3.terminal as terminal
import pygments
import pygments.lexers
import pygments.styles
import termstr


@functools.lru_cache(maxsize=100)
def highlight_str(line, bg_color, transparency=0.6):
    def blend_style(style):
        return termstr.CharStyle(termstr.blend_color(style.fg_color, bg_color, transparency),
                                 termstr.blend_color(style.bg_color, bg_color, transparency),
                                 is_bold=style.is_bold, is_italic=style.is_italic,
                                 is_underlined=style.is_underlined)
    return termstr.TermStr(line).transform_style(blend_style)


PYTHON_LEXER = pygments.lexers.get_lexer_by_name("python")
# NATIVE_STYLE = pygments.styles.get_style_by_name("monokai")
# NATIVE_STYLE = pygments.styles.get_style_by_name("native")
NATIVE_STYLE = pygments.styles.get_style_by_name("paraiso-dark")
# NATIVE_STYLE = pygments.styles.get_style_by_name("fruity")
# NATIVE_STYLE = pygments.styles.get_style_by_name("solarizedlight")


def _syntax_highlight(text, lexer, style):
    @functools.lru_cache(maxsize=500)
    def _parse_rgb(hex_rgb):
        if hex_rgb.startswith("#"):
            hex_rgb = hex_rgb[1:]
        return tuple(int("0x" + hex_rgb[index:index+2], base=16) for index in [0, 2, 4])

    @functools.lru_cache(maxsize=500)
    def _char_style_for_token_type(token_type, default_bg_color, default_style):
        try:
            token_style = style.style_for_token(token_type)
        except KeyError:
            return default_style
        fg_color = (termstr.Color.black if token_style["color"] is None
                    else _parse_rgb(token_style["color"]))
        bg_color = (default_bg_color if token_style["bgcolor"] is None
                    else _parse_rgb(token_style["bgcolor"]))
        return termstr.CharStyle(fg_color, bg_color, token_style["bold"], token_style["italic"],
                                 token_style["underline"])
    default_bg_color = _parse_rgb(style.background_color)
    default_style = termstr.CharStyle(bg_color=default_bg_color)
    text = fill3.join("", [termstr.TermStr(
        text, _char_style_for_token_type(token_type, default_bg_color, default_style))
                           for token_type, text in pygments.lex(text, lexer)])
    text_widget = fill3.Text(text, pad_char=termstr.TermStr(" ").bg_color(default_bg_color))
    return fill3.join("\n", text_widget.text)


class Text:

    def __init__(self, text, pad_char=" "):
        self.padding_char = " "
        self.text, self.actual_text, self.max_line_length = [], [], 0
        lines = [""] if text == "" else text.splitlines()
        if text.endswith("\n"):
            lines.append("")
        self[:] = lines

    def __len__(self):
        return len(self.text)

    def __getitem__(self, line_index):
        return self.actual_text[line_index]

    def _convert_line(self, line, max_line_length):
        return line.ljust(max_line_length)

    def __setitem__(self, key, value):
        if type(key) == int:
            self._replace_lines(slice(key, key + 1), [value])
        else:  # slice
            self._replace_lines(key, value)

    def _replace_lines(self, slice_, new_lines):
        new_lengths = [len(line) for line in new_lines]
        try:
            max_new_lengths = max(new_lengths)
        except ValueError:
            max_new_lengths = 0
        if max_new_lengths > self.max_line_length:
            padding = self.padding_char * (max_new_lengths - self.max_line_length)
            self.text = [line + padding for line in self.text]
            self.max_line_length = max_new_lengths
        converted_lines = [self._convert_line(line, self.max_line_length) for line in new_lines]
        self.text[slice_], self.actual_text[slice_] = converted_lines, new_lines
        new_max_line_length = max(len(line) for line in self.actual_text)
        if new_max_line_length < self.max_line_length:
            clip_width = self.max_line_length - new_max_line_length
            self.text = [line[:-clip_width] for line in self.text]
            self.max_line_length = new_max_line_length

    def insert(self, index, line):
        self._replace_lines(slice(index, index), [line])

    def append(self, line):
        self.insert(len(self.text), line)

    def get_text(self):
        return "\n".join(self)

    def appearance_min(self):
        return self.text

    def appearance(self, dimensions):
        return fill3.appearance_resize(self.appearance_min(), dimensions)


class Code(Text):

    def __init__(self, text, lexer=PYTHON_LEXER, theme=NATIVE_STYLE):
        self.lexer = lexer
        self.theme = theme
        self.padding_char = _syntax_highlight(" ", lexer, theme)
        Text.__init__(self, text)

    def _convert_line(self, line, max_line_length):
        return (termstr.TermStr(line.ljust(max_line_length)) if self.theme is None
                else _syntax_highlight(line.ljust(max_line_length), self.lexer, self.theme))

    def syntax_highlight_all(self):
        if self.theme is None:
            self.text = [termstr.TermStr(line.ljust(self.max_line_length))
                         for line in self.get_text().splitlines()]
        else:
            self.padding_char = _syntax_highlight(" ", self.lexer, self.theme)
            highlighted = _syntax_highlight(self.get_text(), self.lexer, self.theme)
            self.text = [line.ljust(self.max_line_length) for line in highlighted.splitlines()]


class Decor:

    def __init__(self, widget, decorator):
        self.widget = widget
        self.decorator = decorator

    def appearance(self, dimensions):
        return self.decorator(self.widget.appearance(dimensions))

    def appearance_min(self):
        return self.decorator(self.widget.appearance_min())


def highlight_part(line, start, end):
    return (line[:start] + highlight_str(line[start:end], termstr.Color.white, transparency=0.7) +
            line[end:])


def add_highlights(self, appearance):
    result = appearance.copy()
    if not self.is_editing:
        return result
    if self.mark is None:
        result[self.cursor_y] = highlight_str(result[self.cursor_y], termstr.Color.white, 0.8)
    else:
        (start_x, start_y), (end_x, end_y) = self.get_selection_interval()
        if start_y == end_y:
            result[start_y] = highlight_part(result[start_y], start_x, end_x)
        else:
            result[start_y] = highlight_part(result[start_y], start_x, len(result[start_y]))
            view_x, view_y = self.view_widget.position
            for line_num in range(max(start_y+1, view_y), min(end_y, view_y + self.last_height)):
                result[line_num] = highlight_part(result[line_num], 0, len(result[line_num]))
            result[end_y] = highlight_part(result[end_y], 0, end_x)
    if self.cursor_x >= len(result[0]):
        result = fill3.appearance_resize(result, (self.cursor_x+1, len(result)))
    cursor_line = result[self.cursor_y]
    result[self.cursor_y] = (cursor_line[:self.cursor_x] +
                             termstr.TermStr(cursor_line[self.cursor_x]).invert() +
                             cursor_line[self.cursor_x+1:])
    return result


class Editor:

    THEMES = [pygments.styles.get_style_by_name(style)
              for style in ["monokai", "fruity", "native"]] + [None]

    def __init__(self, text="", path="Untitled"):
        self.set_text(text)
        self.path = path
        self.mark = None
        self.clipboard = None
        self.last_width = 100
        self.last_height = 40
        self.is_editing = True
        self.theme_index = 0
        self.previous_term_code = None

    @property
    def cursor_x(self):
        line_length = len(self.text_widget.actual_text[self.cursor_y])
        return min(self._cursor_x, line_length)

    @cursor_x.setter
    def cursor_x(self, x):
        self._cursor_x = x

    @property
    def cursor_y(self):
        return self._cursor_y

    @cursor_y.setter
    def cursor_y(self, y):
        if y < 0 or y >= len(self.text_widget):
            raise IndexError
        self._cursor_y = y

    @property
    def scroll_position(self):
        return self.view_widget.position

    @scroll_position.setter
    def scroll_position(self, position):
        x, y = position
        # text_width = self.text_widget.max_line_length
        # if x < 0:
        #     new_x = 0
        # elif x > text_width - self.last_width + 2:
        #     new_x = max(text_width - self.last_width + 2, 0)
        # else:
        #     new_x = x
        # if y < 0:
        #     new_y = 0
        # elif y > len(self.text_widget) - self.last_height + 2:
        #     new_y = max(len(self.text_widget) - self.last_height + 2, 0)
        # else:
        #     new_y = y
        new_x, new_y = max(x, 0), y
        self.view_widget.position = new_x, new_y
        view_x, view_y = self.view_widget.position
        new_cursor_y = self.cursor_y + y - view_y
        self.cursor_y = max(0, min(new_cursor_y, len(self.text_widget) - 1))

    def get_selection_interval(self):
        mark_x, mark_y = self.mark
        (start_y, start_x), (end_y, end_x) = sorted(
            [(mark_y, mark_x), (self.cursor_y, self.cursor_x)])
        return (start_x, start_y), (end_x, end_y)

    def set_text(self, text):
        self.text_widget = Code(text)
        # self.text_widget = Text(text)
        self.decor_widget = Decor(self.text_widget,
                                  lambda appearance: add_highlights(self, appearance))
        self.view_widget = fill3.View.from_widget(self.decor_widget)
        self.cursor_x, self.cursor_y = 0, 0
        self.original_text = self.text_widget.actual_text.copy()

    def prefix(self):
        pass

    def load(self, path):
        with open(path) as file_:
            self.set_text(file_.read())
        self.path = path

    def save(self):
        if self.previous_term_code == terminal.CTRL_X:
            with open(self.path, "w") as file_:
                file_.write(self.text_widget.get_text())
            self.original_text = self.text_widget.actual_text.copy()

    def backspace(self):
        if self.cursor_x == 0:
            if self.cursor_y != 0:
                self.set_mark()
                self.cursor_left()
                self.delete_selection()
        else:
            line = self.text_widget[self.cursor_y]
            new_line = line[:self.cursor_x-1] + line[self.cursor_x:]
            self.cursor_x -= 1
            self.text_widget[self.cursor_y] = new_line

    def cursor_left(self):
        if self.cursor_x == 0:
            self.cursor_up()
            self.jump_to_end_of_line()
        else:
            self.cursor_x -= 1

    def cursor_right(self):
        if self.cursor_x == len(self.text_widget.actual_text[self.cursor_y]):
            self.cursor_down()
            self.jump_to_start_of_line()
        else:
            self.cursor_x += 1

    def cursor_up(self):
        self.cursor_y -= 1

    def cursor_down(self):
        self.cursor_y += 1

    def page_up(self):
        new_y = self.cursor_y - self.last_height // 2
        self.cursor_x, self.cursor_y = 0, max(0, new_y)

    def page_down(self):
        new_y = self.cursor_y + self.last_height // 2
        self.cursor_x, self.cursor_y = 0, min(len(self.text_widget.text) - 1, new_y)

    def jump_to_start_of_line(self):
        self.cursor_x = 0

    def jump_to_end_of_line(self):
        self.cursor_x = len(self.text_widget.actual_text[self.cursor_y])

    def open_line(self):
        line = self.text_widget[self.cursor_y]
        self.text_widget[self.cursor_y:self.cursor_y+1] = \
            [line[:self.cursor_x], line[self.cursor_x:]]

    def enter(self):
        self.open_line()
        self.cursor_x, self.cursor_y = 0, self.cursor_y + 1

    def set_mark(self):
        self.mark = self.cursor_x, self.cursor_y

    def drop_highlight(self):
        self.mark = None

    def copy_selection(self):
        if self.mark is not None:
            (start_x, start_y), (end_x, end_y) = self.get_selection_interval()
            selection = [self.text_widget[line_num] for line_num in range(start_y, end_y+1)]
            selection[-1] = selection[-1][:end_x]
            selection[0] = selection[0][start_x:]
            self.clipboard = selection
            self.mark = None

    def delete_selection(self):
        if self.mark is not None:
            (start_x, start_y), (end_x, end_y) = self.get_selection_interval()
            self.copy_selection()
            start_line = self.text_widget[start_y]
            end_line = self.text_widget[end_y]
            new_line = start_line[:start_x] + end_line[end_x:]
            self.text_widget[start_y:end_y+1] = [new_line]
            self.cursor_x, self.cursor_y = start_x, start_y

    def insert_text(self, text):
        try:
            current_line = self.text_widget[self.cursor_y]
            new_line = current_line[:self.cursor_x] + text + current_line[self.cursor_x:]
            self.text_widget[self.cursor_y] = new_line
        except IndexError:
            self.text_widget.append(text)
        self.cursor_x += len(text)

    def delete_character(self):
        self.cursor_right()
        self.backspace()

    def delete_right(self):
        self.set_mark()
        self.next_word()
        self.delete_selection()

    def paste_from_clipboard(self):
        if self.clipboard is not None:
            for line in self.clipboard[:-1]:
                self.insert_text(line)
                self.enter()
            self.insert_text(self.clipboard[-1])

    def _is_on_empty_line(self):
        return self.text_widget[self.cursor_y].strip() == ""

    def _jump_to_block_edge(self, direction_func):
        self.jump_to_start_of_line()
        while self._is_on_empty_line():
            direction_func()
        while not self._is_on_empty_line():
            direction_func()

    def jump_to_block_start(self):
        return self._jump_to_block_edge(self.cursor_up)

    def jump_to_block_end(self):
        return self._jump_to_block_edge(self.cursor_down)

    WORD_CHARS = string.ascii_letters + string.digits

    def _current_character(self):
        try:
            return self.text_widget[self.cursor_y][self.cursor_x]
        except IndexError:
            return "\n"

    def next_word(self):
        while self._current_character() not in Editor.WORD_CHARS:
            self.cursor_right()
        while self._current_character() in Editor.WORD_CHARS:
            self.cursor_right()

    def previous_word(self):
        self.cursor_left()
        while self._current_character() not in Editor.WORD_CHARS:
            self.cursor_left()
        while self._current_character() in Editor.WORD_CHARS:
            self.cursor_left()
        self.cursor_right()

    def delete_backward(self):
        self.set_mark()
        with contextlib.suppress(IndexError):
            self.previous_word()
        self.delete_selection()

    def delete_line(self):
        empty_selection = self.text_widget[self.cursor_y][self.cursor_x:].strip() == ""
        self.set_mark()
        self.jump_to_end_of_line()
        self.delete_selection()
        if empty_selection:
            self.delete_character()

    def join_lines(self):
        if self.cursor_y == 0:
            self.jump_to_start_of_line()
        else:
            left_part = self.text_widget[self.cursor_y-1].rstrip()
            right_part = self.text_widget[self.cursor_y].lstrip()
            new_line = right_part if left_part == "" else (left_part + " " + right_part)
            self.text_widget[self.cursor_y-1:self.cursor_y+1] = [new_line]
            self.cursor_x, self.cursor_y = len(left_part), self.cursor_y - 1

    def highlight_block(self):
        self.jump_to_block_end()
        self.set_mark()
        self.jump_to_block_start()

    def syntax_highlight_all(self):
        self.text_widget.syntax_highlight_all()

    def center_cursor(self):
        view_x, view_y = self.view_widget.position
        new_y = max(0, self.cursor_y - self.last_height // 2)
        self.view_widget.position = view_x, new_y

    def comment_highlighted(self):
        pass

    def cycle_syntax_highlighting(self):
        self.theme_index += 1
        if self.theme_index == len(Editor.THEMES):
            self.theme_index = 0
        theme = self.THEMES[self.theme_index]
        self.text_widget.theme = theme
        self.text_widget.syntax_highlight_all()

    def quit(self):
        fill3.SHUTDOWN_EVENT.set()

    def ctrl_c(self):
        if self.previous_term_code == terminal.CTRL_X:
            self.quit()

    def get_text(self):
        return self.text_widget.get_text()

    def follow_cursor(self):
        height = self.last_height
        height -= 2  # header + scrollbar
        width = self.last_width
        width -= 1  # scrollbar
        view_x, view_y = self.view_widget.position
        if self.cursor_y >= view_y + height or self.cursor_y < view_y:
            new_y = self.cursor_y - height // 2
        else:
            new_y = view_y
        if self.cursor_x >= view_x + width or self.cursor_x < view_x:
            new_x = self.cursor_x - width // 2
        else:
            new_x = view_x
        self.view_widget.position = max(0, new_x), max(0, new_y)

    _PRINTABLE = string.printable[:-5]

    def on_keyboard_input(self, term_code):
        if term_code in Editor.KEY_MAP:
            with contextlib.suppress(IndexError):
                Editor.KEY_MAP[term_code](self)
        elif term_code in self._PRINTABLE:
            self.insert_text(term_code)
        else:
            self.insert_text(repr(term_code))
        self.previous_term_code = term_code
        self.follow_cursor()
        fill3.APPEARANCE_CHANGED_EVENT.set()

    def scroll(self, dx, dy):
        view_x, view_y = self.scroll_position
        self.scroll_position = view_x + dx, view_y + dy

    def on_mouse_press(self, x, y):
        view_x, view_y = self.view_widget.position
        self.cursor_x = x + view_x
        self.cursor_y = min(y + view_y - 1, len(self.text_widget) - 1)
        self.last_mouse_position = (x, y)

    def on_mouse_drag(self, x, y):
        last_x, last_y = self.last_mouse_position
        self.scroll(last_x - x, last_y - y)
        self.last_mouse_position = (x, y)

    def on_mouse_input(self, term_code):
        action, flag, x, y = terminal.decode_mouse_input(term_code)
        if action == terminal.MOUSE_PRESS:
            self.on_mouse_press(x, y)
        elif action == terminal.MOUSE_DRAG:
            self.on_mouse_drag(x, y)
        self.follow_cursor()
        fill3.APPEARANCE_CHANGED_EVENT.set()

    def appearance_min(self):
        return self.decor_widget.appearance_min()

    _HEADER_STYLE = termstr.CharStyle(fg_color=termstr.Color.white, bg_color=termstr.Color.green)

    @functools.lru_cache(maxsize=100)
    def get_header(self, path, width, cursor_x, cursor_y, is_changed):
        change_marker = "*" if is_changed else ""
        cursor_position = f"Line {cursor_y+1} Column {cursor_x+1:<3}"
        path_part = (path + change_marker).ljust(width - len(cursor_position) - 2)
        return (termstr.TermStr(" " + path_part, self._HEADER_STYLE).bold() +
                termstr.TermStr(cursor_position + " ", self._HEADER_STYLE))

    def appearance(self, dimensions):
        width, height = dimensions
        is_changed = self.text_widget.actual_text != self.original_text
        header = self.get_header(self.path, width, self.cursor_x, self.cursor_y, is_changed)
        self.last_width = width
        self.last_height = height
        result = [header] + self.view_widget.appearance((width, height - 1))
        return result

    KEY_MAP = {
        terminal.CTRL_S: save, terminal.BACKSPACE: backspace, terminal.LEFT: cursor_left,
        terminal.CTRL_B: cursor_left, terminal.RIGHT: cursor_right, terminal.CTRL_F: cursor_right,
        terminal.UP: cursor_up, terminal.CTRL_P: cursor_up, terminal.DOWN: cursor_down,
        terminal.CTRL_N: cursor_down, terminal.CTRL_A: jump_to_start_of_line,
        terminal.CTRL_E: jump_to_end_of_line, terminal.CTRL_O: open_line, terminal.ENTER: enter,
        terminal.CTRL_SPACE: set_mark, terminal.CTRL_G: drop_highlight,
        terminal.PAGE_DOWN: page_down, terminal.CTRL_V: page_down, terminal.PAGE_UP: page_up,
        terminal.ALT_v: page_up, terminal.ALT_w: copy_selection, terminal.CTRL_W: delete_selection,
        terminal.CTRL_D: delete_character, terminal.DELETE: delete_character,
        terminal.ALT_d: delete_right, terminal.CTRL_Y: paste_from_clipboard,
        terminal.CTRL_UP: jump_to_block_start, terminal.CTRL_DOWN: jump_to_block_end,
        terminal.ALT_f: next_word, terminal.CTRL_RIGHT: next_word, terminal.ALT_RIGHT: next_word,
        terminal.ALT_b: previous_word, terminal.CTRL_LEFT: previous_word,
        terminal.ALT_LEFT: previous_word, terminal.ALT_BACKSPACE: delete_backward,
        terminal.ALT_CARROT: join_lines, terminal.ALT_h: highlight_block,
        terminal.ALT_H: highlight_block, terminal.CTRL_R: syntax_highlight_all,
        terminal.CTRL_L: center_cursor, terminal.ALT_SEMICOLON: comment_highlighted,
        terminal.ALT_c: cycle_syntax_highlighting, terminal.CTRL_X: prefix, terminal.ESC: quit,
        terminal.CTRL_C: ctrl_c, terminal.CTRL_K: delete_line}


def main():
    editor = Editor()
    editor.load(sys.argv[1])
    asyncio.run(fill3.tui("Editor", editor), debug=True)


if __name__ == "__main__":
    main()
