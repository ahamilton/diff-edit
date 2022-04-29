#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import asyncio
import contextlib
import enum
import functools
import os
import string
import sys

import fill3
import fill3.terminal as terminal
import pygments
import pygments.lexers
import pygments.styles
import termstr

import cwcwidth


@functools.lru_cache(maxsize=100)
def highlight_str(line, bg_color, transparency=0.6):
    def blend_style(style):
        return termstr.CharStyle(termstr.blend_color(style.fg_color, bg_color, transparency),
                                 termstr.blend_color(style.bg_color, bg_color, transparency),
                                 is_bold=style.is_bold, is_italic=style.is_italic,
                                 is_underlined=style.is_underlined)
    return termstr.TermStr(line).transform_style(blend_style)


def highlight_line(line):
    return highlight_str(line, termstr.Color.white, 0.8)


NATIVE_STYLE = pygments.styles.get_style_by_name("paraiso-dark")


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
    text = expandtabs(text)
    text = fill3.join("", [termstr.TermStr(
        text, _char_style_for_token_type(token_type, default_bg_color, default_style))
                           for token_type, text in pygments.lex(text, lexer)])
    text_widget = fill3.Text(text, pad_char=termstr.TermStr(" ").bg_color(default_bg_color))
    return fill3.join("\n", text_widget.text)


@functools.lru_cache(maxsize=5000)
def expand_str(str_):
    expanded_str = termstr.TermStr(str_)
    return str_ if expanded_str.data == str_ else expanded_str


class Text:

    def __init__(self, text, padding_char=" "):
        self.padding_char = padding_char
        self.lines = []
        self.max_line_length = None
        lines = [""] if text == "" else text.splitlines()
        if text.endswith("\n"):
            lines.append("")
        self[:] = lines

    def __len__(self):
        return len(self.lines)

    def __getitem__(self, line_index):
        return self.lines[line_index]

    @functools.lru_cache(maxsize=5000)
    def _convert_line(self, line, max_line_length):
        return expand_str(line).ljust(max_line_length)

    def __setitem__(self, key, value):
        if type(key) == int:
            self._replace_lines(slice(key, key + 1), [value])
        else:  # slice
            self._replace_lines(key, value)

    @functools.cached_property
    def max_line_length(self):
        return max(len(expand_str(line)) for line in self.lines)

    def _replace_lines(self, slice_, new_lines):
        self.lines[slice_] = new_lines
        with contextlib.suppress(AttributeError):
            del self.max_line_length

    def insert(self, index, line):
        self._replace_lines(slice(index, index), [line])

    def append(self, line):
        self.insert(len(self.lines), line)

    def get_text(self):
        return "\n".join(self)

    def appearance(self):
        return [self._convert_line(line, self.max_line_length) for line in self.lines]

    def appearance_dimensions(self):
        return (self.max_line_length, len(self.lines))

    def appearance_interval(self, interval):
        start_y, end_y = interval
        return [self._convert_line(line, self.max_line_length)
                for line in self.lines[start_y:end_y]]


class Code(Text):

    def __init__(self, text, path, theme=NATIVE_STYLE):
        self.lexer = pygments.lexers.get_lexer_for_filename(path, text)
        self.theme = theme
        padding_char = None
        Text.__init__(self, text, padding_char)

    @functools.lru_cache(maxsize=5000)
    def _convert_line_themed(self, line, max_line_length, theme):
        if self.padding_char is None:
            self.padding_char = (" " if self.theme is None
                                 else _syntax_highlight(" ", self.lexer, self.theme))
        highlighted_line = (termstr.TermStr(line) if theme is None
                            else _syntax_highlight(line, self.lexer, theme))
        return highlighted_line.ljust(max_line_length, fillchar=self.padding_char)

    def _convert_line(self, line, max_line_length):
        return self._convert_line_themed(line, max_line_length, self.theme)

    def syntax_highlight_all(self):
        self.padding_char = None


class Decor:

    def __init__(self, widget, decorator):
        self.widget = widget
        self.decorator = decorator

    def appearance_for(self, dimensions):
        return self.decorator(self.widget.appearance_for(dimensions))

    def appearance(self):
        return self.decorator(self.widget.appearance())

    def appearance_interval(self, interval):
        return self.decorator(self.widget.appearance_interval(interval))

    def appearance_dimensions(self):
        return self.widget.appearance_dimensions()


