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
import lscolors
import pygments
import pygments.lexers
import pygments.lexers.special
import pygments.styles
import termstr

import cwcwidth


@functools.lru_cache(maxsize=100)
def highlight_str(line, bg_color, transparency=0.6):
    def blend_style(style):
        return termstr.CharStyle(termstr.blend_color(style.fg_rgb_color, bg_color, transparency),
                                 termstr.blend_color(style.bg_rgb_color, bg_color, transparency),
                                 is_bold=style.is_bold, is_italic=style.is_italic,
                                 is_underlined=style.is_underlined)
    return termstr.TermStr(line).transform_style(blend_style)


@functools.lru_cache(maxsize=500)
def parse_rgb(hex_rgb):
    if hex_rgb.startswith("#"):
        hex_rgb = hex_rgb[1:]
    return tuple(int("0x" + hex_rgb[index:index+2], base=16) for index in [0, 2, 4])


@functools.cache
def is_bright_theme(theme):
    return sum(parse_rgb(theme.background_color)) > (255 * 3 / 2)


def highlight_line(line, theme=None):
    blend_color = (termstr.Color.black if theme is not None and is_bright_theme(theme)
                   else termstr.Color.white)
    return highlight_str(line, blend_color, 0.8)


NATIVE_STYLE = pygments.styles.get_style_by_name("paraiso-dark")


@functools.lru_cache(maxsize=500)
def char_style_for_token_type(token_type, style):
    default_bg_color = parse_rgb(style.background_color)
    default_style = termstr.CharStyle(bg_color=default_bg_color)
    try:
        token_style = style.style_for_token(token_type)
    except KeyError:
        return default_style
    fg_color = (termstr.Color.black if token_style["color"] is None
                else parse_rgb(token_style["color"]))
    bg_color = (default_bg_color if token_style["bgcolor"] is None
                else parse_rgb(token_style["bgcolor"]))
    return termstr.CharStyle(fg_color, bg_color, token_style["bold"], token_style["italic"],
                             token_style["underline"])


def syntax_highlight(text, lexer, style):
    text = expandtabs(text)
    text = termstr.join("", [termstr.TermStr(text, char_style_for_token_type(token_type, style))
                             for token_type, text in pygments.lex(text, lexer)])
    bg_color = parse_rgb(style.background_color)
    text_widget = fill3.Text(text, pad_char=termstr.TermStr(" ").bg_color(bg_color))
    return termstr.join("\n", text_widget.text)


@functools.lru_cache(maxsize=5000)
def expand_str(str_):
    expanded_str = termstr.TermStr(str_)
    return str_ if expanded_str.data == str_ else expanded_str


class Text:

    def __init__(self, text):
        lines = [""] if text == "" else text.splitlines()
        if text.endswith("\n"):
            lines.append("")
        self.version = 0
        self.lines = lines

    def __len__(self):
        return len(self.lines)

    @functools.cached_property
    def max_line_length(self):
        return max(len(expand_str(line)) for line in self.lines)

    def _new_line(self, line):
        self.max_line_length = max(self.max_line_length, len(expand_str(line)))
        self.version += 1

    def __getitem__(self, line_index):
        return self.lines[line_index]

    def __setitem__(self, key, value):
        if type(key) == int and \
           len(expand_str(self.lines[key])) != self.max_line_length:
            self.lines[key] = value
            self._new_line(value)
        else:
            self.lines[key] = value
            with contextlib.suppress(AttributeError):
                del self.max_line_length
            self.version += 1

    def insert(self, index, line):
        self.lines.insert(index, line)
        self._new_line(line)

    def append(self, line):
        self.lines.append(line)
        self._new_line(line)

    def get_text(self):
        return "\n".join(self)

    @staticmethod
    @functools.lru_cache(maxsize=5000)
    def _convert_line(line, max_line_length):
        return expand_str(line).ljust(max_line_length)

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
        try:
            self.lexer = pygments.lexers.get_lexer_for_filename(path, text)
        except pygments.util.ClassNotFound:
            self.lexer = pygments.lexers.special.TextLexer()
        self.theme = theme
        Text.__init__(self, text)

    @functools.lru_cache(maxsize=5000)
    def _convert_line_themed(self, line, max_line_length, theme):
        padding_char = syntax_highlight(" ", self.lexer, self.theme)
        highlighted_line = syntax_highlight(line, self.lexer, theme)
        return highlighted_line.ljust(max_line_length, fillchar=padding_char)

    def _convert_line(self, line, max_line_length):
        return self._convert_line_themed(line, max_line_length, self.theme)


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


