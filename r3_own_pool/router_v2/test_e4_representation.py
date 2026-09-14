"""Checks for text preservation and evaluation-label isolation."""
import unittest
import numpy as np
from .experiment_e4_representation import parse_prompt, cross_repeat, FOOTER


def prompt():
    header = ("Answer the following computer science question. The last line of your response should be of the following format: "
              "'Answer: $LETTER' (without quotes) where LETTER is one of ABCDEFGHIJ.")
    options = '\n'.join(f'{c}. option {c}\ncontinued text' for c in 'ABCDEFGHIJ')
    return header + '\n\nA question\nwith multiple paragraphs.\n\n' + options + FOOTER


class RepresentationTests(unittest.TestCase):
    def test_preserve_options_and_multiline_stem(self):
        parsed = parse_prompt(prompt())
        self.assertEqual(parsed['subject'], 'computer science')
        self.assertIn('A question\nwith multiple paragraphs.', parsed['Stem'])
        self.assertNotIn('option A', parsed['Stem'])
        self.assertNotIn('A question', parsed['Options'])
        for c in 'ABCDEFGHIJ':
            self.assertIn(f'{c}. option {c}\ncontinued text', parsed['Options'])
        self.assertNotIn("Let's think", parsed['Content'])
        self.assertNotIn('$LETTER', parsed['Content'])

    def test_reject_malformed_and_empty_options(self):
        for bad in [prompt().replace('B. option B', 'A. option B'),
                    prompt().replace('J. option J\ncontinued text', 'J. '),
                    prompt() + '\nAnswer: A',
                    prompt().replace('question. The last', 'question! The last')]:
            with self.assertRaises(ValueError):
                parse_prompt(bad)

    def test_held_repeat_cannot_affect_its_predictions(self):
        rng = np.random.default_rng(7)
        x = rng.normal(size=(12, 8)).astype('float32')
        v = rng.integers(0, 2, (12, 4, 5)).astype('float32')
        folds = [(np.arange(6), np.arange(6, 12)), (np.arange(6, 12), np.arange(6))]
        _, choices, _, predictions = cross_repeat(x, v, folds)
        changed = v.copy(); changed[:, :, 2] = 1 - changed[:, :, 2]
        _, next_choices, _, next_predictions = cross_repeat(x, changed, folds)
        np.testing.assert_array_equal(choices[:, 2], next_choices[:, 2])
        np.testing.assert_allclose(predictions[:, 2], next_predictions[:, 2])

    def test_test_query_labels_cannot_affect_its_predictions(self):
        rng = np.random.default_rng(9)
        x = rng.normal(size=(12, 8)).astype('float32')
        v = rng.integers(0, 2, (12, 4, 5)).astype('float32')
        folds = [(np.arange(6), np.arange(6, 12)), (np.arange(6, 12), np.arange(6))]
        _, choices, _, predictions = cross_repeat(x, v, folds)
        changed = v.copy(); changed[6:] = 1 - changed[6:]
        _, next_choices, _, next_predictions = cross_repeat(x, changed, folds)
        np.testing.assert_array_equal(choices[6:], next_choices[6:])
        np.testing.assert_allclose(predictions[6:], next_predictions[6:])


if __name__ == '__main__':
    unittest.main()
