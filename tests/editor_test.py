#!/usr/bin/env python3


import unittest

import pygments.lexers.python
import termstr

import diff_edit.editor as editor


class TextWidgetTestCase(unittest.TestCase):

    def test_get_text(self):
        text = editor.Text("a")
        self.assertEqual(text.get_text(), "a")

    def test_padding(self):
        text = editor.Text("a\nbb")
        self.assertEqual(text.appearance(), ["a ", "bb"])

    def test_get_line(self):
        text = editor.Text("")
        self.assertEqual(text[0], "")
        text = editor.Text("a\nbb")
        self.assertEqual(text[0], "a")
        self.assertEqual(text[1], "bb")

    def test_change_line(self):
        text = editor.Text("a\nbb")
        text[0] = "aaa"
        self.assertEqual(text.appearance(), ["aaa", "bb "])

    def test_insert_line(self):
        text = editor.Text("a\nbb")
        text.insert(1, "ccc")
        self.assertEqual(text.appearance(), ["a  ", "ccc", "bb "])

    def test_append_line(self):
        text = editor.Text("a")
        text.append("bb")
        self.assertEqual(text.appearance(), ["a ", "bb"])

    def test_replace_lines(self):
        text = editor.Text("a\nbb\nc\nd")
        text[1:3] = ["e", "f", "g"]
        self.assertEqual(text.appearance(), ["a", "e", "f", "g", "d"])

    def test_len(self):
        text = editor.Text("a\nbb\nc\nd")
        self.assertEqual(len(text), 4)

    def test_tabs(self):
        text = editor.Text("a\tb\naa\tb")
        self.assertEqual(text.get_text(), "a\tb\naa\tb")
        self.assertEqual(text.appearance(),
                         [termstr.TermStr("a       b"), termstr.TermStr("aa      b")])
        text = editor.Text("a\tb\tc")
        self.assertEqual(text.appearance(), [termstr.TermStr("a       b       c")])


class WrapTextTestCase(unittest.TestCase):

    def test_wrap_text(self):
        self.assertEqual(editor.wrap_text(["aa", "bb", "cc"], 10),
                         ([" aa bb cc "], [(1, 3), (4, 6), (7, 9)]))
        self.assertEqual(editor.wrap_text(["aa", "bb", "cc"], 5),
                         (["aa bb", "  cc "], [(0, 2), (3, 5), (7, 9)]))


class PartsListTestCase(unittest.TestCase):

    def test_parts_lines(self):
        python_lexer = pygments.lexers.python.PythonLexer()
        theme = pygments.styles.get_style_by_name("paraiso-dark")
        class_charstyle = editor.char_style_for_token_type(pygments.token.Name.Class, theme)
        self.assertEqual(editor.parts_lines("class A:\n    pass", python_lexer, theme),
                         [(termstr.TermStr("top"), 0), (termstr.TermStr("A", class_charstyle), 0),
                          (termstr.TermStr("bottom"), 1)])
        func_charstyle = editor.char_style_for_token_type(pygments.token.Name.Function, theme)
        self.assertEqual(editor.parts_lines("\ndef B:", python_lexer, theme),
                         [(termstr.TermStr("top"), 0), (termstr.TermStr("B", func_charstyle), 1),
                          (termstr.TermStr("bottom"), 1)])


class ExpandTabsTestCase(unittest.TestCase):

    def test_expand_tabs(self):
        self.assertEqual(editor.expandtabs(""), "")
        self.assertEqual(editor.expandtabs("a"), "a")
        self.assertEqual(editor.expandtabs("a\tb"), "a       b")
        self.assertEqual(editor.expandtabs("a♓\tb"), "a♓     b")
        self.assertEqual(editor.expandtabs("c\na♓\tb"), "c\na♓     b")