def highlight_part(line, start, end):
    return (line[:start] + highlight_str(line[start:end], termstr.Color.white, transparency=0.7) +
            line[end:])


@functools.lru_cache(maxsize=5000)
def expandtabs(text):
    result = []
    for line in text.splitlines(keepends=True):
        parts = line.split("\t")
        if len(parts) == 1:
            result.append(line)
            continue
        result.append(parts[0])
        line_length = cwcwidth.wcswidth(parts[0])
        for part in parts[1:]:
            spacing = 8 - line_length % 8
            result.extend([" " * spacing, part])
            line_length += spacing + cwcwidth.wcswidth(part)
    return "".join(result)


@functools.lru_cache(maxsize=5000)
def expand_str_inverse(str_):
    result = []
    for index, char in enumerate(str_):
        run_length = 8 - len(result) % 8 if char == "\t" else cwcwidth.wcwidth(char)
        result.extend([index] * run_length)
    return result


def _wrap_text_lines(words, width):
    cursor = len(words[0])
    first_word = 0
    for index, word in enumerate(words[1:]):
        if cursor + 1 + len(word) <= width:
            cursor += (1 + len(word))
        else:
            yield words[first_word:index+1]
            first_word = index + 1
            cursor = len(word)
    yield words[first_word:]


def wrap_text(words, width):
    appearance = []
    coords = []
    for index, line in enumerate(_wrap_text_lines(words, width)):
        line = list(line)
        content = fill3.join(" ", line)
        appearance.append(content.center(width))
        cursor = index * width + round((width - len(content)) / 2)
        for word in line:
            coords.append((cursor, cursor + len(word)))
            cursor += (len(word) + 1)
    return appearance, coords


class Line(enum.Enum):
    class_ = enum.auto()
    function = enum.auto()
    endpoint = enum.auto()


@functools.lru_cache(1)
def parts_lines(source, lexer):
    cursor = 0
    line_num = 0
    line_lengths = [len(line) for line in source.splitlines(keepends=True)]
    result = [(Line.endpoint, "top", 0)]
    for position, token_type, text in lexer.get_tokens_unprocessed(source):
        while position >= cursor:
            cursor += line_lengths[line_num]
            line_num += 1
        if token_type == pygments.token.Name.Class:
            result.append((Line.class_, text, line_num - 1))
        elif token_type in [pygments.token.Name.Function, pygments.token.Name.Function.Magic]:
            result.append((Line.function, text, line_num - 1))
    result.append((Line.endpoint, "bottom", line_num - 1))
    return result


COLOR_MAP = {Line.class_: termstr.Color.red,
             Line.function: termstr.Color.green,
             Line.endpoint: termstr.Color.white}


class Parts:

    def __init__(self, editor, source, lexer):
        self.editor = editor
        self.lines = parts_lines(source, lexer)
        self.parts = [termstr.TermStr(text).fg_color(COLOR_MAP[line_type])
                      for line_type, text, line_num in self.lines]
        self.width, self.height = None, None
        self.set_cursor()

    def set_cursor(self):
        for index, (line_type, text, line_num) in enumerate(self.lines):
            if line_num > self.editor.cursor_y:
                self.cursor = index - 1
                break
        else:
            self.cursor = len(self.lines) - 1

    def _move_cursor(self, delta):
        self.cursor = (self.cursor + delta) % len(self.parts)
        self.editor.cursor_x, self.editor.cursor_y = 0, self.lines[self.cursor][2]
        x, y = self.editor.view_widget.portal.position
        self.editor.view_widget.portal.position = x, self.editor.cursor_y - 1

    def cursor_left(self):
        self._move_cursor(-1)

    def cursor_right(self):
        self._move_cursor(1)

    def on_keyboard_input(self, term_code):
        if term_code == terminal.ESC:
            self.editor.parts_widget = None
            self.editor.is_editing = True
            self.editor.center_cursor()
        elif term_code == terminal.LEFT:
            self.cursor_left()
        elif term_code == terminal.RIGHT:
            self.cursor_right()
        fill3.APPEARANCE_CHANGED_EVENT.set()

    def appearance(self):
        width, height = self.dimensions
        parts = self.parts.copy()
        parts[self.cursor] = parts[self.cursor].invert()
        result, coords = wrap_text(parts, width)
        if len(result) > height:
            appearance, coords = wrap_text(parts, width - 1)
            line_num = coords[self.cursor][0] // (width - 1)
            appearance[line_num] = highlight_line(appearance[line_num])
            view_widget = fill3.View.from_widget(fill3.Fixed(appearance))
            if line_num >= height:
                x, y = view_widget.portal.position
                view_widget.portal.position = x, line_num // height * height
                view_widget.portal.limit_scroll(self.dimensions, (width, len(appearance)))
            result = view_widget.appearance_for(self.dimensions)
        else:
            line_num = coords[self.cursor][0] // width
            result[line_num] = highlight_line(result[line_num])
        return result


