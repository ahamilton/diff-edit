#!/usr/bin/env python3


import unittest

import diff_edit


class OverlayListTestCase(unittest.TestCase):

    def test_overlay_list(self):
        self.assertEqual(diff_edit.overlay_list([1, 2, 3, 4], [5, 6], 0), [5, 6, 3, 4])
        self.assertEqual(diff_edit.overlay_list([1, 2, 3, 4], [5, 6], 3), [1, 2, 3, 5])
        self.assertEqual(diff_edit.overlay_list([1, 2, 3, 4], [5, 6], -1), [6, 2, 3, 4])
        self.assertEqual(diff_edit.overlay_list([5, 6], [1, 2, 3, 4], -1), [2, 3])

    
if __name__ == "__main__":
    unittest.main()