def wrap_text(words, width, pad_char=" "):
    appearance = []
    coords = []
    for index, line in enumerate(_wrap_text_lines(words, width)):
        line = list(line)
        content = termstr.join(pad_char, line)
        appearance.append(content.center(width, pad_char))
        cursor = index * width + round((width - len(content)) / 2)
        for word in line:
            coords.append((cursor, cursor + len(word)))
            cursor += (len(word) + 1)
    return appearance, coords


@functools.lru_cache(100)
def parts_lines(source, lexer, theme):
    cursor = 0
    line_num = 0
    line_lengths = [len(line) for line in source.splitlines(keepends=True)]
    white_style = termstr.CharStyle(fg_color=termstr.Color.white)
    result = [(termstr.TermStr("top", white_style), 0)]
    token_types = {pygments.token.Name.Class, pygments.token.Name.Function,
                   pygments.token.Name.Function.Magic}
    if lexer is None:
        line_num = len(source.splitlines())
    else:
        for position, token_type, text in lexer.get_tokens_unprocessed(source):
            while position >= cursor:
                cursor += line_lengths[line_num]
                line_num += 1
            if token_type in token_types:
                char_style = char_style_for_token_type(token_type, theme)
                result.append((termstr.TermStr(text, char_style), line_num - 1))
    result.append((termstr.TermStr("bottom", white_style), line_num - 1))
    return result


class Parts:

    def __init__(self, editor, source, lexer):
        self.editor = editor
        self.source = source
        self.lexer = lexer
        self.lines = parts_lines(source, lexer, editor.text_widget.theme)
        self.width, self.height = None, None
        self.is_focused = True
        self.set_cursor()

    def set_cursor(self):
        for index, (text, line_num) in enumerate(self.lines):
            if line_num > self.editor.cursor_y:
                self.cursor = index - 1
                break
        else:
            self.cursor = len(self.lines) - 1

    def _move_cursor(self, delta):
        self.cursor = (self.cursor + delta) % len(self.lines)
        self.editor.cursor_x, self.editor.cursor_y = 0, self.lines[self.cursor][1]
        x, y = self.editor.view_widget.portal.position
        self.editor.view_widget.portal.position = x, self.editor.cursor_y - 1

    def escape_parts_browser(self):
        self.editor.parts_widget = None
        self.editor.is_editing = True
        self.editor.center_cursor()

    def cursor_left(self):
        self._move_cursor(-1)

    def cursor_right(self):
        self._move_cursor(1)

    def on_keyboard_input(self, term_code):
        match term_code:
            case terminal.ESC:
                self.escape_parts_browser()
            case terminal.DOWN:
                self.escape_parts_browser()
            case terminal.LEFT:
                self.cursor_left()
            case terminal.RIGHT:
                self.cursor_right()
        fill3.APPEARANCE_CHANGED_EVENT.set()

    def appearance(self):
        width, height = self.dimensions
        lines = parts_lines(self.source, self.lexer, self.editor.text_widget.theme)
        parts = [text for text, line_num in lines]
        parts[self.cursor] = parts[self.cursor].invert()
        pad_char = syntax_highlight(" ", self.editor.text_widget.lexer,
                                    self.editor.text_widget.theme)
        result, coords = wrap_text(parts, width, pad_char)
        if len(result) > height:
            appearance, coords = wrap_text(parts, width - 1, pad_char)
            line_num = coords[self.cursor][0] // (width - 1)
            if self.is_focused:
                appearance[line_num] = highlight_line(appearance[line_num],
                                                      self.editor.text_widget.theme)
            view_widget = fill3.View.from_widget(fill3.Fixed(appearance))
            if line_num >= height:
                x, y = view_widget.portal.position
                view_widget.portal.position = x, line_num // height * height
                view_widget.portal.limit_scroll(self.dimensions, (width, len(appearance)))
            result = view_widget.appearance_for(self.dimensions)
        else:
            if self.is_focused:
                line_num = coords[self.cursor][0] // width
                result[line_num] = highlight_line(result[line_num], self.editor.text_widget.theme)
        fg_color = termstr.Color.grey_100
        bg_color = parse_rgb(self.editor.text_widget.theme.background_color)
        result.append(termstr.TermStr("???").bg_color(bg_color).fg_color(fg_color) * width)
        return result