class Editor:

    TAB_SIZE = 4
    THEMES = [pygments.styles.get_style_by_name(style)
              for style in ["monokai", "fruity", "native"]] + [None]

    def __init__(self, text="", path="Untitled", is_left_aligned=True):
        self.path = os.path.normpath(path)
        self.is_left_aligned = is_left_aligned
        self.set_text(text)
        self.mark = None
        self.clipboard = None
        self.last_width = 100
        self.last_height = 40
        self.is_editing = True
        self.theme_index = 0
        self.is_overwriting = False
        self.previous_term_code = None
        self.last_mouse_position = 0, 0
        self.parts_widget = None

    def screen_x(self, x, y):
        return len(expand_str(self.text_widget[y][:x]))

    def model_x(self, x, y):
        return expand_str_inverse(self.text_widget[y])[x]

    @property
    def cursor_x(self):
        try:
            return self.model_x(self._cursor_x, self.cursor_y)
        except IndexError:
            return len(self.text_widget.lines[self.cursor_y])

    @cursor_x.setter
    def cursor_x(self, x):
        try:
            self._cursor_x = self.screen_x(x, self.cursor_y)
        except IndexError:
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
        self.view_widget.position = position

    def get_selection_interval(self):
        mark_x, mark_y = self.mark
        (start_y, start_x), (end_y, end_x) = sorted(
            [(mark_y, mark_x), (self.cursor_y, self.cursor_x)])
        return (start_x, start_y), (end_x, end_y)

    def add_highlights(self, appearance):
        view_x, view_y = self.view_widget.position
        result = appearance
        if not self.is_editing:
            return result
        cursor_y = self.cursor_y - view_y
        if self.mark is None:
            if 0 <= cursor_y < len(result):
                result[cursor_y] = highlight_line(result[cursor_y])
        else:
            (start_x, start_y), (end_x, end_y) = self.get_selection_interval()
            screen_start_x = self.screen_x(start_x, start_y)
            screen_end_x = self.screen_x(end_x, end_y)
            start_y -= view_y
            end_y -= view_y
            if start_y == end_y:
                result[start_y] = highlight_part(result[start_y], screen_start_x, screen_end_x)
            else:
                if 0 <= start_y < len(result):
                    result[start_y] = highlight_part(result[start_y], screen_start_x,
                                                     len(result[start_y]))
                view_x, view_y = self.view_widget.position
                for line_num in range(max(start_y+1, 0), min(end_y, self.last_height)):
                    if 0 <= line_num < len(result):
                        result[line_num] = highlight_part(result[line_num], 0,
                                                          len(result[line_num]))
                if 0 <= end_y < len(result):
                    result[end_y] = highlight_part(result[end_y], 0, screen_end_x)
        if self.cursor_x >= len(result[0]):
            result = fill3.appearance_resize(result, (self.cursor_x+1, len(result)))
        if 0 <= cursor_y < len(result):
            cursor_line = result[cursor_y]
            screen_x = self.screen_x(self.cursor_x, self.cursor_y)
            screen_x_after = (screen_x + 1 if self._current_character() in ["\t", "\n"] else
                              self.screen_x(self.cursor_x + 1, self.cursor_y))
            result[cursor_y] = (cursor_line[:screen_x] +
                                termstr.TermStr(cursor_line[screen_x:screen_x_after]).invert() +
                                cursor_line[screen_x_after:])
        return result

    def set_text(self, text):
        try:
            self.text_widget = Code(text, self.path)
        except pygments.util.ClassNotFound:  # No lexer for path
            self.text_widget = Text(text)
        self.decor_widget = Decor(self.text_widget,
                                  lambda appearance: self.add_highlights(appearance))
        self.view_widget = fill3.View.from_widget(self.decor_widget)
        self.view_widget.portal.is_scroll_limited = True
        if not self.is_left_aligned:
            self.view_widget.portal.is_left_aligned = False
        self._cursor_x, self._cursor_y = 0, 0
        self.original_text = self.text_widget.lines.copy()
        self.history = []
        self.history_position = 0
        self.add_to_history()

    def load(self, path):
        self.path = os.path.normpath(path)
        with open(path) as file_:
            self.set_text(file_.read())

    def save(self):
        with open(self.path, "w") as file_:
            file_.write(self.text_widget.get_text())
        self.original_text = self.text_widget.lines.copy()

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
        if self.cursor_x == len(self.text_widget.lines[self.cursor_y]):
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
        self.cursor_x, self.cursor_y = 0, min(len(self.text_widget.lines) - 1, new_y)

    def jump_to_start_of_line(self):
        self.cursor_x = 0

    def jump_to_end_of_line(self):
        self.cursor_x = len(self.text_widget.lines[self.cursor_y])

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

    def insert_text(self, text, is_overwriting=False):
        try:
            current_line = self.text_widget[self.cursor_y]
            replace_count = len(text) if is_overwriting else 0
            self.text_widget[self.cursor_y] = (current_line[:self.cursor_x] + text
                                               + current_line[self.cursor_x+replace_count:])
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

    def _indent_level(self):
        if self.cursor_y == 0:
            return 0
        self.jump_to_start_of_line()
        self.cursor_up()
        while self._current_character() in [" ", "\t"]:
            self.cursor_right()
        return self.cursor_x

    def tab_align(self):
        if self.cursor_y == 0:
            return
        indent = self._indent_level()
        self.cursor_down()
        self.jump_to_start_of_line()
        self.set_mark()
        while self._current_character() in [" ", "\t"]:
            self.cursor_right()
        self.delete_selection()
        self.insert_text(" " * indent)

    def insert_tab(self):
        self.insert_text("\t")

    def _line_indent(self, y):
        line = self.text_widget[y]
        for index, char in enumerate(line):
            if char != " ":
                return index
        return 0

    def comment_lines(self):
        if self.mark is None:
            if self.text_widget[self.cursor_y].strip() == "":
                self.text_widget[self.cursor_y] = "# "
                self.cursor_x = 2
            else:
                try:
                    index = self.text_widget[self.cursor_y].index("#")
                    self.cursor_x = index + 1
                except ValueError:  # '#' not in line
                    self.jump_to_end_of_line()
                    self.insert_text("  # ")
        else:
            (start_x, start_y), (end_x, end_y) = self.get_selection_interval()
            if end_x != 0 and not self.cursor_x == len(self.text_widget[end_y]):
                self.enter()
                self.cursor_left()
            if start_x != 0:
                new_line = (self.text_widget[start_y][:start_x] + "# " +
                            self.text_widget[start_y][start_x:])
                self.text_widget[start_y] = new_line
                self._cursor_x = len(new_line)
                start_y += 1
            if end_x != 0:
                end_y += 1
            mid_lines = range(start_y, end_y)
            try:
                min_indent = min(self._line_indent(y) for y in mid_lines
                                 if self.text_widget[y].strip() != "")
            except ValueError:
                pass
            else:
                if all(self.text_widget[y][min_indent:min_indent+2] == "# "
                       or self.text_widget[y].strip() == "" for y in mid_lines):
                    for y in mid_lines:
                        line = self.text_widget[y]
                        if line.strip() != "":
                            self.text_widget[y] = line[:min_indent] + line[min_indent + 2:]
                else:
                    for y in mid_lines:
                        line = self.text_widget[y]
                        if line.strip() != "":
                            self.text_widget[y] = line[:min_indent] + "# " + line[min_indent:]
            self.mark = None

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

    def cycle_syntax_highlighting(self):
        self.theme_index += 1
        if self.theme_index == len(Editor.THEMES):
            self.theme_index = 0
        theme = self.THEMES[self.theme_index]
        self.text_widget.theme = theme
        self.text_widget.syntax_highlight_all()

    def quit(self):
        fill3.SHUTDOWN_EVENT.set()

    def show_parts_list(self):
        self.parts_widget = Parts(self, self.get_text(), self.text_widget.lexer)
        self.is_editing = False
        self.mark = None

    def ring_bell(self):
        if "unittest" not in sys.modules:
            print("\a", end="")

    def add_to_history(self):
        if self.history_position < len(self.history):
            self.history[self.history_position:] = []
        self.history.append((self.text_widget.lines.copy(), self._cursor_x, self._cursor_y))
        self.history_position = len(self.history)

    def undo(self):
        if self.history_position == 0:
            self.ring_bell()
            return
        if self.history_position == len(self.history):
            self.add_to_history()
            self.history_position -= 1
        self.history_position -= 1
        self.text_widget[:], self._cursor_x, self._cursor_y = self.history[self.history_position]

    def redo(self):
        if self.history_position >= len(self.history) - 1:
            self.ring_bell()
            return
        self.history_position += 1
        self.text_widget[:], self._cursor_x, self._cursor_y = self.history[self.history_position]

    def toggle_overwrite(self):
        self.is_overwriting = not self.is_overwriting

    def _work_lines(self):
        if self.mark is None:
            return [self.cursor_y]
        else:
            (start_x, start_y), (end_x, end_y) = self.get_selection_interval()
            return range(start_y + (start_x > 0), end_y + 1 - (end_x == 0))

    def indent(self):
        indent_ = " " * Editor.TAB_SIZE
        for line_num in self._work_lines():
            if self.text_widget[line_num].strip() == "":
                self.text_widget[line_num] = ""
                continue
            self.text_widget[line_num] = indent_ + self.text_widget[line_num]
            if self.cursor_y == line_num:
                self.cursor_x += Editor.TAB_SIZE

    def dedent(self):
        indent_ = " " * Editor.TAB_SIZE
        line_nums = self._work_lines()
        if not all(self.text_widget[line_num].startswith(indent_)
                   or self.text_widget[line_num].strip() == "" for line_num in line_nums):
            self.ring_bell()
            return
        for line_num in line_nums:
            if self.cursor_y == line_num:
                self.cursor_x = max(self.cursor_x - Editor.TAB_SIZE, 0)
            if self.text_widget[line_num].strip() == "":
                self.text_widget[line_num] = ""
                continue
            self.text_widget[line_num] = self.text_widget[line_num][Editor.TAB_SIZE:]

    def abort_command(self):
        self.mark = None
        self.ring_bell()

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
        screen_x = self.screen_x(self.cursor_x, self.cursor_y)
        if screen_x >= view_x + width or screen_x < view_x:
            new_x = screen_x - width // 2
        else:
            new_x = view_x
        self.view_widget.position = max(0, new_x), max(0, new_y)

    def on_keyboard_input(self, term_code):
        if self.parts_widget is not None:
            self.parts_widget.on_keyboard_input(term_code)
            return
        if action := (Editor.KEY_MAP.get((self.previous_term_code, term_code))
                      or Editor.KEY_MAP.get(term_code)):
            try:
                if action in Editor.CHANGE_ACTIONS:
                    self.add_to_history()
                action(self)
            except IndexError:
                self.ring_bell()
        elif not (len(term_code) == 1 and ord(term_code) < 32):
            self.add_to_history()
            self.insert_text(term_code, is_overwriting=self.is_overwriting)
        self.previous_term_code = term_code
        self.follow_cursor()
        fill3.APPEARANCE_CHANGED_EVENT.set()

    def scroll(self, dx, dy):
        view_x, view_y = self.scroll_position
        self.scroll_position = max(0, view_x + dx), max(0, view_y + dy)

    def on_mouse_press(self, x, y):
        view_x, view_y = self.view_widget.position
        self.cursor_y = min(y + view_y - 1, len(self.text_widget) - 1)
        self._cursor_x = x + view_x
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

    def appearance(self):
        return self.decor_widget.appearance()

    _HEADER_STYLE = termstr.CharStyle(fg_color=termstr.Color.white, bg_color=termstr.Color.green)

    @functools.lru_cache(maxsize=100)
    def get_header(self, path, width, cursor_x, cursor_y, is_changed):
        change_marker = "*" if is_changed else ""
        cursor_position = f"Line {cursor_y+1} Column {cursor_x+1:<3}"
        path_part = (path + change_marker).ljust(width - len(cursor_position) - 2)
        return (termstr.TermStr(" " + path_part, self._HEADER_STYLE).bold() +
                termstr.TermStr(cursor_position + " ", self._HEADER_STYLE))

    def appearance_for(self, dimensions):
        width, height = dimensions
        if self.parts_widget is None:
            parts_appearance = []
        else:
            self.parts_widget.dimensions = width, height // 4
            parts_appearance = self.parts_widget.appearance()
        self.parts_height = len(parts_appearance)
        is_changed = self.text_widget.lines != self.original_text
        header = self.get_header(self.path, width, self.cursor_x, self.cursor_y, is_changed)
        self.last_width = width
        self.last_height = height
        body_appearance = self.view_widget.appearance_for((width, height-len(parts_appearance)-1))
        return [header] + parts_appearance + body_appearance

    KEY_MAP = {
        (terminal.CTRL_X, terminal.CTRL_S): save, terminal.BACKSPACE: backspace,
        terminal.LEFT: cursor_left, terminal.CTRL_B: cursor_left, terminal.RIGHT: cursor_right,
        terminal.CTRL_F: cursor_right, terminal.UP: cursor_up, terminal.CTRL_P: cursor_up,
        terminal.DOWN: cursor_down, terminal.CTRL_N: cursor_down,
        terminal.CTRL_A: jump_to_start_of_line, terminal.CTRL_E: jump_to_end_of_line,
        terminal.CTRL_O: open_line, terminal.ENTER: enter, terminal.CTRL_SPACE: set_mark,
        terminal.CTRL_G: drop_highlight, terminal.PAGE_DOWN: page_down, terminal.CTRL_V: page_down,
        terminal.PAGE_UP: page_up, terminal.ALT_v: page_up, terminal.ALT_w: copy_selection,
        terminal.CTRL_W: delete_selection, terminal.CTRL_D: delete_character,
        terminal.DELETE: delete_character, terminal.ALT_d: delete_right,
        terminal.CTRL_Y: paste_from_clipboard, terminal.CTRL_UP: jump_to_block_start,
        terminal.CTRL_DOWN: jump_to_block_end, terminal.ALT_f: next_word,
        terminal.CTRL_RIGHT: next_word, terminal.ALT_RIGHT: next_word,
        terminal.ALT_b: previous_word, terminal.CTRL_LEFT: previous_word,
        terminal.ALT_LEFT: previous_word, terminal.ALT_BACKSPACE: delete_backward,
        terminal.ALT_CARROT: join_lines, terminal.ALT_h: highlight_block,
        terminal.ALT_H: highlight_block, terminal.CTRL_R: syntax_highlight_all,
        terminal.CTRL_L: center_cursor, terminal.ALT_SEMICOLON: comment_lines,
        terminal.ALT_c: cycle_syntax_highlighting, (terminal.CTRL_X, terminal.CTRL_C): quit,
        terminal.ESC: show_parts_list, terminal.CTRL_K: delete_line, terminal.TAB: tab_align,
        (terminal.CTRL_Q, terminal.TAB): insert_tab, terminal.CTRL_UNDERSCORE: redo,
        terminal.CTRL_Z: undo, terminal.CTRL_G: abort_command, terminal.INSERT: toggle_overwrite,
        (terminal.CTRL_C, ">"): indent, (terminal.CTRL_C, "<"): dedent}

    CHANGE_ACTIONS = {backspace, open_line, enter, delete_selection, delete_character, delete_right,
                      paste_from_clipboard, delete_backward, join_lines, comment_lines, delete_line,
                      tab_align, insert_tab, indent, dedent}


def main():
    editor = Editor()
    editor.load(sys.argv[1])
    asyncio.run(fill3.tui("Editor", editor))


if __name__ == "__main__":
    main()
