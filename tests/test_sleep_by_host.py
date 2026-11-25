"""Prodleva po zdrojích: vlastní rozsah pro web (sleep_by_host) přepíše výchozí hodnoty, validace hodnot."""
import pytest

from viddown import config
from viddown.runner import Runner


def test_youtube_variants_are_one_host_and_www_is_dropped():
    out = config.normalize_sleep_hosts([
        {"host": "www.Example.com", "min": 10, "max": 20},
        {"host": "youtu.be", "min": 1, "max": 2},
        {"host": "music.youtube.com", "min": 3, "max": 4},
    ])
    assert {e["host"] for e in out} == {"example.com", "youtube.com"}
    assert [e for e in out if e["host"] == "youtube.com"][0]["max"] == 4.0   # poslední zápis pro stejný web vyhrává


@pytest.mark.parametrize("bad", [
    [{"host": "", "min": 1, "max": 2}],
    [{"host": "a.example/path", "min": 1, "max": 2}],
    [{"host": "a.example", "min": 5, "max": 2}],          # max < min
    [{"host": "a.example", "min": 0, "max": 601}],         # nad 600 s
    [{"host": "a.example", "min": True, "max": 2}],        # bool není číslo
    [{"host": "a.example", "min": "1", "max": "2"}],       # řetězec není číslo
    ["a.example"],
    "a.example",
])
def test_invalid_entries_are_refused(bad):
    with pytest.raises(ValueError):
        config.normalize_sleep_hosts(bad)


def test_custom_range_overrides_defaults():
    s = {"sleep_min": 5, "sleep_max": 15, "sleep_youtube_min": 30, "sleep_youtube_max": 60,
         "sleep_by_host": [{"host": "example.com", "min": 40, "max": 40}]}
    assert Runner._sleep_for("example.com", s) == 40.0
    assert 30 <= Runner._sleep_for("youtube.com", s) <= 60          # bez vlastního záznamu zůstává výchozí pro YouTube
    assert 5 <= Runner._sleep_for("other.example", s) <= 15         # a výchozí pro ostatní weby
