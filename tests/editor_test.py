#!/usr/bin/env python3


import contextlib
import unittest

import diff_edit.editor as editor


class TextWidgetTestCase(unittest.TestCase):

    def test_get_text(self):
        text = editor.Text("a")
        self.assertEqual(text.get_text(), "a")

    def test_padding(self):
        text = editor.Text("a\nbb")
        self.assertEqual(text.appearance_min(), ["a ", "bb"])

    def test_get_line(self):
        text = editor.Text("")
        self.assertEqual(text[0], "")
        text = editor.Text("a\nbb")
        self.assertEqual(text[0], "a")
        self.assertEqual(text[1], "bb")

    def test_change_line(self):
        text = editor.Text("a\nbb")
        text[0] = "aaa"
        self.assertEqual(text.appearance_min(), ["aaa", "bb "])

    def test_insert_line(self):
        text = editor.Text("a\nbb")
        text.insert(1, "ccc")
        self.assertEqual(text.appearance_min(), ["a  ", "ccc", "bb "])

    def test_append_line(self):
        text = editor.Text("a")
        text.append("bb")
        self.assertEqual(text.appearance_min(), ["a ", "bb"])

    def test_replace_lines(self):
        text = editor.Text("a\nbb\nc\nd")
        text[1:3] = ["e", "f", "g"]
        self.assertEqual(text.appearance_min(), ["a", "e", "f", "g", "d"])

    def test_len(self):
        text = editor.Text("a\nbb\nc\nd")
        self.assertEqual(len(text), 4)


class EditorTestCase(unittest.TestCase):

    def setUp(self):
        self.editor = editor.Editor()

    def _assert_editor(self, expected_text, expected_cursor_position):
        cursor_x, cursor_y = expected_cursor_position
        self.assertEqual(self.editor.get_text(), expected_text)
        self.assertEqual(self.editor.cursor_x, cursor_x)
        self.assertEqual(self.editor.cursor_y, cursor_y)

    def _set_editor(self, text, cursor_position):
        self.editor.set_text(text)
        self.editor.cursor_x, self.editor.cursor_y = cursor_position

    def _assert_changes(self, changes):
        for index, change in enumerate(changes):
            with self.subTest(index=index, change=change):
                method, expected_text, expected_cursor_position = change
                with contextlib.suppress(IndexError):
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

    def test_enter(self):
        self._set_editor("ab", (1, 0))
        self.editor.enter()
        self._assert_editor("a\nb", (0, 1))

    def test_delete_character(self):
        self._set_editor("ab\nc", (1, 0))
        self._assert_changes([(self.editor.delete_character, "a\nc", (1, 0)),
                              (self.editor.delete_character, "ac", (1, 0)),
                              (self.editor.delete_character, "a", (1, 0)),
                              (self.editor.delete_character, "a", (1, 0))])

    def test_backspace(self):
        self._set_editor("a\n"
                         "bcd", (2, 1))
        self._assert_changes([(self.editor.backspace, "a\n"
                                                      "bd", (1, 1)),
                              (self.editor.backspace, "a\nd", (0, 1)),
                              (self.editor.backspace, "ad", (1, 0)),
                              (self.editor.backspace, "d", (0, 0)),
                              (self.editor.backspace, "d", (0, 0))])

    def test_cursor_movement(self):
        text = ("a\n"
                "bc")
        self._set_editor(text, (0, 0))
        up, down = self.editor.cursor_up, self.editor.cursor_down
        left, right = self.editor.cursor_left, self.editor.cursor_right
        self._assert_changes([
            (up, text, (0, 0)), (left, text, (0, 0)), (right, text, (1, 0)),
            (right, text, (0, 1)), (left, text, (1, 0)), (down, text, (1, 1)),
            (right, text, (2, 1)), (right, text, (2, 1)), (up, text, (1, 0)),
            (down, text, (2, 1)),
            (self.editor.jump_to_start_of_line, text, (0, 1)),
            (self.editor.jump_to_end_of_line, text, (2, 1))])

    def test_jumping_words(self):
        text = ("ab .dj\n"
                " bc*d")
        self._set_editor(text, (0, 0))
        next, previous = self.editor.next_word, self.editor.previous_word
        self._assert_changes([
            (next, text, (2, 0)), (next, text, (6, 0)), (next, text, (3, 1)),
            (next, text, (5, 1)), (next, text, (5, 1)),
            (previous, text, (4, 1)), (previous, text, (1, 1)),
            (previous, text, (4, 0)), (previous, text, (0, 0)),
            (previous, text, (0, 0))])

    def test_jumping_blocks(self):
        text = "a\nb\n\nc\nd"
        self._set_editor(text, (0, 0))
        self._assert_changes([(self.editor.jump_to_block_start, text, (0, 0)),
                              (self.editor.jump_to_block_end, text, (0, 2)),
                              (self.editor.jump_to_block_end, text, (0, 4)),
                              (self.editor.jump_to_block_end, text, (0, 4))])

    def test_page_up_and_down(self):
        text = "a\nbb\nc\nd"
        self._set_editor(text, (1, 1))
        self._assert_changes([(self.editor.page_up, text, (0, 0)),
                              (self.editor.page_up, text, (0, 0)),
                              (self.editor.page_down, text, (0, 3)),
                              (self.editor.page_down, text, (0, 3))])

    def test_join_lines(self):
        text = " \nab-  \n  -cd  "
        self._set_editor(text, (4, 2))
        self._assert_changes([(self.editor.join_lines, " \nab- -cd  ", (3, 1)),
                              (self.editor.join_lines, "ab- -cd  ", (0, 0)),
                              (self.editor.join_lines, "ab- -cd  ", (0, 0))])


if __name__ == "__main__":
    unittest.main()
