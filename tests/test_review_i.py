"""Dávka I po hloubkové revizi (GUI): srozumitelné chybové hlášky, výpadek serveru, protokol enginů neskáče, pořadí fronty klávesnicí."""
from pathlib import Path

APP_JS = (Path(__file__).resolve().parent.parent / "src" / "viddown" / "web" / "app.js").read_text(encoding="utf-8")


def test_server_messages_are_translated_and_network_failure_is_explained():
    assert "function errText(" in APP_JS and "'wrong password'" in APP_JS and "'busy'" in APP_JS
    assert "Server neodpovídá" in APP_JS
    assert "Array.isArray(msg)" in APP_JS                                       # chyba validace (422) není „[object Object]“


def test_engine_log_keeps_the_reading_position_and_ignores_late_responses():
    body = APP_JS[APP_JS.index("async function loadEngines"):APP_JS.index("/* ------------------------------------------------------------ nápověda")]
    assert "keepLog" in body and "App.view !== 'engines' || !$('#eauto')" in body


def test_queue_order_can_be_changed_with_the_keyboard():
    assert "e.altKey" in APP_JS and "ArrowUp" in APP_JS and 'tabindex="0"' in APP_JS
