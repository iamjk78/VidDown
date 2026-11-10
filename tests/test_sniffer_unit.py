from viddown.resolvers.sniffer import parse_netscape_cookies


def test_cookie_expiry_in_milliseconds_is_converted(tmp_path):
    f = tmp_path / "cookies.txt"
    f.write_text(
        "# Netscape HTTP Cookie File\n"
        ".example.com\tTRUE\t/\tTRUE\t1794769255661\tms\tv1\n"      # milisekundy (Firefox)
        ".example.com\tTRUE\t/\tFALSE\t1794769255\tsec\tv2\n"        # sekundy
        ".example.com\tTRUE\t/\tFALSE\t0\tsession\tv3\n"             # relační
        "#HttpOnly_.example.com\tTRUE\t/\tTRUE\t1794769255\thttp\tv4\n")
    c = {x["name"]: x for x in parse_netscape_cookies(f)}
    assert c["ms"]["expires"] == 1794769255
    assert c["sec"]["expires"] == 1794769255
    assert "expires" not in c["session"]
    assert c["http"]["domain"] == ".example.com" and c["http"]["secure"] is True
