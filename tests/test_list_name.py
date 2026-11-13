from viddown.util import url_list_name


def test_model_page_gets_name_and_is_channel():
    assert url_list_name("https://video.example/model/nejaky-autor/videos") == ("nejaky-autor", True)


def test_plain_playlist_has_no_name():
    assert url_list_name("https://example.com/playlist?list=abc") == (None, False)


def test_dashes_become_spaces():
    assert url_list_name("https://x.com/channels/my-cool-channel") == ("my cool channel", True)