class TextEditor:

    TAB_SIZE = 4
    THEMES = [pygments.styles.get_style_by_name(style)
              for style in ["material", "monokai", "fruity", "native", "inkpot", "solarized-light",
                             "manni", "gruvbox-light", "perldoc", "zenburn",  "friendly",]]

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

    def _highlight_selection(self, appearance):
        (start_x, start_y), (end_x, end_y) = self.get_selection_interval()
        screen_start_x = self.screen_x(start_x, start_y)
        screen_end_x = self.screen_x(end_x, end_y)
        view_x, view_y = self.view_widget.position
        start_y -= view_y
        end_y -= view_y
        if start_y == end_y:
            appearance[start_y] = highlight_part(appearance[start_y], screen_start_x, screen_end_x)
        else:
            if 0 <= start_y < len(appearance):
                appearance[start_y] = highlight_part(appearance[start_y], screen_start_x,
                                                     len(appearance[start_y]))
            for line_num in range(max(start_y+1, 0), min(end_y, self.last_height)):
                if 0 <= line_num < len(appearance):
                    appearance[line_num] = highlight_part(appearance[line_num], 0,
                                                          len(appearance[line_num]))
            if 0 <= end_y < len(appearance):
                appearance[end_y] = highlight_part(appearance[end_y], 0, screen_end_x)

    def _highlight_cursor(self, appearance, cursor_y):
        cursor_line = appearance[cursor_y]
        screen_x = self.screen_x(self.cursor_x, self.cursor_y)
        screen_x_after = (screen_x + 1 if self._current_character() in ["\t", "\n"] else
                          self.screen_x(self.cursor_x + 1, self.cursor_y))
        appearance[cursor_y] = (cursor_line[:screen_x] +
                                termstr.TermStr(cursor_line[screen_x:screen_x_after]).invert() +
                                cursor_line[screen_x_after:])

    def _add_highlights(self, appearance):
        view_x, view_y = self.view_widget.position
        cursor_y = self.cursor_y - view_y
        if 0 <= cursor_y < len(appearance):
            self._highlight_cursor(appearance, cursor_y)
        if not self.is_editing:
            return appearance
        if self.mark is None:
            if 0 <= cursor_y < len(appearance):
                appearance[cursor_y] = highlight_line(appearance[cursor_y], self.text_widget.theme)
        else:
            self._highlight_selection(appearance)
        if self.cursor_x >= len(appearance[0]):
            appearance = fill3.appearance_resize(appearance, (self.cursor_x+1, len(appearance)))
        return appearance

    def set_text(self, text):
        self.text_widget = Code(text, self.path)
        self.decor_widget = Decor(self.text_widget,
                                  lambda appearance: self._add_highlights(appearance))
        self.view_widget = fill3.View.from_widget(self.decor_widget)
        self.view_widget.portal.is_scroll_limited = True
        if not self.is_left_aligned:
            self.view_widget.portal.x_alignment = fill3.Alignment.right
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
        while self._current_character() not in TextEditor.WORD_CHARS:
            self.cursor_right()
        while self._current_character() in TextEditor.WORD_CHARS:
            self.cursor_right()

    def previous_word(self):
        self.cursor_left()
        while self._current_character() not in TextEditor.WORD_CHARS:
            self.cursor_left()
        while self._current_character() in TextEditor.WORD_CHARS:
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

    def center_cursor(self):
        view_x, view_y = self.view_widget.position
        new_y = max(0, self.cursor_y - self.last_height // 2)
        self.view_widget.position = view_x, new_y

    def cycle_syntax_highlighting(self):
        self.theme_index = (self.theme_index + 1) % len(TextEditor.THEMES)
        self.text_widget.theme = self.THEMES[self.theme_index]

    def quit(self):
        fill3.SHUTDOWN_EVENT.set()

    def show_parts_list(self):
        lexer = getattr(self.text_widget, "lexer", None)
        self.parts_widget = Parts(self, self.get_text(), lexer)
        self.is_editing = False
        self.mark = None

    def ring_bell(self):
        if "unittest" not in sys.modules:
            print("\a", end="")

    def add_to_history(self, state=None):
        if state is None:
            lines = self.text_widget.lines.copy()
            cursor_x, cursor_y = self._cursor_x, self._cursor_y
        else:
            lines, cursor_x, cursor_y = state
        if self.history_position < len(self.history):
            self.history.extend(reversed(self.history[self.history_position:-1]))
        self.history.append((lines, cursor_x, cursor_y))
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
        self.mark = None

    def toggle_overwrite(self):
        self.is_overwriting = not self.is_overwriting

    def _work_lines(self):
        if self.mark is None:
            return [self.cursor_y]
        else:
            (start_x, start_y), (end_x, end_y) = self.get_selection_interval()
            return range(start_y + (start_x > 0), end_y + 1 - (end_x == 0))

    def indent(self):
        indent_ = " " * TextEditor.TAB_SIZE
        for line_num in self._work_lines():
            if self.text_widget[line_num].strip() == "":
                self.text_widget[line_num] = ""
                continue
            self.text_widget[line_num] = indent_ + self.text_widget[line_num]
            if self.cursor_y == line_num:
                self.cursor_x += TextEditor.TAB_SIZE

    def dedent(self):
        indent_ = " " * TextEditor.TAB_SIZE
        line_nums = self._work_lines()
        if not all(self.text_widget[line_num].startswith(indent_)
                   or self.text_widget[line_num].strip() == "" for line_num in line_nums):
            self.ring_bell()
            return
        for line_num in line_nums:
            if self.cursor_y == line_num:
                self.cursor_x = max(self.cursor_x - TextEditor.TAB_SIZE, 0)
            if self.text_widget[line_num].strip() == "":
                self.text_widget[line_num] = ""
                continue
            self.text_widget[line_num] = self.text_widget[line_num][TextEditor.TAB_SIZE:]

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
        old_version = self.text_widget.version
        lines_before = self.text_widget.lines.copy()
        cursor_x_before, cursor_y_before = self._cursor_x, self._cursor_y
        if action := (TextEditor.KEY_MAP.get((self.previous_term_code, term_code))
                      or TextEditor.KEY_MAP.get(term_code)):
            try:
                action(self)
            except IndexError:
                self.ring_bell()
        elif not (len(term_code) == 1 and ord(term_code) < 32):
            self.insert_text(term_code, is_overwriting=self.is_overwriting)
        if self.text_widget.version != old_version and action != TextEditor.undo:
            self.add_to_history((lines_before, cursor_x_before, cursor_y_before))
            self.mark = None
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
        match action:
            case terminal.MOUSE_PRESS:
                self.on_mouse_press(x, y)
            case terminal.MOUSE_DRAG:
                self.on_mouse_drag(x, y)
        self.follow_cursor()
        fill3.APPEARANCE_CHANGED_EVENT.set()

    def appearance(self):
        return self.decor_widget.appearance()

    @functools.lru_cache(maxsize=100)
    def get_header(self, path, width, cursor_x, cursor_y, is_changed):
        change_marker = "*" if is_changed else ""
        cursor_position = termstr.TermStr(
            f"Line {cursor_y+1} Column {cursor_x+1:<3}").fg_color(termstr.Color.grey_100)
        path_colored = lscolors.path_colored(path) + change_marker
        path_part = path_colored.ljust(width - len(cursor_position) - 2)
        header = " " + path_part + cursor_position + " "
        return termstr.TermStr(header).bg_color(termstr.Color.grey_30)

    def appearance_for(self, dimensions):
        width, height = dimensions
        if self.parts_widget is None:
            parts_appearance = []
        else:
            self.parts_widget.dimensions = width, height // 5
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
        terminal.CTRL_A: jump_to_start_of_line, terminal.HOME: jump_to_start_of_line,
        terminal.CTRL_E: jump_to_end_of_line, terminal.END: jump_to_end_of_line,
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
        terminal.ALT_H: highlight_block, terminal.CTRL_L: center_cursor,
        terminal.ALT_SEMICOLON: comment_lines, terminal.ALT_c: cycle_syntax_highlighting,
        (terminal.CTRL_X, terminal.CTRL_C): quit, terminal.ESC: show_parts_list,
        terminal.CTRL_K: delete_line, terminal.TAB: tab_align,
        (terminal.CTRL_Q, terminal.TAB): insert_tab, terminal.CTRL_UNDERSCORE: undo,
        terminal.CTRL_Z: undo, terminal.CTRL_G: abort_command, terminal.INSERT: toggle_overwrite,
        (terminal.CTRL_C, ">"): indent, (terminal.CTRL_C, "<"): dedent}


