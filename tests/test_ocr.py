import unittest

from roku_stream.ocr import OcrObservation, OcrWord


def word(text: str, left: int = 0, confidence: float = 90.0) -> OcrWord:
    return OcrWord(text, confidence, left, 0, 40, 30, 1, 1, 1)


class OcrObservationTests(unittest.TestCase):
    def test_espn_does_not_match_espn2_token(self) -> None:
        observation = OcrObservation((word("ESPN2"),))
        self.assertEqual(observation.find_names(["ESPN"]), [])
        self.assertEqual(
            observation.find_names(["ESPN2"])[0]["configured_name"], "ESPN2"
        )

    def test_split_network_name_matches_on_same_line(self) -> None:
        observation = OcrObservation((word("MLB"), word("Network", left=50)))
        match = observation.find_names(["MLB Network"])[0]
        self.assertEqual(match["normalized"], "mlbnetwork")


if __name__ == "__main__":
    unittest.main()