class TextEditorTestCase(unittest.TestCase):

    def setUp(self):
        self.editor = editor.TextEditor()

    def _assert_editor(self, expected_text, expected_cursor_position):
        cursor_x, cursor_y = expected_cursor_position
        self.assertEqual(self.editor.get_text(), expected_text)
        self.assertEqual(self.editor.cursor_x, cursor_x)
        self.assertEqual(self.editor.cursor_y, cursor_y)

    def _set_editor(self, text, cursor_position):
        self.editor.set_text(text)
        self.editor._cursor_x, self.editor._cursor_y = cursor_position

    def _assert_change(self, method, expected_text, expected_cursor_position):
        method()
        self._assert_editor(expected_text, expected_cursor_position)

    def test_empty_editor(self):
        self._assert_editor("", (0, 0))

    def test_set_text(self):
        self.editor.set_text("foo")
        self.assertEqual(self.editor.get_text(), "foo")

    def test_insert_text(self):
        self.editor.insert_text("a")
        self._assert_editor("a", (1, 0))
        self.editor.insert_text("bc")
        self._assert_editor("abc", (3, 0))
        # overwrite
        self.editor.toggle_overwrite()
        self.editor.cursor_left()
        self.editor.insert_text("d", is_overwriting=True)
        self._assert_editor("abd", (3, 0))
        self.editor.cursor_left()
        self.editor.cursor_left()
        self.editor.insert_text("ef", is_overwriting=True)
        self._assert_editor("aef", (3, 0))

    def test_indent(self):
        # no selection
        self._set_editor("ab", (1, 0))
        self._assert_change(self.editor.indent, "    ab", (5, 0))
        self._set_editor("   ", (1, 0))
        self._assert_change(self.editor.indent, "", (0, 0))
        # on selection
        self._set_editor("a\nb\nc", (0, 0))
        self.editor.set_mark()
        self.editor.cursor_down()
        self._assert_change(self.editor.indent, "    a\nb\nc", (0, 1))
        self._set_editor("a\nb\nc", (1, 0))
        self.editor.set_mark()
        self.editor.cursor_left()
        self.editor.cursor_down()
        self.editor.cursor_down()
        self._assert_change(self.editor.indent, "a\n    b\nc", (0, 2))
        self._set_editor("a\nb\nc", (0, 1))
        self.editor.set_mark()
        self.editor.cursor_down()
        self.editor.cursor_right()
        self._assert_change(self.editor.indent, "a\n    b\n    c", (5, 2))

    def test_dedent(self):
        # no selection
        self._set_editor("    ab", (2, 0))
        self._assert_change(self.editor.dedent, "ab", (0, 0))
        self._set_editor("    ab", (5, 0))
        self._assert_change(self.editor.dedent, "ab", (1, 0))
        self._set_editor("   ab", (0, 0))
        self._assert_change(self.editor.dedent, "   ab", (0, 0))
        self._set_editor("   ", (1, 0))
        self._assert_change(self.editor.dedent, "", (0, 0))
        # on selection
        self._set_editor("    a\n  \n    b", (0, 0))
        self.editor.set_mark()
        self.editor.cursor_down()
        self.editor.cursor_down()
        self._assert_change(self.editor.dedent, "a\n\n    b", (0, 2))

    def test_enter(self):
        self._set_editor("ab", (1, 0))
        self.editor.enter()
        self._assert_editor("a\nb", (0, 1))

    def test_delete_character(self):
        self._set_editor("ab\nc", (1, 0))
        self._assert_change(self.editor.delete_character, "a\nc", (1, 0))
        self._assert_change(self.editor.delete_character, "ac", (1, 0))
        self._assert_change(self.editor.delete_character, "a", (1, 0))
        self.assertRaises(IndexError, self.editor.delete_character)

    def test_backspace(self):
        self._set_editor("a\n"
                         "bcd", (2, 1))
        self._assert_change(self.editor.backspace, "a\nbd", (1, 1))
        self._assert_change(self.editor.backspace, "a\nd", (0, 1))
        self._assert_change(self.editor.backspace, "ad", (1, 0))
        self._assert_change(self.editor.backspace, "d", (0, 0))
        self._assert_change(self.editor.backspace, "d", (0, 0))

    def test_cursor_movement(self):
        text = ("a\n"
                "bc")
        self._set_editor(text, (0, 0))
        self.assertRaises(IndexError, self.editor.cursor_up)
        self.assertRaises(IndexError, self.editor.cursor_left)
        self._assert_change(self.editor.cursor_right, text, (1, 0))
        self._assert_change(self.editor.cursor_right, text, (0, 1))
        self._assert_change(self.editor.cursor_left, text, (1, 0))
        self._assert_change(self.editor.cursor_down, text, (1, 1))
        self._assert_change(self.editor.cursor_right, text, (2, 1))
        self.assertRaises(IndexError, self.editor.cursor_right)
        self._assert_change(self.editor.cursor_up, text, (1, 0))
        self._assert_change(self.editor.cursor_down, text, (2, 1))
        self._assert_change(self.editor.jump_to_start_of_line, text, (0, 1))
        self._assert_change(self.editor.jump_to_end_of_line, text, (2, 1))
        text = ("♓\n"
                "bc")
        self._set_editor(text, (0, 0))
        self._assert_change(self.editor.cursor_right, text, (1, 0))
        self._assert_change(self.editor.cursor_down, text, (2, 1))

    def test_jumping_words(self):
        text = ("ab .dj\n"
                " bc*d")
        self._set_editor(text, (0, 0))
        self._assert_change(self.editor.next_word, text, (2, 0))
        self._assert_change(self.editor.next_word, text, (6, 0))
        self._assert_change(self.editor.next_word, text, (3, 1))
        self._assert_change(self.editor.next_word, text, (5, 1))
        self.assertRaises(IndexError, self.editor.next_word)
        self._assert_change(self.editor.previous_word, text, (4, 1))
        self._assert_change(self.editor.previous_word, text, (1, 1))
        self._assert_change(self.editor.previous_word, text, (4, 0))
        self.assertRaises(IndexError, self.editor.previous_word)
        self._assert_editor(text, (0, 0))
        self.assertRaises(IndexError, self.editor.previous_word)
        self._assert_editor(text, (0, 0))

    def test_jumping_blocks(self):
        text = "a\nb\n\nc\nd"
        self._set_editor(text, (0, 0))
        self.assertRaises(IndexError, self.editor.jump_to_block_start)
        self._assert_change(self.editor.jump_to_block_end, text, (0, 2))
        self.assertRaises(IndexError, self.editor.jump_to_block_end)
        self._assert_editor(text, (0, 4))
        self.assertRaises(IndexError, self.editor.jump_to_block_end)
        self._assert_editor(text, (0, 4))

    def test_page_up_and_down(self):
        text = "a\nbb\nc\nd"
        self._set_editor(text, (1, 1))
        self._assert_change(self.editor.page_up, text, (0, 0))
        self._assert_change(self.editor.page_up, text, (0, 0))
        self._assert_change(self.editor.page_down, text, (0, 3))
        self._assert_change(self.editor.page_down, text, (0, 3))

    def test_join_lines(self):
        self._set_editor(" \nab-  \n  -cd  ", (4, 2))
        self._assert_change(self.editor.join_lines, " \nab- -cd  ", (3, 1))
        self._assert_change(self.editor.join_lines, "ab- -cd  ", (0, 0))
        self._assert_change(self.editor.join_lines, "ab- -cd  ", (0, 0))

    def test_delete_line(self):
        self._set_editor("a  \ndef", (1, 0))
        self._assert_change(self.editor.delete_line, "adef", (1, 0))
        self._assert_change(self.editor.delete_line, "a", (1, 0))
        self._set_editor("\nabc", (0, 0))
        self._assert_change(self.editor.delete_line, "abc", (0, 0))
        self._assert_change(self.editor.delete_line, "", (0, 0))
        self.assertRaises(IndexError, self.editor.delete_line)

    def test_tab_align(self):
        text = " a\n  b"
        self._set_editor(text, (0, 0))
        self._assert_change(self.editor.tab_align, text, (0, 0))
        self._assert_change(self.editor.cursor_down, text, (0, 1))
        self._assert_change(self.editor.tab_align, " a\n b", (1, 1))

    def test_comment_lines(self):
        # from scratch
        self._set_editor("", (0, 0))
        self._assert_change(self.editor.comment_lines, "# ", (2, 0))
        # No selection
        self._set_editor("a", (0, 0))
        self._assert_change(self.editor.comment_lines, "a  # ", (5, 0))
        # Comment when comment exists
        self.editor.jump_to_start_of_line()
        self._assert_change(self.editor.comment_lines, "a  # ", (4, 0))
        # Selection containing blank lines
        text = "  a\n\n b\n"
        self._set_editor(text, (0, 0))
        self.editor.set_mark()
        self.editor.cursor_down()
        self.editor.cursor_down()
        self.editor.cursor_down()
        self._assert_change(self.editor.comment_lines, " #  a\n\n # b\n", (0, 3))
        self.assertEqual(self.editor.mark, None)
        # Undo comments in selection
        self.editor.set_mark()
        self.editor.cursor_up()
        self.editor.cursor_up()
        self.editor.cursor_up()
        self._assert_change(self.editor.comment_lines, text, (0, 0))
        # Selection on one line, in middle
        self._set_editor("abc", (1, 0))
        self.editor.set_mark()
        self.editor.cursor_right()
        self._assert_change(self.editor.comment_lines, "a# b\nc", (4, 0))
        # Selection on one line, on right
        self._set_editor("ab", (1, 0))
        self.editor.set_mark()
        self.editor.cursor_right()
        self._assert_change(self.editor.comment_lines, "a# b", (4, 0))
        # Multi-line selection, starting middle, ending middle. Trailing unselected line
        self._set_editor("abc\ndef\nghi\njkl", (2, 0))
        self.editor.set_mark()
        self.editor.cursor_down()
        self.editor.cursor_down()
        self._assert_change(self.editor.comment_lines, "ab# c\n# def\n# gh\ni\njkl", (4, 2))

    def test_undo(self):
        self._set_editor("ab", (1, 0))
        self.editor.add_to_history()
        self.editor.enter()
        self.editor.add_to_history()
        self.editor.enter()
        self._assert_change(self.editor.undo, "a\nb", (0, 1))
        self._assert_change(self.editor.undo, "ab", (1, 0))

    def test_abort_command(self):
        self._set_editor("", (0, 0))
        self.editor.set_mark()
        self.editor.abort_command()
        self.assertEqual(self.editor.mark, None)

    def test_expand_str_inverse(self):
        self.assertEqual(editor.expand_str_inverse(""), [])
        self.assertEqual(editor.expand_str_inverse("a"), [0])
        self.assertEqual(editor.expand_str_inverse("a\tb"), [0, 1, 1, 1, 1, 1, 1, 1, 2])
        self.assertEqual(editor.expand_str_inverse("aaaaaaaaaa\t"),
                         [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 10, 10, 10, 10])
        self.assertEqual(editor.expand_str_inverse("a\tb\tc"),
                         [0, 1, 1, 1, 1, 1, 1, 1, 2, 3, 3, 3, 3, 3, 3, 3, 4])
        self.assertEqual(editor.expand_str_inverse("♓"), [0, 0])
        self.assertEqual(editor.expand_str_inverse("♓\tb"), [0, 0, 1, 1, 1, 1, 1, 1, 2])


if __name__ == "__main__":
    unittest.main()