class FileBrowser:

    def __init__(self, paths):
        self.parts = [self._path_colored(path) for path in paths]
        self.cursor = 0

    @staticmethod
    def _path_colored(path):
        return termstr.TermStr(os.path.basename(path), lscolors._charstyle_of_path(path))

    def cursor_left(self):
        self.cursor = (self.cursor - 1) % len(self.parts)

    def cursor_right(self):
        self.cursor = (self.cursor + 1) % len(self.parts)

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


class TextFilesEditor:

    def __init__(self, paths):
        self.paths = paths
        self.file_browser = FileBrowser(paths)
        self.is_browsing = False

    @staticmethod
    @functools.cache
    def get_editor(path):
        editor = TextEditor()
        editor.load(path)
        return editor

    def current_editor(self):
        return self.get_editor(self.paths[self.file_browser.cursor])

    def open_parts_browser(self):
        editor = self.current_editor()
        if editor.parts_widget is None:
            editor.show_parts_list()
            editor.parts_widget.is_focused = False

    def on_keyboard_input(self, term_code):
        if self.is_browsing:
            match term_code:
                case terminal.DOWN:
                    self.is_browsing = False
                    self.current_editor().parts_widget.is_focused = True
                case terminal.LEFT:
                    self.file_browser.cursor_left()
                    self.open_parts_browser()
                case terminal.RIGHT:
                    self.file_browser.cursor_right()
                    self.open_parts_browser()
                case terminal.ESC:
                    self.is_browsing = False
                    self.current_editor().parts_widget.escape_parts_browser()
        elif term_code == terminal.UP and self.current_editor().parts_widget is not None:
            self.is_browsing = True
            self.current_editor().parts_widget.is_focused = False
        else:
            self.current_editor().on_keyboard_input(term_code)
        fill3.APPEARANCE_CHANGED_EVENT.set()

    def on_mouse_input(self, term_code):
        self.current_editor().on_mouse_input(term_code)

    def appearance_for(self, dimensions):
        width, height = dimensions
        if self.is_browsing:
            self.file_browser.dimensions = width, height // 5
            file_browser_appearance = self.file_browser.appearance()
        else:
            file_browser_appearance = []
        editor_dimensions = width, height - len(file_browser_appearance)
        return file_browser_appearance + self.current_editor().appearance_for(editor_dimensions)


def main():
    editor = TextFilesEditor(sys.argv[1:])
    asyncio.run(fill3.tui("Text Editor", editor))


if __name__ == "__main__":
    main()
