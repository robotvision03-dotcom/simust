"""Opening card must replace the previous results clip before the next test."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import smart_simust_player as player


def _window():
    win = player.SmartPlayerWindow.__new__(player.SmartPlayerWindow)
    win.results_timer = None
    win.player = _Player()
    win.instance = _Instance()
    win.videoframe = _Frame()
    win.operator_paused = False
    win.display_phase = "per_video_results"
    win._results_epoch = 0
    win._results_finished_epoch = None
    win._level_card_shown_for = 1
    win.cards = []
    win.stopped = 0
    win.played = []
    win.video_files = [f"clip-{i}.mp4" for i in range(12)]
    win._post_results_index = 1
    win.playlist_finished = False
    win.waiting_for_results = True
    win._clear_held_results = lambda: None

    def show_card(next_index=0, after="intro"):
        win.cards.append((int(next_index), after))
        win.display_phase = "level_card"

    def play_intro(next_index=0, after="start"):
        win.played.append((int(next_index), after))

    win._show_level_card = show_card
    win._play_level_intro = play_intro
    win._do_continue = player.SmartPlayerWindow._do_continue.__get__(win, player.SmartPlayerWindow)
    return win


class _Player:
    def stop(self):
        self.stopped = True

    def set_media(self, media):
        self.media = media


class _Instance:
    def media_new(self, path):
        return path


class _Frame:
    def hide(self):
        self.hidden = True


class LevelSequenceTests(unittest.TestCase):
    def test_next_test_shows_opening_card_after_results(self):
        win = _window()
        win.display_phase = "per_video_results"
        win._begin_level_intro(1)
        self.assertEqual(win.cards, [(1, "intro")])
        self.assertTrue(win.videoframe.hidden)
        self.assertEqual(win.played, [])

    def test_stale_results_do_not_replay(self):
        win = _window()
        win.display_phase = "level_card"
        win._results_epoch = 4
        win._play_per_video_results("old-results.mp4", epoch=3)
        self.assertEqual(win.display_phase, "level_card")

    def test_results_finish_advances_once(self):
        win = _window()
        win.display_phase = "per_video_results"
        win._results_epoch = 2
        advanced = []
        win._begin_level_intro = lambda idx=0: advanced.append(int(idx))
        player.SmartPlayerWindow._finish_per_video_results(win)
        player.SmartPlayerWindow._finish_per_video_results(win)
        self.assertEqual(advanced, [1])


if __name__ == "__main__":
    unittest.main()
