import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import photo_tools


class MovingBackground(unittest.TestCase):
    def test_each_frame_moves_and_is_not_a_copy_of_the_person(self):
        person = np.zeros((48, 64, 3), dtype=np.uint8)
        person[:, :] = (20, 30, 40)
        first = photo_tools._moving_background(person.shape, 0, 10)
        later = photo_tools._moving_background(person.shape, 5, 10)
        self.assertFalse(np.array_equal(first, later))
        self.assertFalse(np.array_equal(first, person))
        self.assertGreater(float(np.std(first)), 10)

    def test_mask_change_is_zero_until_the_mask_moves(self):
        still = np.zeros((20, 20), dtype=np.uint8)
        still[4:16, 4:16] = 255
        quiet = photo_tools._mask_edge(still, None, still)
        moved = still.copy()
        moved[:, 1:] = still[:, :-1]
        changed = photo_tools._mask_edge(moved, None, still)
        self.assertEqual(quiet["mask_change"], 0.0)
        self.assertGreater(changed["mask_change"], 0)


if __name__ == "__main__":
    unittest.main()
